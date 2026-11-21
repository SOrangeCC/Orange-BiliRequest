"""内置 OBS 浏览器源本地 HTTP 服务（纯标准库，透明背景、实时刷新）。"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from core.state import BoardState

DEFAULT_OBS_PORT = 18080
MAX_PORT_TRIES = 20

OVERLAY_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Orange BiliRequest - OBS 展示板</title>
<style>
  :root {
    --card-bg: linear-gradient(145deg, rgba(226, 240, 255, 0.88) 0%, rgba(206, 228, 252, 0.84) 100%);
    --card-border: rgba(255, 255, 255, 0.78);
    --card-shadow: 0 14px 36px rgba(42, 88, 152, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.75);
    --title-blue: #4B70A6;
    --song-blue: #3D6296;
    --text-muted: #76899E;
    --text-dark: #4C5E73;
    --gold: #F5B82E;
    --gold-deep: #E59E1B;
    --badge-gold-bg: linear-gradient(135deg, #FFE074 0%, #F7C232 100%);
    --badge-normal-bg: rgba(255, 255, 255, 0.62);
    --pill-bg: rgba(255, 255, 255, 0.48);
    --bar-track: rgba(255, 255, 255, 0.55);
    --bar-fill: linear-gradient(90deg, rgba(126, 178, 245, 0.75) 0%, rgba(92, 152, 235, 0.88) 100%);
    --bar-fill-lead: linear-gradient(90deg, rgba(255, 214, 102, 0.85) 0%, rgba(247, 186, 50, 0.92) 100%);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  html, body {
    background: transparent;
    font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif;
    color: var(--text-dark);
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }

  .stage {
    padding: 16px;
    display: flex;
    gap: 16px;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .board-card {
    position: relative;
    width: 400px;
    max-width: 100%;
    background: var(--card-bg);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1.5px solid var(--card-border);
    border-radius: 22px;
    box-shadow: var(--card-shadow);
    padding: 20px 22px 20px;
    overflow: hidden;
    transition: opacity 0.25s ease, transform 0.25s ease;
  }

  .board-card.hidden {
    display: none;
  }

  /* 装饰性半透明气泡与水印 */
  .deco-circle-1 {
    position: absolute;
    width: 130px;
    height: 130px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.35) 0%, rgba(255, 255, 255, 0) 72%);
    top: 34px;
    left: 52%;
    pointer-events: none;
  }

  .deco-circle-2 {
    position: absolute;
    width: 170px;
    height: 170px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.26) 0%, rgba(255, 255, 255, 0) 72%);
    bottom: -55px;
    right: -35px;
    pointer-events: none;
  }

  .deco-play {
    position: absolute;
    top: -16px;
    left: 44px;
    width: 72px;
    height: 72px;
    opacity: 0.22;
    pointer-events: none;
  }

  .header-row {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }

  .board-title {
    font-size: 20px;
    font-weight: 700;
    color: var(--title-blue);
    letter-spacing: 0.4px;
  }

  .status-pill {
    padding: 4px 13px;
    border-radius: 999px;
    background: var(--pill-bg);
    border: 1px solid rgba(255, 255, 255, 0.72);
    font-size: 13px;
    font-weight: 700;
    color: var(--gold-deep);
  }

  .status-pill.paused {
    color: var(--text-muted);
  }

  .meta-row {
    position: relative;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 6px;
  }

  .timer-text {
    font-size: 21px;
    font-weight: 800;
    color: var(--gold);
    font-variant-numeric: tabular-nums;
    text-shadow: 0 1px 2px rgba(255, 255, 255, 0.6);
  }

  .participants-text {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-dark);
  }

  .rule-line {
    position: relative;
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 14px;
    line-height: 1.4;
  }

  /* 点歌列表 */
  .song-list {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .song-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 7px 6px;
    border-radius: 14px;
    transition: background 0.2s ease;
    animation: fadeSlideIn 0.28s ease;
  }

  .song-item:hover {
    background: rgba(255, 255, 255, 0.28);
  }

  .rank-badge {
    flex: 0 0 30px;
    height: 30px;
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 800;
    background: var(--badge-normal-bg);
    color: var(--text-dark);
    box-shadow: 0 2px 6px rgba(60, 90, 140, 0.08);
  }

  .rank-badge.rank-1 {
    background: var(--badge-gold-bg);
    color: #2B261C;
  }

  .song-info {
    flex: 1;
    min-width: 0;
  }

  .song-name {
    font-size: 17px;
    font-weight: 700;
    color: var(--song-blue);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .song-user {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .vote-count {
    flex: 0 0 auto;
    font-size: 15px;
    font-weight: 800;
    color: var(--gold-deep);
    font-variant-numeric: tabular-nums;
  }

  /* 投票列表 */
  .vote-question {
    position: relative;
    font-size: 17px;
    font-weight: 700;
    color: var(--song-blue);
    margin-bottom: 6px;
    line-height: 1.35;
  }

  .vote-list {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 9px;
  }

  .vote-option {
    position: relative;
    border-radius: 13px;
    background: var(--bar-track);
    border: 1px solid rgba(255, 255, 255, 0.65);
    overflow: hidden;
    padding: 9px 12px;
  }

  .vote-bar-fill {
    position: absolute;
    inset: 0 auto 0 0;
    width: 0%;
    background: var(--bar-fill);
    transition: width 0.4s cubic-bezier(0.22, 1, 0.36, 1);
    pointer-events: none;
  }

  .vote-option.leading .vote-bar-fill {
    background: var(--bar-fill-lead);
  }

  .vote-option-inner {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .trigger-badge {
    flex: 0 0 auto;
    min-width: 28px;
    height: 26px;
    padding: 0 8px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.85);
    color: var(--song-blue);
    font-size: 13px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 1px 4px rgba(50, 80, 130, 0.08);
  }

  .vote-option.leading .trigger-badge {
    background: var(--badge-gold-bg);
    color: #2B261C;
  }

  .vote-label {
    flex: 1;
    min-width: 0;
    font-size: 15px;
    font-weight: 700;
    color: #2E4A73;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .vote-stats {
    flex: 0 0 auto;
    text-align: right;
    font-size: 13px;
    font-weight: 700;
    color: #3B5578;
    font-variant-numeric: tabular-nums;
  }

  .vote-stats .pct {
    font-size: 12px;
    color: var(--text-muted);
    margin-left: 4px;
  }

  .empty-hint {
    position: relative;
    text-align: center;
    padding: 18px 10px;
    font-size: 13px;
    color: var(--text-muted);
  }

  @keyframes fadeSlideIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
</head>
<body>
<div class="stage">
  <!-- 点歌板 -->
  <section id="songCard" class="board-card">
    <div class="deco-circle-1"></div>
    <div class="deco-circle-2"></div>
    <svg class="deco-play" viewBox="0 0 64 64" fill="none">
      <path d="M18 14L50 32L18 50V14Z" stroke="white" stroke-width="5" stroke-linejoin="round"/>
    </svg>
    <div class="header-row">
      <div class="board-title">弹幕点歌</div>
      <div id="songStatusPill" class="status-pill">征集中</div>
    </div>
    <div class="meta-row">
      <div id="songTimer" class="timer-text">实时榜</div>
      <div id="songParticipants" class="participants-text">0 人参与</div>
    </div>
    <div id="songRuleLine" class="rule-line">发送「点歌 歌名」即可点歌 · 每人限投 1 票</div>
    <div id="songList" class="song-list"></div>
  </section>

  <!-- 弹幕投票板 -->
  <section id="voteCard" class="board-card hidden">
    <div class="deco-circle-1"></div>
    <div class="deco-circle-2"></div>
    <div class="header-row">
      <div class="board-title">弹幕投票</div>
      <div id="voteStatusPill" class="status-pill">未开始</div>
    </div>
    <div id="voteQuestion" class="vote-question">弹幕投票</div>
    <div id="voteMeta" class="rule-line">发送对应指令参与投票 · 0 人参与 · 共 0 票</div>
    <div id="voteList" class="vote-list"></div>
  </section>
</div>

<script>
  const params = new URLSearchParams(window.location.search);
  const urlMode = params.get("mode") || "auto";
  const MAX_SONGS_SHOWN = 8;
  let lastVersion = -1;

  function fmtTime(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
  }

  function esc(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function render(data) {
    const mode = urlMode === "auto" ? data.effective_mode : urlMode;
    const songCard = document.getElementById("songCard");
    const voteCard = document.getElementById("voteCard");

    songCard.classList.toggle("hidden", mode !== "songs" && mode !== "both");
    voteCard.classList.toggle("hidden", mode !== "vote" && mode !== "both");

    // 渲染点歌板
    const songs = data.songs || {};
    const songPill = document.getElementById("songStatusPill");
    songPill.textContent = data.listening ? "征集中" : "待机中";
    songPill.classList.toggle("paused", !data.listening);

    const timerEnabled = Boolean(songs.round_timer_enabled);
    document.getElementById("songTimer").textContent = timerEnabled
      ? fmtTime(songs.remaining_seconds)
      : `共 ${songs.count || 0} 首`;
    document.getElementById("songRuleLine").textContent = timerEnabled
      ? "发送「点歌 歌名」即可点歌 · 60 分钟一榜 · 每人限投 1 票"
      : "发送「点歌 歌名」即可点歌 · 每人限投 1 票";
    document.getElementById("songParticipants").textContent = (songs.participants || 0) + " 人参与";

    const items = (songs.items || []).slice(0, MAX_SONGS_SHOWN);
    const songListEl = document.getElementById("songList");
    if (items.length === 0) {
      songListEl.innerHTML = '<div class="empty-hint">暂无点歌，发「点歌 歌名」即可上榜~</div>';
    } else {
      songListEl.innerHTML = items.map(item => `
        <div class="song-item">
          <div class="rank-badge ${item.rank === 1 ? "rank-1" : ""}">${item.rank}</div>
          <div class="song-info">
            <div class="song-name">${esc(item.song)}</div>
            <div class="song-user">${esc(item.requester)}</div>
          </div>
          <div class="vote-count">${item.votes} 票</div>
        </div>
      `).join("");
    }

    // 渲染投票板
    const vote = data.vote || {};
    const votePill = document.getElementById("voteStatusPill");
    votePill.textContent = vote.active ? "投票中" : "已结束";
    votePill.classList.toggle("paused", !vote.active);

    document.getElementById("voteQuestion").textContent = vote.question || "弹幕投票";
    const ruleText = vote.single_vote_per_user ? "每人限投 1 票" : "可多次投票";
    document.getElementById("voteMeta").textContent =
      `${ruleText} · ${vote.participants || 0} 人参与 · 共 ${vote.total_votes || 0} 票`;

    const opts = vote.options || [];
    const voteListEl = document.getElementById("voteList");
    if (opts.length === 0) {
      voteListEl.innerHTML = '<div class="empty-hint">主播暂未设置投票选项</div>';
    } else {
      voteListEl.innerHTML = opts.map(opt => `
        <div class="vote-option ${opt.is_leading ? "leading" : ""}">
          <div class="vote-bar-fill" style="width: ${opt.percent}%"></div>
          <div class="vote-option-inner">
            <div class="trigger-badge">${esc(opt.trigger)}</div>
            <div class="vote-label">${esc(opt.label)}</div>
            <div class="vote-stats">${opt.votes} 票<span class="pct">${opt.percent}%</span></div>
          </div>
        </div>
      `).join("");
    }
  }

  async function poll() {
    try {
      const resp = await fetch("/api/state", { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        if (data.version !== lastVersion) {
          lastVersion = data.version;
          render(data);
        } else if (data.songs && data.songs.round_timer_enabled) {
          // 即使 version 没变，开启倒计时时每秒也更新一次显示
          document.getElementById("songTimer").textContent = fmtTime(data.songs.remaining_seconds);
        }
      }
    } catch (_) {
      // 本地服务重启或暂不可用时静默重试
    }
  }

  poll();
  setInterval(poll, 500);
</script>
</body>
</html>
"""


def _make_handler(state: BoardState):
    class OverlayHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - 屏蔽控制台刷屏日志
            return

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/overlay"):
                body = OVERLAY_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/state":
                payload = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    return OverlayHandler


class ObsOverlayServer:
    """管理 OBS 展示板的本地 HTTP 服务。"""

    def __init__(self, state: BoardState, host: str = "127.0.0.1", port: int = DEFAULT_OBS_PORT):
        self.state = state
        self.host = host
        self.preferred_port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port: int = port

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def overlay_url(self, mode: str = "auto") -> str:
        if mode == "auto":
            return f"{self.base_url}/overlay"
        return f"{self.base_url}/overlay?mode={urllib.parse.quote(mode)}"

    def start(self) -> int:
        if self._server is not None:
            return self.port
        handler = _make_handler(self.state)
        last_err: Optional[OSError] = None
        for offset in range(MAX_PORT_TRIES):
            candidate = self.preferred_port + offset
            try:
                self._server = ThreadingHTTPServer((self.host, candidate), handler)
                self.port = self._server.server_address[1]
                break
            except OSError as exc:
                last_err = exc
        if self._server is None:
            raise last_err or OSError("无法启动 OBS 本地展示服务")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="obs-overlay-http",
            daemon=True,
        )
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
