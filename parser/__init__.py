"""点歌指令解析。"""

from .song_parser import PREFIXES, SongRequest, extract_song, parse

__all__ = ["PREFIXES", "SongRequest", "extract_song", "parse"]
