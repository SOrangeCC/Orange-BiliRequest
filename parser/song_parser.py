"""把一条弹幕变成一次点歌。

只认“开头就是点歌指令”的弹幕，剩下的是歌名。这样能顺手挡掉两类噪声：
「能不能点歌」「点歌吗」这类不含歌名的问句（歌名不足 2 字），以及正文中间偶然出现
“点歌”二字的普通聊天（指令必须在开头）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

#: 长的在前，这样「点一首歌 晴天」不会被「点一首」先吃掉一个“歌”字。
PREFIXES: Tuple[str, ...] = ("点一首歌", "点一首", "点歌")

#: 指令和歌名之间的分隔符，一律忽略。
SEPARATORS = " \t:：,，、。.~～!！?？-—_<>《》「」“”\"'()（）[]【】"

MIN_SONG_LENGTH = 2
#: 弹幕最长 60 字，整条当歌名会把卡片撑成一堵墙；截断只影响显示。
MAX_SONG_LENGTH = 40


@dataclass(frozen=True)
class SongRequest:
    user: str
    song: str
    timestamp: datetime
    raw: str


def extract_song(text: str) -> Optional[str]:
    """命中标题就返回歌名，否则返回 None。"""
    body = str(text or "").strip()
    for prefix in PREFIXES:
        if not body.startswith(prefix):
            continue
        song = body[len(prefix):].strip(SEPARATORS).strip()
        if len(song) < MIN_SONG_LENGTH:
            return None
        return song[:MAX_SONG_LENGTH]
    return None


def parse(danmaku) -> Optional[SongRequest]:
    """danmaku 需要 ``text`` / ``username`` / ``timestamp`` 三个字段。"""
    song = extract_song(getattr(danmaku, "text", None) if hasattr(danmaku, "text") else danmaku)
    if song is None:
        return None
    return SongRequest(
        user=str(getattr(danmaku, "username", "") or "匿名"),
        song=song,
        timestamp=getattr(danmaku, "timestamp", None) or datetime.now(),
        raw=str(getattr(danmaku, "text", song)),
    )
