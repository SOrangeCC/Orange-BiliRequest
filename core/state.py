"""点歌榜与弹幕投票的线程安全状态管理（纯标准库，无 Qt 依赖）。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from parser.song_parser import SongRequest

DEFAULT_ROUND_SECONDS = 3600  # 60 分钟一榜
MAX_SONG_BOARD_ITEMS = 100
VOTE_COMMAND_PREFIXES: Tuple[str, ...] = ("投票", "投", "选")


def _normalize_song_key(song: str) -> str:
    return " ".join(song.strip().lower().split())


@dataclass
class SongEntry:
    """点歌榜上的一首歌（按歌名聚合票数）。"""

    key: str
    song: str
    requester: str
    timestamp: datetime
    voters: Set[str] = field(default_factory=set)
    first_seq: int = 0

    @property
    def votes(self) -> int:
        return len(self.voters)


@dataclass
class VoteOption:
    """弹幕投票的一个选项。"""

    trigger: str
    label: str
    voters: Set[str] = field(default_factory=set)

    @property
    def votes(self) -> int:
        return len(self.voters)


def match_vote_trigger(text: str, triggers: List[str]) -> Optional[int]:
    """判断弹幕文本是否命中某个投票选项，返回命中的选项索引，未命中返回 None。"""
    body = str(text or "").strip()
    if not body:
        return None
    lowered = body.lower()

    # 1) 精确匹配弹幕输入关键词
    for idx, trigger in enumerate(triggers):
        t = trigger.strip().lower()
        if t and lowered == t:
            return idx

    # 2) 兼容「投1」「选 2」「投票A」等常见前缀写法
    for prefix in VOTE_COMMAND_PREFIXES:
        if lowered.startswith(prefix):
            rest = lowered[len(prefix):].strip(" \t:：")
            if not rest:
                continue
            for idx, trigger in enumerate(triggers):
                t = trigger.strip().lower()
                if t and rest == t:
                    return idx
    return None


class BoardState:
    """统一管理点歌榜、弹幕投票和 OBS 展示模式的线程安全状态容器。"""

    def __init__(self, round_seconds: int = DEFAULT_ROUND_SECONDS):
        self._lock = threading.Lock()
        self._version = 1
        self._seq = 0
        self._round_seconds = max(60, int(round_seconds))
        self._round_started_at = time.monotonic()

        # 点歌状态
        self._songs: Dict[str, SongEntry] = {}
        self._song_participants: Set[str] = set()
        self._listening: bool = False
        self.round_timer_enabled: bool = False

        # 投票状态
        self.vote_question: str = "接下来想听什么类型的歌？"
        self.vote_options: List[VoteOption] = [
            VoteOption("1", "支持1选项"),
            VoteOption("2", "支持2选项"),
            VoteOption("3", "支持3选项"),
            VoteOption("4", "支持4选项"),
            VoteOption("5", "支持5选项"),
        ]
        self.vote_active: bool = False
        self.single_vote_per_user: bool = True
        self._voted_users: Set[str] = set()

        # OBS 展示模式: "auto" | "songs" | "vote" | "both"
        self._obs_mode: str = "auto"
        self._active_tab: str = "songs"

    def _bump(self) -> None:
        self._version += 1

    # --- 监听与模式 ----------------------------------------------------------

    def set_listening(self, listening: bool) -> None:
        with self._lock:
            if self._listening != listening:
                self._listening = listening
                if listening and not self._songs:
                    self._round_started_at = time.monotonic()
                self._bump()

    def set_round_timer_enabled(self, enabled: bool) -> None:
        with self._lock:
            flag = bool(enabled)
            if self.round_timer_enabled != flag:
                self.round_timer_enabled = flag
                if flag:
                    self._round_started_at = time.monotonic()
                self._bump()

    def set_obs_mode(self, mode: str) -> None:
        if mode not in ("auto", "songs", "vote", "both"):
            return
        with self._lock:
            if self._obs_mode != mode:
                self._obs_mode = mode
                self._bump()

    def set_active_tab(self, tab: str) -> None:
        if tab not in ("songs", "vote"):
            return
        with self._lock:
            if self._active_tab != tab:
                self._active_tab = tab
                self._bump()

    # --- 点歌榜操作 ----------------------------------------------------------

    def add_song_request(self, request: SongRequest) -> bool:
        """记录一条点歌。如果是新歌或新投票人返回 True，重复同一人点同一首返回 False。"""
        key = _normalize_song_key(request.song)
        if not key:
            return False
        user = request.user or "匿名"
        with self._lock:
            self._song_participants.add(user)
            entry = self._songs.get(key)
            if entry is None:
                self._seq += 1
                entry = SongEntry(
                    key=key,
                    song=request.song,
                    requester=user,
                    timestamp=request.timestamp,
                    voters={user},
                    first_seq=self._seq,
                )
                self._songs[key] = entry
                self._trim_songs_locked()
                self._bump()
                return True
            if user in entry.voters:
                return False
            entry.voters.add(user)
            self._bump()
            return True

    def _trim_songs_locked(self) -> None:
        if len(self._songs) <= MAX_SONG_BOARD_ITEMS:
            return
        ordered = self._ordered_songs_locked()
        for stale in ordered[MAX_SONG_BOARD_ITEMS:]:
            self._songs.pop(stale.key, None)

    def _ordered_songs_locked(self) -> List[SongEntry]:
        return sorted(
            self._songs.values(),
            key=lambda e: (-e.votes, e.first_seq),
        )

    def remove_song(self, song_key: str) -> bool:
        with self._lock:
            if song_key in self._songs:
                self._songs.pop(song_key)
                self._bump()
                return True
            return False

    def clear_songs(self) -> None:
        with self._lock:
            self._songs.clear()
            self._song_participants.clear()
            self._round_started_at = time.monotonic()
            self._bump()

    # --- 弹幕投票操作 --------------------------------------------------------

    def configure_vote(
        self,
        question: str,
        options: List[Tuple[str, str]],
        single_vote_per_user: bool = True,
    ) -> None:
        """设置投票问题与选项列表 [(trigger, label), ...]。"""
        cleaned: List[VoteOption] = []
        for idx, (trigger, label) in enumerate(options, start=1):
            t = str(trigger or "").strip() or str(idx)
            lbl = str(label or "").strip() or f"选项{idx}"
            cleaned.append(VoteOption(trigger=t, label=lbl))
        with self._lock:
            self.vote_question = str(question or "").strip() or "弹幕投票"
            self.vote_options = cleaned
            self.single_vote_per_user = bool(single_vote_per_user)
            self._voted_users.clear()
            self._bump()

    def set_vote_active(self, active: bool) -> None:
        with self._lock:
            if self.vote_active != active:
                self.vote_active = active
                self._bump()

    def reset_votes(self) -> None:
        with self._lock:
            for opt in self.vote_options:
                opt.voters.clear()
            self._voted_users.clear()
            self._bump()

    def process_vote_danmaku(self, danmaku) -> Optional[int]:
        """尝试将弹幕计入当前投票。成功计票返回选项索引，否则返回 None。"""
        text = getattr(danmaku, "text", None) if hasattr(danmaku, "text") else danmaku
        user = str(getattr(danmaku, "username", "") or "匿名")
        with self._lock:
            if not self.vote_active or not self.vote_options:
                return None
            if self.single_vote_per_user and user in self._voted_users:
                return None
            triggers = [opt.trigger for opt in self.vote_options]
            idx = match_vote_trigger(str(text or ""), triggers)
            if idx is None:
                return None
            option = self.vote_options[idx]
            if user in option.voters:
                return None
            option.voters.add(user)
            self._voted_users.add(user)
            self._bump()
            return idx

    # --- 快照输出（给 GUI 与 OBS API 使用） -----------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = max(0.0, time.monotonic() - self._round_started_at)
            remaining = max(0, int(self._round_seconds - elapsed))
            ordered_songs = self._ordered_songs_locked()
            song_list = [
                {
                    "rank": i,
                    "key": entry.key,
                    "song": entry.song,
                    "requester": entry.requester,
                    "votes": entry.votes,
                    "time": entry.timestamp.strftime("%H:%M:%S"),
                }
                for i, entry in enumerate(ordered_songs, start=1)
            ]

            total_votes = sum(opt.votes for opt in self.vote_options)
            max_votes = max((opt.votes for opt in self.vote_options), default=0)
            vote_list = []
            for i, opt in enumerate(self.vote_options, start=1):
                pct = round((opt.votes / total_votes) * 100, 1) if total_votes > 0 else 0.0
                vote_list.append({
                    "index": i,
                    "trigger": opt.trigger,
                    "label": opt.label,
                    "votes": opt.votes,
                    "percent": pct,
                    "is_leading": max_votes > 0 and opt.votes == max_votes,
                })

            effective_mode = (
                self._active_tab if self._obs_mode == "auto" else self._obs_mode
            )

            return {
                "version": self._version,
                "listening": self._listening,
                "obs_mode": self._obs_mode,
                "effective_mode": effective_mode,
                "songs": {
                    "items": song_list,
                    "count": len(song_list),
                    "participants": len(self._song_participants),
                    "round_timer_enabled": self.round_timer_enabled,
                    "remaining_seconds": remaining,
                },
                "vote": {
                    "active": self.vote_active,
                    "question": self.vote_question,
                    "single_vote_per_user": self.single_vote_per_user,
                    "total_votes": total_votes,
                    "participants": len(self._voted_users),
                    "options": vote_list,
                },
            }
