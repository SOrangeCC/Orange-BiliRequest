"""点歌榜状态、弹幕投票逻辑与 OBS HTTP 服务的离线单元测试（纯标准库）。"""

from __future__ import annotations

import json
import unittest
import urllib.request
from datetime import datetime

from bilibili.danmaku import Danmaku
from core.state import BoardState, match_vote_trigger
from obs.server import ObsOverlayServer
from parser.song_parser import SongRequest


class SongBoardTests(unittest.TestCase):
    def test_aggregates_votes_deduplicates_user_and_ranks(self) -> None:
        state = BoardState()
        t = datetime(2026, 11, 19, 12, 0, 0)
        self.assertTrue(state.add_song_request(SongRequest("用户A", "苏州河", t, "点歌 苏州河")))
        self.assertTrue(state.add_song_request(SongRequest("用户B", "棠梨煎雪", t, "点歌 棠梨煎雪")))
        # 同一用户重复点同一首歌不重复加票
        self.assertFalse(state.add_song_request(SongRequest("用户A", "苏州河", t, "点歌 苏州河")))
        # 另一位用户点同一首歌：票数 +1，并排在第一
        self.assertTrue(state.add_song_request(SongRequest("用户C", "棠梨煎雪", t, "点歌 棠梨煎雪")))

        snap = state.snapshot()["songs"]
        self.assertEqual(snap["count"], 2)
        self.assertEqual(snap["participants"], 3)
        self.assertEqual(snap["items"][0]["song"], "棠梨煎雪")
        self.assertEqual(snap["items"][0]["votes"], 2)
        self.assertEqual(snap["items"][0]["rank"], 1)
        self.assertEqual(snap["items"][1]["song"], "苏州河")
        self.assertEqual(snap["items"][1]["votes"], 1)

    def test_remove_and_clear_songs(self) -> None:
        state = BoardState()
        t = datetime.now()
        state.add_song_request(SongRequest("用户A", "晴天", t, "点歌 晴天"))
        state.add_song_request(SongRequest("用户B", "稻香", t, "点歌 稻香"))
        key = state.snapshot()["songs"]["items"][0]["key"]
        self.assertTrue(state.remove_song(key))
        self.assertEqual(state.snapshot()["songs"]["count"], 1)
        state.clear_songs()
        self.assertEqual(state.snapshot()["songs"]["count"], 0)
        self.assertEqual(state.snapshot()["songs"]["participants"], 0)

    def test_round_timer_defaults_off_and_toggles(self) -> None:
        state = BoardState()
        self.assertFalse(state.snapshot()["songs"]["round_timer_enabled"])
        state.set_round_timer_enabled(True)
        self.assertTrue(state.snapshot()["songs"]["round_timer_enabled"])
        state.set_round_timer_enabled(False)
        self.assertFalse(state.snapshot()["songs"]["round_timer_enabled"])


class VoteTests(unittest.TestCase):
    def test_trigger_matching_avoids_partial_numbers(self) -> None:
        triggers = ["1", "2", "3", "4", "5"]
        self.assertEqual(match_vote_trigger("1", triggers), 0)
        self.assertEqual(match_vote_trigger("投2", triggers), 1)
        self.assertEqual(match_vote_trigger("选 3", triggers), 2)
        self.assertEqual(match_vote_trigger("投票5", triggers), 4)
        self.assertIsNone(match_vote_trigger("100", triggers))
        self.assertIsNone(match_vote_trigger("12", triggers))
        self.assertIsNone(match_vote_trigger("6", triggers))

    def test_five_plus_options_and_single_vote_per_user(self) -> None:
        state = BoardState()
        state.configure_vote(
            "下一把玩什么？",
            [
                ("1", "支持1选项"),
                ("2", "支持2选项"),
                ("3", "支持3选项"),
                ("4", "支持4选项"),
                ("5", "支持5选项"),
                ("6", "支持6选项"),
            ],
            single_vote_per_user=True,
        )
        # 未开始投票时不计票
        self.assertIsNone(state.process_vote_danmaku(Danmaku("观众1", "1", datetime.now())))

        state.set_vote_active(True)
        self.assertEqual(state.process_vote_danmaku(Danmaku("观众1", "1", datetime.now())), 0)
        # 同一人再次投别的选项被忽略
        self.assertIsNone(state.process_vote_danmaku(Danmaku("观众1", "2", datetime.now())))
        self.assertEqual(state.process_vote_danmaku(Danmaku("观众2", "5", datetime.now())), 4)
        self.assertEqual(state.process_vote_danmaku(Danmaku("观众3", "1", datetime.now())), 0)
        self.assertEqual(state.process_vote_danmaku(Danmaku("观众4", "6", datetime.now())), 5)

        vote = state.snapshot()["vote"]
        self.assertEqual(len(vote["options"]), 6)
        self.assertEqual(vote["total_votes"], 4)
        self.assertEqual(vote["participants"], 4)
        self.assertEqual(vote["options"][0]["votes"], 2)
        self.assertEqual(vote["options"][0]["percent"], 50.0)
        self.assertTrue(vote["options"][0]["is_leading"])
        self.assertEqual(vote["options"][4]["votes"], 1)
        self.assertEqual(vote["options"][5]["votes"], 1)

        state.reset_votes()
        self.assertEqual(state.snapshot()["vote"]["total_votes"], 0)


class ObsServerTests(unittest.TestCase):
    def test_serves_overlay_html_and_live_json_state(self) -> None:
        state = BoardState()
        state.add_song_request(SongRequest("風見ロク", "苏州河", datetime.now(), "点歌 苏州河"))
        server = ObsOverlayServer(state, host="127.0.0.1", port=0)
        # port=0 让系统自动分配空闲端口
        server.preferred_port = 0
        port = server.start()
        try:
            self.assertGreater(port, 0)
            with urllib.request.urlopen(f"{server.base_url}/overlay", timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                html = resp.read().decode("utf-8")
                self.assertIn("弹幕点歌", html)
                self.assertIn("弹幕投票", html)

            with urllib.request.urlopen(f"{server.base_url}/api/state", timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["songs"]["count"], 1)
                self.assertEqual(data["songs"]["items"][0]["song"], "苏州河")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
