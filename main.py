"""Orange BiliRequest —— B 站直播弹幕点歌显示器，程序入口。

    python main.py                    # 在界面里填房间号
    python main.py --room 21452505    # 直接带上房间号
    python main.py --demo             # 不联网，用假弹幕验证整条链路和界面
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Iterator, List, Optional

from bilibili.danmaku import Danmaku

THEME_TO_DARK = {"auto": None, "light": False, "dark": True}

#: 覆盖点歌与弹幕投票的演示弹幕：有效点歌、重复投票加票、投票数字、普通聊天。
DEMO_DANMAKU: List[tuple] = [
    ("風見ロク", "点歌 苏州河"),
    ("星距离422_618", "点歌 棠梨煎雪"),
    ("路人甲", "主播唱得真好"),
    ("观众A", "1"),
    ("观众B", "点一首 稻香"),
    ("观众C", "2"),
    ("观众D", "点歌 苏州河"),
    ("观众E", "点歌"),
    ("观众F", "1"),
    ("观众G", "5"),
    ("观众H", "点歌《平凡之路》"),
]


def demo_messages() -> Iterator[Danmaku]:
    for user, text in DEMO_DANMAKU:
        time.sleep(0.35)
        yield Danmaku(username=user, text=text, timestamp=datetime.now())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Orange BiliRequest —— B 站直播弹幕点歌显示器")
    parser.add_argument("--room", default="", help="直播间房间号（纯数字），留空则在界面输入")
    parser.add_argument("--theme", choices=tuple(THEME_TO_DARK), default="auto",
                        help="auto 跟随系统")
    parser.add_argument("--cookie", default=os.environ.get("BILI_COOKIE", ""),
                        help="可选：匿名取 token 失败时的备用 B 站 cookie，也可用环境变量 BILI_COOKIE")
    parser.add_argument("--demo", action="store_true", help="用假弹幕跑通链路，不联网")
    args = parser.parse_args(argv)

    from gui.app import run  # 放在这里，好让 --help 和单元测试不必加载 Qt

    return run(args.room.strip(), THEME_TO_DARK[args.theme], args.cookie.strip(),
               demo_messages if args.demo else None)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
