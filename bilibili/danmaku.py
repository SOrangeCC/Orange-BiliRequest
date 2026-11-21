"""B站直播弹幕抓取：conn-info 拿 token，WebSocket 收 DANMU_MSG。

协议细节沿用 Orange BLiveClip 在真实直播间实测到的结论：

* 聊天服务器在收到带 ``key`` 的 Auth 包之前不回任何数据，匿名调用官方 conn-info 返回 -352，
  所以默认走匿名 worker 取 token（无需登录），可选用 cookie 走官方接口。
* Auth 用现代扁平包，教程里常见的 ``{"cmd":"Auth","args":[...]}`` 会被立刻拒绝。
* ``protover=2`` 让服务器回 zlib 包装的 JSON；``3`` 回 protobuf，本项目不解。
* ``op=5`` 的 body 可能是若干条完整包的拼接，必须再切一次；而切出来的子包仍带 ``op=5``
  但版本降为 0，所以拆分只能在“这段 body 不是在描述包”时停下，否则会把 JSON 的头 16 字节
  当成包头。
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, List, Optional, Tuple

#: 匿名 worker：第三方服务，无契约，随时可能停；官方的 -352 就是它存在的原因。
WORKER_URL = "https://workers.laplace.cn/bilibili/room-conn-info-v2/"
DANMUINFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"
SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
DEFAULT_HOSTS = ("broadcastlv.chat.bilibili.com", "broadcastlv-mixed.chat.bilibili.com")
WS_PORT = 443
WS_PATH = "/sub"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

OP_HEARTBEAT = 2
OP_HEARTBEAT_REPLY = 3
OP_MESSAGE = 5
OP_JOIN = 7
OP_AUTH_REPLY = 8

#: 低于这个数值的 epoch 毫秒不是时钟：DANMU_MSG 的 ``info[0]`` 里混着秒级和别的数字。
PLAUSIBLE_EPOCH_MS = 10 ** 12

HEARTBEAT_SECONDS = 25.0
RECONNECT_AFTER_SECONDS = 1800.0


class DanmakuError(RuntimeError):
    """取不到 token、连不上聊天服务器、或连接被拒绝。"""


@dataclass(frozen=True)
class Danmaku:
    """统一后的弹幕结构。"""

    username: str
    text: str
    timestamp: datetime


@dataclass(frozen=True)
class ConnInfo:
    token: str
    hosts: Tuple[str, ...]
    origin: str

    def __repr__(self) -> str:
        return f"ConnInfo(origin={self.origin!r}, hosts={list(self.hosts)}, token=***)"


def _get_json(url: str, headers: Optional[dict] = None, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA,
                                               "Accept": "application/json",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _post_json(url: str, headers: Optional[dict] = None, body: Optional[dict] = None,
               timeout: float = 15.0) -> dict:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"User-Agent": BROWSER_UA,
                                          "Accept": "application/json",
                                          "Content-Type": "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _hosts_of(data: dict) -> Tuple[str, ...]:
    hosts = tuple(str(e.get("host")) for e in (data.get("host_list") or [])
                  if isinstance(e, dict) and e.get("host"))
    return hosts or DEFAULT_HOSTS


def mint_buvid() -> str:
    """匿名设备号，Auth 包要带；它不是登录，也不授予任何权限。"""
    try:
        data = _get_json(SPI_URL, {"Referer": "https://live.bilibili.com/"}).get("data") or {}
    except Exception:
        return ""
    return str(data.get("b_3") or "") if isinstance(data, dict) else ""


def buvid_from_cookie(cookie: str) -> str:
    for part in str(cookie or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "buvid3":
            return value.strip()
    return ""


def fetch_conn_info(room_id: str, cookie: str = "") -> ConnInfo:
    """给这个房间取一个聊天 token：cookie 优先（官方），否则匿名 worker。"""
    key = str(room_id or "").strip()
    if not key.isdigit():
        raise DanmakuError(f"房间号必须是数字，收到 {key!r}")
    failures: List[str] = []

    if cookie:
        url = f"{DANMUINFO_URL}?{urllib.parse.urlencode({'id': key, 'type': 0})}"
        try:
            envelope = _get_json(url, {"Cookie": cookie,
                                       "Referer": f"https://live.bilibili.com/{key}"})
            data = envelope.get("data") or {}
            if envelope.get("code") == 0 and data.get("token"):
                return ConnInfo(str(data["token"]), _hosts_of(data), "bilibili (cookie)")
            failures.append(f"官方接口 code={envelope.get('code')}")
        except Exception as e:
            failures.append(f"官方接口失败 {type(e).__name__}")

    try:
        # POST 而不是 GET：GET 会被 Cloudflare 挡成 403 挑战页，BLiveClip 实测走的是空 JSON 体。
        envelope = _post_json(WORKER_URL + urllib.parse.quote(key, safe=""),
                              {"Origin": "https://chat.laplace.live",
                               "Referer": "https://chat.laplace.live/"})
        data = envelope.get("data") or {}
        if envelope.get("code") == 0 and data.get("token"):
            return ConnInfo(str(data["token"]), _hosts_of(data), "anonymous worker")
        failures.append(f"匿名 worker code={envelope.get('code')}")
    except Exception as e:
        code = getattr(e, "code", None)
        failures.append(f"匿名 worker 失败 {type(e).__name__}"
                        + (f" HTTP {code}" if code else ""))

    raise DanmakuError("拿不到聊天 token：" + "; ".join(failures))


def encode_frame(payload: bytes, opcode: int = 0x2) -> bytes:
    """客户端 -> 服务器的一个 WebSocket 帧：FIN、带掩码、不分片。"""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < (1 << 16):
        header.append(0x80 | 126)
        header += struct.pack(">H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", length)
    mask = os.urandom(4)
    header += mask
    return bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def build_packet(body: bytes, op: int, version: int = 1) -> bytes:
    payload = zlib.compress(body) if version == 2 else body
    return struct.pack(">IHHII", 16 + len(payload), 16, version, op, 1) + payload


def split_packets(buf: bytes) -> Tuple[List[Tuple[int, int, bytes]], bytes]:
    out: List[Tuple[int, int, bytes]] = []
    while len(buf) >= 16:
        total, _hlen, version, op, _seq = struct.unpack(">IHHII", buf[:16])
        if total < 16 or total > len(buf):
            break
        body, buf = buf[16:total], buf[total:]
        if version in (2, 3):
            try:
                body = zlib.decompress(body)
            except zlib.error:
                out.append((version, op, body))
                continue
        if op != OP_MESSAGE:
            out.append((version, op, body))
            continue
        nested, remainder = split_packets(body)
        out.extend(nested or [(version, op, body)])
        del remainder
    return out, buf


def split_frames(buf: bytes, frag: Optional[Tuple[int, bytes]] = None
                 ) -> Tuple[List[Tuple[int, bytes]], Optional[Tuple[int, bytes]], bytes]:
    """解出完整的 WebSocket 帧，顺带把服务器分片发出的帧拼回去。"""
    frames: List[Tuple[int, bytes]] = []
    pos = 0
    while len(buf) - pos >= 2:
        first, second = buf[pos], buf[pos + 1]
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
        head = pos + 2
        if length == 126:
            if len(buf) - head < 2:
                break
            length = struct.unpack(">H", buf[head:head + 2])[0]
            head += 2
        elif length == 127:
            if len(buf) - head < 8:
                break
            length = struct.unpack(">Q", buf[head:head + 8])[0]
            head += 8
        masked = bool(second & 0x80)
        if masked:
            if len(buf) - head < 4:
                break
            head += 4
        if len(buf) - head < length:
            break
        payload = buf[head:head + length]
        if masked:
            mask = buf[head - 4:head]
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        pos = head + length
        if opcode == 0x0 and frag is not None:
            opcode, previous = frag
            payload = previous + payload
            frag = None
        elif frag is not None:
            frag = None
        if not fin:
            frag = (opcode, payload)
            continue
        frames.append((opcode, payload))
    return frames, frag, buf[pos:]


def open_socket(host: str, timeout: float = 15.0) -> Tuple[ssl.SSLSocket, bytes]:
    context = ssl.create_default_context()
    raw = socket.create_connection((host, WS_PORT), timeout=timeout)
    sock = context.wrap_socket(raw, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (f"GET {WS_PATH} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\nOrigin: https://live.bilibili.com\r\n\r\n")
    sock.sendall(request.encode("ascii"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
    if "101" not in status:
        sock.close()
        raise OSError(f"升级被拒绝: {status.strip() or '无响应'}")
    return sock, rest


def _message_time(info: list) -> Optional[int]:
    """epoch 毫秒：优先 ``info[0][4]``，退回 ``info[9]["ts"]`` 秒。"""
    if isinstance(info[0], list) and len(info[0]) > 4 and isinstance(info[0][4], int):
        if info[0][4] >= PLAUSIBLE_EPOCH_MS:
            return info[0][4]
    if len(info) > 9 and isinstance(info[9], dict):
        seconds = info[9].get("ts")
        if isinstance(seconds, int) and seconds >= PLAUSIBLE_EPOCH_MS // 1000:
            return seconds * 1000
    return None


def to_danmaku(payload: dict) -> Optional[Danmaku]:
    """一条 ``DANMU_MSG`` -> Danmaku；不是观众打的字就返回 None。"""
    if payload.get("cmd") != "DANMU_MSG":
        return None
    info = payload.get("info")
    if not isinstance(info, list) or len(info) < 3:
        return None
    text = info[1] if isinstance(info[1], str) else ""
    if not text.strip():
        return None
    username = ""
    if isinstance(info[2], list) and len(info[2]) > 1 and isinstance(info[2][1], str):
        username = info[2][1]
    moment = _message_time(info)
    stamp = datetime.fromtimestamp(moment / 1000) if moment else datetime.now()
    return Danmaku(username=username or "匿名", text=text.strip(), timestamp=stamp)


class DanmakuStream:
    """迭代即持续收弹幕；``stop` 置位后自然结束。断线自己重连。"""

    def __init__(self, room_id: str, cookie: str = "", stop: Optional[threading.Event] = None,
                 on_status: Optional[callable] = None):
        self.room_id = str(room_id).strip()
        self.cookie = cookie
        self.stop = stop or threading.Event()
        self.on_status = on_status or (lambda message: None)

    def _say(self, message: str) -> None:
        self.on_status(message)

    def __iter__(self) -> Iterator[Danmaku]:
        while not self.stop.is_set():
            try:
                yield from self._session()
            except (DanmakuError, OSError, ssl.SSLError, struct.error) as e:
                self._say(f"连接中断：{type(e).__name__}: {e}")
                if not self.stop.wait(3.0):
                    continue
                return

    def _session(self) -> Iterator[Danmaku]:
        info = fetch_conn_info(self.room_id, self.cookie)
        self._say(f"已取到聊天 token（{info.origin}），正在连接…")
        buvid = buvid_from_cookie(self.cookie) if self.cookie else mint_buvid()
        auth = {"uid": 0, "roomid": int(self.room_id), "protover": 2, "platform": "web",
                "type": 2, "key": info.token}
        if buvid:
            auth["buvid"] = buvid

        last_error = ""
        for host in info.hosts:
            try:
                sock, pending = open_socket(host)
            except OSError as e:
                last_error = f"{host}: {e}"
                continue
            self._say(f"已连接 {host}（房间 {self.room_id}）")
            try:
                sock.sendall(encode_frame(build_packet(
                    json.dumps(auth, separators=(",", ":")).encode("utf-8"), OP_JOIN)))
            except OSError as e:
                sock.close()
                last_error = f"{host}: {e}"
                continue
            yield from self._read(sock, pending)
            return
        raise DanmakuError(last_error or "所有聊天服务器都连不上")

    def _read(self, sock: ssl.SSLSocket, rx: bytes) -> Iterator[Danmaku]:
        frag: Optional[Tuple[int, bytes]] = None
        beat_at = time.monotonic()
        opened_at = beat_at
        while not self.stop.is_set():
            if time.monotonic() - opened_at > RECONNECT_AFTER_SECONDS:
                sock.close()
                self._say("token 到龄，重新握手")
                return
            if time.monotonic() - beat_at >= HEARTBEAT_SECONDS:
                try:
                    sock.sendall(encode_frame(build_packet(b"", OP_HEARTBEAT)))
                except OSError:
                    pass
                beat_at = time.monotonic()
            try:
                sock.settimeout(1.0)
                chunk = sock.recv(65536)
            except (socket.timeout, TimeoutError):
                chunk = b""
            except (ssl.SSLWantReadError, BlockingIOError):
                continue
            except OSError as e:
                sock.close()
                raise OSError(f"读取失败 {type(e).__name__}") from e
            if chunk:
                rx += chunk
                frames, frag, rx = split_frames(rx, frag)
                for opcode, payload in frames:
                    if opcode == 0x9:
                        try:
                            sock.sendall(encode_frame(payload, opcode=0xA))
                        except OSError:
                            pass
                        continue
                    if opcode == 0x8:
                        sock.close()
                        self._say("服务器发来关闭帧")
                        return
                    if opcode not in (0x1, 0x2):
                        continue
                    packets, _leftover = split_packets(payload)
                    for _version, op, body in packets:
                        if op == OP_AUTH_REPLY:
                            refusal = self._refusal(body)
                            if refusal:
                                sock.close()
                                raise DanmakuError(refusal)
                        elif op == OP_MESSAGE:
                            for item in self._json_items(body):
                                message = to_danmaku(item)
                                if message is not None:
                                    yield message
                        elif op == OP_HEARTBEAT_REPLY:
                            beat_at = time.monotonic()

    @staticmethod
    def _refusal(body: bytes) -> str:
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return ""
        code = payload.get("code") if isinstance(payload, dict) else None
        return "" if code in (None, 0) else f"聊天服务器拒绝该 token（code {code}）"

    @staticmethod
    def _json_items(body: bytes) -> List[dict]:
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return []
        items = payload if isinstance(payload, list) else [payload]
        return [item for item in items if isinstance(item, dict)]
