"""弹幕解析的离线用例：不联网，只喂构造出来的字节。

覆盖几个真机上踩过的点：``op=5`` 的 body 是多条包的拼接；拆出来的子包仍带 ``op=5``
但版本降为 0，不能被再当包头读一次；以及一帧 WebSocket 数据被拆成两次 recv 到达。
"""

import json
import struct
import unittest
import zlib
from datetime import datetime

from bilibili import danmaku
from bilibili.danmaku import (OP_MESSAGE, build_packet, encode_frame, split_frames,
                              split_packets, to_danmaku)


def danmaku_packet(text: str, nickname: str = "用户A", ms: int = 1_760_000_000_000) -> bytes:
    payload = {"cmd": "DANMU_MSG",
               "info": [[0, 1, 25, 0, ms, 0, 0, "", 1, 1, 1, "", 1, 0, 0, 0, 0, 0],
                        text, [12345, nickname, 0, 0, 0, 0, 0, 0, 0], []]}
    return build_packet(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        OP_MESSAGE, version=2)


class PacketSplitTests(unittest.TestCase):
    def test_bundle_of_two_packets_is_split(self):
        buf = danmaku_packet("点歌 起风了") + danmaku_packet("主播好")
        packets, leftover = split_packets(buf)
        self.assertEqual(len(packets), 2)
        self.assertEqual(leftover, b"")
        texts = [json.loads(body.decode("utf-8"))["info"][1] for _v, _op, body in packets]
        self.assertEqual(texts, ["点歌 起风了", "主播好"])

    def test_a_plain_json_body_is_not_reparsed_as_a_header(self):
        body = b'[{"cmd":"DANMU_MSG","info":[[0],"\xe7\x82\xb9\xe6\xad\x8c Lemon"]}]'
        buf = struct.pack(">IHHII", 16 + len(body), 16, 0, OP_MESSAGE, 1) + body
        packets, leftover = split_packets(buf)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0][2], body)
        self.assertEqual(leftover, b"")

    def test_a_partial_packet_is_held_back(self):
        buf = danmaku_packet("点歌 起风了")
        packets, leftover = split_packets(buf[:len(buf) - 3])
        self.assertEqual(packets, [])
        self.assertEqual(leftover, buf[:len(buf) - 3])


class FrameSplitTests(unittest.TestCase):
    def test_a_frame_arriving_in_two_reads_is_rejoined(self):
        """照 DanmakuStream 里的真实累积写法：残片留在缓冲区，下一段接上再解一次。"""
        payload = b"hello-world, this is a bilibili chat frame"
        frame = encode_frame(payload)
        buf = b""
        got = []
        for piece in (frame[:5], frame[5:11], frame[11:]):
            buf += piece
            frames, frag, buf = split_frames(buf)
            got.extend(frames)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], payload)
        self.assertEqual(buf, b"")

    def test_zlib_roundtrip_survives_a_packet(self):
        from bilibili.danmaku import OP_JOIN

        body = json.dumps({"roomid": 21452505}).encode("utf-8")
        wire = build_packet(body, OP_JOIN, version=2)
        total, hlen, version, op, _seq = struct.unpack(">IHHII", wire[:16])
        self.assertEqual((hlen, version, op), (16, 2, OP_JOIN))
        self.assertEqual(total, len(wire))
        self.assertEqual(zlib.decompress(wire[16:]), body)


class ToDanmakuTests(unittest.TestCase):
    def test_reads_text_user_and_server_time(self):
        payload = {"cmd": "DANMU_MSG",
                   "info": [[0, 1, 25, 0, 1_760_000_000_000], "点歌 Lemon",
                            [1, "用户A"], []]}
        message = to_danmaku(payload)
        self.assertEqual((message.username, message.text), ("用户A", "点歌 Lemon"))
        self.assertEqual(message.timestamp, datetime.fromtimestamp(1_760_000_000))

    def test_ignores_gifts_and_empty_messages(self):
        self.assertIsNone(to_danmaku({"cmd": "SEND_GIFT", "data": {}}))
        self.assertIsNone(to_danmaku({"cmd": "DANMU_MSG", "info": [[0], "  ", [1, "用户A"]]}))


class ConnInfoRouteTests(unittest.TestCase):
    """取 token 那条路：worker 只认 POST，GET 会被 Cloudflare 挡成 403。"""

    def setUp(self):
        self.calls = []
        self._post = danmaku._post_json
        self._get = danmaku._get_json
        danmaku._post_json = lambda url, headers=None, body=None, timeout=15.0: (
            self.calls.append(("POST", url)) or {"code": 0,
                                                 "data": {"token": "tk", "host_list": []}})
        danmaku._get_json = lambda url, headers=None, timeout=15.0: (
            self.calls.append(("GET", url)) or {})
        self.addCleanup(lambda: setattr(danmaku, "_post_json", self._post))
        self.addCleanup(lambda: setattr(danmaku, "_get_json", self._get))

    def test_anonymous_route_posts_the_room_id_and_keeps_the_hosts(self):
        info = danmaku.fetch_conn_info("21452505")
        self.assertEqual([m for m, _u in self.calls], ["POST"])
        self.assertTrue(self.calls[0][1].endswith("/room-conn-info-v2/21452505"))
        self.assertEqual((info.token, info.origin), ("tk", "anonymous worker"))
        # worker 不回 host_list 时必须退回内置的两个聊天域名，否则没地方可连
        self.assertEqual(info.hosts, danmaku.DEFAULT_HOSTS)

    def test_cookie_route_is_tried_first(self):
        try:
            danmaku.fetch_conn_info("21452505", cookie="SESSDATA=x")
        except danmaku.DanmakuError:
            pass
        self.assertEqual([m for m, _u in self.calls], ["GET", "POST"])


if __name__ == "__main__":
    unittest.main()
