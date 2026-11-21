"""解析规则的离线用例，不需要网络。"""

import unittest
from datetime import datetime

from parser.song_parser import MAX_SONG_LENGTH, SongRequest, extract_song, parse


class ExtractSongTests(unittest.TestCase):
    def test_supported_forms(self):
        cases = [
            ("点歌 起风了", "起风了"),
            ("点歌: Lemon", "Lemon"),
            ("点歌：Lemon", "Lemon"),
            ("点一首 起风了", "起风了"),
            ("点歌起风了", "起风了"),
            ("点歌  《起风了》 ", "起风了"),
            ("点一首歌 晴天", "晴天"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_song(text), expected)

    def test_invalid_requests_are_dropped(self):
        for text in ("点歌", "点歌 ", "点歌:", "点一首", "点歌 你", "点歌 好",
                     "我想点歌 起风了", "有人点歌吗", "", "   ", "求点歌 起风了"):
            with self.subTest(text=text):
                self.assertIsNone(extract_song(text))

    def test_song_is_capped(self):
        self.assertEqual(extract_song("点歌 " + "歌" * 60), "歌" * MAX_SONG_LENGTH)

    def test_case_is_kept_but_music_word_is_required(self):
        self.assertEqual(extract_song("点歌 Lemon Tree"), "Lemon Tree")


class ParseDanmakuTests(unittest.TestCase):
    def test_builds_a_request_from_a_danmaku(self):
        stamp = datetime(2026, 10, 10, 21, 30, 5)

        class Message:
            username = "用户A"
            text = "点歌 Lemon"
            timestamp = stamp

        request = parse(Message())
        self.assertIsInstance(request, SongRequest)
        self.assertEqual((request.user, request.song, request.timestamp),
                         ("用户A", "Lemon", stamp))

    def test_plain_chat_returns_none(self):
        class Message:
            username = "用户B"
            text = "主播好"
            timestamp = datetime(2026, 10, 10, 21, 0, 0)

        self.assertIsNone(parse(Message()))


if __name__ == "__main__":
    unittest.main()
