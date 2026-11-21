"""Material 3 风格的 B 站直播点歌 & 弹幕投票后台窗口，附带 OBS 浏览器源展示。"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bilibili.danmaku import DanmakuStream
from core.state import BoardState
from obs.server import ObsOverlayServer
from parser.song_parser import SongRequest, parse

FONT_FAMILY = '"PingFang SC", "Microsoft YaHei UI", "Segoe UI Variable", "Segoe UI", sans-serif'
MAX_VOTE_OPTIONS = 10
MIN_VOTE_OPTIONS = 2


def resource(name: str) -> Path:
    """资源位置：源码运行时在项目根的 assets/，打成 exe 后在 PyInstaller 解出来的 _MEIPASS。"""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "assets" / name


@dataclass(frozen=True)
class Scheme:
    """Material 3 的一整套颜色令牌。"""

    name: str
    window: str
    app_bar: str
    card: str
    card_border: str
    field: str
    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str
    on_surface: str
    on_surface_variant: str
    outline: str
    state: str

    def qss(self) -> str:
        return f"""
QWidget {{ color: {self.on_surface}; font-family: {FONT_FAMILY}; font-size: 14px; }}
#root {{ background: {self.window}; }}
QLabel {{ background: transparent; }}
QCheckBox {{ background: transparent; spacing: 8px; color: {self.on_surface}; }}
#appBar, #obsBar, #sectionCard {{
    background: {self.app_bar};
    border: 1px solid {self.card_border};
    border-radius: 20px;
}}
#appIcon {{ font-size: 26px; }}
#appTitle {{ font-size: 20px; font-weight: 700; color: {self.on_surface}; }}
#appSubtitle {{ font-size: 13px; color: {self.on_surface_variant}; }}
#roomIdField, #inputField {{
    background: {self.field};
    color: {self.on_surface};
    border: 1px solid {self.outline};
    border-radius: 16px;
    padding: 8px 14px;
    font-size: 14px;
}}
#roomIdField:focus, #inputField:focus {{ border: 2px solid {self.primary}; }}
#comboBox {{
    background: {self.field};
    color: {self.on_surface};
    border: 1px solid {self.outline};
    border-radius: 14px;
    padding: 6px 28px 6px 12px;
    font-size: 13px;
}}
#comboBox:hover {{ border: 1px solid {self.primary}; }}
#comboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border: none;
    background: transparent;
}}
#comboBox::down-arrow {{
    image: url("{resource("chevron_down.svg").as_posix()}");
    width: 12px;
    height: 12px;
}}
#comboBox QAbstractItemView {{
    background: {self.card};
    color: {self.on_surface};
    border: 1px solid {self.card_border};
    border-radius: 12px;
    padding: 4px;
    selection-background-color: {self.primary_container};
    selection-color: {self.on_primary_container};
    outline: none;
}}
#filledButton {{
    background: {self.primary};
    color: {self.on_primary};
    border: none;
    border-radius: 18px;
    padding: 9px 20px;
    font-weight: 600;
}}
#filledButton:disabled {{ background: {self.card_border}; color: {self.outline}; }}
#tonalButton {{
    background: {self.primary_container};
    color: {self.on_primary_container};
    border: none;
    border-radius: 16px;
    padding: 8px 16px;
    font-weight: 600;
}}
#textButton {{
    background: transparent;
    color: {self.primary};
    border: 1px solid {self.outline};
    border-radius: 16px;
    padding: 8px 14px;
}}
#smallButton {{
    background: {self.primary_container};
    color: {self.on_primary_container};
    border: none;
    border-radius: 12px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}}
#tabButton {{
    background: {self.card};
    color: {self.on_surface_variant};
    border: 1px solid {self.card_border};
    border-radius: 16px;
    padding: 9px 18px;
    font-weight: 600;
}}
#tabButton[active="true"] {{
    background: {self.primary};
    color: {self.on_primary};
    border: 1px solid {self.primary};
}}
#listHeading {{ font-size: 15px; font-weight: 700; color: {self.on_surface}; }}
#songCard, #voteRowCard {{
    background: {self.card};
    border: 1px solid {self.card_border};
    border-radius: 16px;
}}
#songName {{ font-size: 16px; font-weight: 700; color: {self.on_surface}; }}
#songMeta {{ font-size: 12px; color: {self.on_surface_variant}; }}
#songIndex {{
    font-size: 12px;
    font-weight: 700;
    color: {self.on_primary_container};
    background: {self.primary_container};
    border-radius: 10px;
    padding: 3px 9px;
}}
#voteBadge {{
    font-size: 12px;
    font-weight: 700;
    color: {self.on_primary};
    background: {self.primary};
    border-radius: 10px;
    padding: 3px 9px;
}}
#hintCard {{
    background: {self.card};
    border: 1px dashed {self.outline};
    border-radius: 16px;
}}
#hintText {{ font-size: 13px; color: {self.on_surface_variant}; }}
#statusLabel {{ font-size: 12px; color: {self.on_surface_variant}; }}
#stateDot {{ color: {self.state}; font-size: 13px; }}
QProgressBar {{
    background: {self.card_border};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {self.primary};
    border-radius: 5px;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {self.outline}; border-radius: 5px; min-height: 32px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


LIGHT = Scheme(
    "浅色", "#F7F4FA", "#FEF7FF", "#FEF7FF", "#E7E0EC", "#FFF8F6",
    "#6750A4", "#FFFFFF", "#EADDFF", "#21005D", "#1D1B20", "#49454F",
    "#79747E", "#2E7D32",
)
DARK = Scheme(
    "深色", "#141218", "#211F26", "#211F26", "#34323A", "#2B2930",
    "#D0BCFF", "#381E72", "#4F378B", "#EADDFF", "#E6E1E5", "#CAC4D0",
    "#938F99", "#81C784",
)


class SongCard(QFrame):
    """点歌榜卡片：排名、歌名、点歌人、票数与「已唱」移除按钮。"""

    def __init__(self, item: dict, on_remove, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("songCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        badge = QLabel(str(item["rank"]))
        badge.setObjectName("songIndex")
        name = QLabel(f"🎵 {item['song']}")
        name.setObjectName("songName")
        name.setWordWrap(True)
        votes = QLabel(f"{item['votes']} 票")
        votes.setObjectName("voteBadge")
        done_btn = QPushButton("✓ 已唱")
        done_btn.setObjectName("smallButton")
        done_btn.setCursor(Qt.PointingHandCursor)
        done_btn.clicked.connect(lambda: on_remove(item["key"]))

        top.addWidget(badge)
        top.addWidget(name, 1)
        top.addWidget(votes)
        top.addWidget(done_btn)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        user = QLabel(f"👤 @{item['requester']}")
        user.setObjectName("songMeta")
        moment = QLabel(f"🕒 {item['time']}")
        moment.setObjectName("songMeta")
        bottom.addWidget(user)
        bottom.addStretch(1)
        bottom.addWidget(moment)
        outer.addLayout(bottom)


class VoteOptionInputRow(QWidget):
    """主播后台投票选项编辑行：弹幕输入关键词 + 选项描述 + 删除按钮。"""

    def __init__(self, trigger: str, label: str, on_delete, parent: Optional[QWidget] = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.trigger_edit = QLineEdit(trigger)
        self.trigger_edit.setObjectName("inputField")
        self.trigger_edit.setPlaceholderText("弹幕输入")
        self.trigger_edit.setFixedWidth(92)

        self.label_edit = QLineEdit(label)
        self.label_edit.setObjectName("inputField")
        self.label_edit.setPlaceholderText("选项内容，如：支持1选项")

        self.del_btn = QPushButton("×")
        self.del_btn.setObjectName("textButton")
        self.del_btn.setFixedWidth(36)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.clicked.connect(lambda: on_delete(self))

        row.addWidget(self.trigger_edit)
        row.addWidget(self.label_edit, 1)
        row.addWidget(self.del_btn)


class VoteResultCard(QFrame):
    """主播后台单个投票选项的实时进度展示卡片。"""

    def __init__(self, opt: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("voteRowCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        badge = QLabel(opt["trigger"])
        badge.setObjectName("voteBadge" if opt["is_leading"] else "songIndex")
        label = QLabel(opt["label"])
        label.setObjectName("songName")
        label.setWordWrap(True)
        stats = QLabel(f"{opt['votes']} 票 ({opt['percent']}%)")
        stats.setObjectName("songMeta")
        top.addWidget(badge)
        top.addWidget(label, 1)
        top.addWidget(stats)
        outer.addLayout(top)

        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(int(round(opt["percent"] * 10)))
        bar.setTextVisible(False)
        outer.addWidget(bar)


class ListenerThread(QThread):
    """收弹幕 -> 通知主窗口（由主窗口同时分发给点歌与投票）。"""

    danmaku_received = Signal(object)
    song_found = Signal(object)
    status = Signal(str)
    danmaku_count = Signal(int)

    def __init__(self, room_id: str = "", cookie: str = "", messages=None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.room_id = room_id
        self.cookie = cookie
        self.messages = messages
        self.stop_event = threading.Event()

    def _source(self):
        if self.messages is not None:
            return self.messages() if callable(self.messages) else self.messages
        return DanmakuStream(self.room_id, self.cookie, self.stop_event, self.status.emit)

    def run(self) -> None:
        seen = 0
        try:
            for message in self._source():
                seen += 1
                self.danmaku_count.emit(seen)
                self.danmaku_received.emit(message)
                request = parse(message)
                if request is not None:
                    self.song_found.emit(request)
                if self.stop_event.is_set():
                    break
        except Exception as e:
            self.status.emit(f"监听异常：{type(e).__name__}: {e}")
        finally:
            self.status.emit("已停止监听")

    def stop(self) -> None:
        self.stop_event.set()


class SongDisplayWindow(QWidget):
    def __init__(self, room_id: str = "", dark: Optional[bool] = None,
                 cookie: str = "", messages=None):
        super().__init__()
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Orange BiliRequest")
        self.resize(620, 820)

        self.thread: Optional[ListenerThread] = None
        self.dark = _guess_dark() if dark is None else dark
        self.cookie = cookie
        self.messages = messages
        self._total_danmaku = 0
        self._option_rows: List[VoteOptionInputRow] = []

        self.state = BoardState()
        self.obs_server = ObsOverlayServer(self.state)
        self._obs_port_error: Optional[str] = None
        try:
            self.obs_server.start()
        except OSError as exc:
            self._obs_port_error = str(exc)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # 1. 顶部标题栏
        bar = QFrame()
        bar.setObjectName("appBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(18, 12, 18, 12)
        icon = QLabel()
        icon.setObjectName("appIcon")
        logo = QPixmap(str(resource("logo.png")))
        if logo.isNull():
            icon.setText("🎵")
        else:
            icon.setPixmap(logo.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.setWindowIcon(QIcon(logo))

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("Orange BiliRequest")
        title.setObjectName("appTitle")
        self.subtitle = QLabel("直播间 roomId：未开始")
        self.subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(self.subtitle)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("textButton")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.clicked.connect(self.toggle_theme)

        bar_layout.addWidget(icon)
        bar_layout.addLayout(titles, 1)
        bar_layout.addWidget(self.theme_button)
        root.addWidget(bar)

        # 2. 房间号与监听控制
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.room_input = QLineEdit(room_id)
        self.room_input.setObjectName("roomIdField")
        self.room_input.setPlaceholderText("输入直播间房间号，例如 21452505")
        self.room_input.setClearButtonEnabled(True)
        self.room_input.returnPressed.connect(self.toggle_listening)
        self.start_button = QPushButton("开始监听")
        self.start_button.setObjectName("filledButton")
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.toggle_listening)
        controls.addWidget(self.room_input, 1)
        controls.addWidget(self.start_button)
        root.addLayout(controls)

        # 3. OBS 直播间展示控制栏
        obs_bar = QFrame()
        obs_bar.setObjectName("obsBar")
        obs_layout = QHBoxLayout(obs_bar)
        obs_layout.setContentsMargins(14, 10, 14, 10)
        obs_layout.setSpacing(8)

        obs_title = QLabel("📺 OBS 浏览器源")
        obs_title.setObjectName("listHeading")
        self.obs_mode_combo = QComboBox()
        self.obs_mode_combo.setObjectName("comboBox")
        self.obs_mode_combo.addItem("跟随当前页", "auto")
        self.obs_mode_combo.addItem("仅点歌板", "songs")
        self.obs_mode_combo.addItem("仅投票板", "vote")
        self.obs_mode_combo.addItem("双板同屏", "both")
        self.obs_mode_combo.currentIndexChanged.connect(self._on_obs_mode_changed)

        self.copy_obs_btn = QPushButton("复制 OBS 链接")
        self.copy_obs_btn.setObjectName("tonalButton")
        self.copy_obs_btn.setCursor(Qt.PointingHandCursor)
        self.copy_obs_btn.clicked.connect(self._copy_obs_url)

        self.preview_obs_btn = QPushButton("预览")
        self.preview_obs_btn.setObjectName("textButton")
        self.preview_obs_btn.setCursor(Qt.PointingHandCursor)
        self.preview_obs_btn.clicked.connect(self._preview_obs_overlay)

        obs_layout.addWidget(obs_title)
        obs_layout.addWidget(self.obs_mode_combo)
        obs_layout.addStretch(1)
        obs_layout.addWidget(self.copy_obs_btn)
        obs_layout.addWidget(self.preview_obs_btn)
        root.addWidget(obs_bar)

        # 4. 功能分页切换（点歌管理 / 弹幕投票）
        tab_row = QHBoxLayout()
        tab_row.setSpacing(10)
        self.songs_tab_btn = QPushButton("🎵 点歌管理")
        self.songs_tab_btn.setObjectName("tabButton")
        self.songs_tab_btn.setCursor(Qt.PointingHandCursor)
        self.songs_tab_btn.clicked.connect(lambda: self.switch_tab(0))

        self.vote_tab_btn = QPushButton("📊 弹幕投票")
        self.vote_tab_btn.setObjectName("tabButton")
        self.vote_tab_btn.setCursor(Qt.PointingHandCursor)
        self.vote_tab_btn.clicked.connect(lambda: self.switch_tab(1))

        tab_row.addWidget(self.songs_tab_btn, 1)
        tab_row.addWidget(self.vote_tab_btn, 1)
        root.addLayout(tab_row)

        # 5. 主体堆栈页面
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_songs_page())
        self.pages.addWidget(self._build_vote_page())
        root.addWidget(self.pages, 1)

        # 6. 底部状态行
        status_row = QHBoxLayout()
        self.state_dot = QLabel("●")
        self.state_dot.setObjectName("stateDot")
        initial_status = (
            f"OBS 服务启动失败：{self._obs_port_error}"
            if self._obs_port_error
            else f"已就绪 · OBS 地址：{self.obs_server.overlay_url()}"
        )
        self.status_label = QLabel(initial_status)
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.state_dot)
        status_row.addWidget(self.status_label, 1)
        root.addLayout(status_row)

        self.switch_tab(0)
        self._refresh_songs_ui()
        self._refresh_vote_results_ui()
        self.apply_theme()

    # --- 页面构建 ------------------------------------------------------------

    def _build_songs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("🎵 点歌排行")
        heading.setObjectName("listHeading")
        self.round_timer_check = QCheckBox("60分钟一榜")
        self.round_timer_check.setChecked(False)
        self.round_timer_check.toggled.connect(self.state.set_round_timer_enabled)
        self.song_count_label = QLabel("0 首 · 0 人参与")
        self.song_count_label.setObjectName("statusLabel")
        clear_btn = QPushButton("清空列表")
        clear_btn.setObjectName("tonalButton")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self.clear_list)
        heading_row.addWidget(heading)
        heading_row.addWidget(self.round_timer_check)
        heading_row.addStretch(1)
        heading_row.addWidget(self.song_count_label)
        heading_row.addWidget(clear_btn)
        layout.addLayout(heading_row)

        self.song_scroll = QScrollArea()
        self.song_scroll.setWidgetResizable(True)
        host = QWidget()
        self.song_list_layout = QVBoxLayout(host)
        self.song_list_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.song_list_layout.setContentsMargins(0, 0, 6, 0)
        self.song_list_layout.setSpacing(10)

        self.song_hint = QFrame()
        self.song_hint.setObjectName("hintCard")
        hint_layout = QVBoxLayout(self.song_hint)
        hint_layout.setContentsMargins(18, 22, 18, 22)
        hint_text = QLabel("还没有人点歌。\n点「开始监听」后，观众发送「点歌 歌名」就会自动上榜并同步到 OBS。")
        hint_text.setObjectName("hintText")
        hint_text.setWordWrap(True)
        hint_layout.addWidget(hint_text)
        self.song_list_layout.addWidget(self.song_hint)
        self.song_list_layout.addStretch(1)
        self.song_scroll.setWidget(host)
        layout.addWidget(self.song_scroll, 1)
        return page

    def _build_vote_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        # 投票设置卡片
        setup_card = QFrame()
        setup_card.setObjectName("sectionCard")
        setup_layout = QVBoxLayout(setup_card)
        setup_layout.setContentsMargins(16, 14, 16, 14)
        setup_layout.setSpacing(10)

        q_row = QHBoxLayout()
        q_lbl = QLabel("问题：")
        q_lbl.setObjectName("listHeading")
        self.vote_question_edit = QLineEdit(self.state.vote_question)
        self.vote_question_edit.setObjectName("inputField")
        self.vote_question_edit.setPlaceholderText("输入投票问题，例如：下一把玩什么？")
        q_row.addWidget(q_lbl)
        q_row.addWidget(self.vote_question_edit, 1)
        setup_layout.addLayout(q_row)

        opts_scroll = QScrollArea()
        opts_scroll.setWidgetResizable(True)
        opts_scroll.setMaximumHeight(210)
        opts_host = QWidget()
        self.vote_options_layout = QVBoxLayout(opts_host)
        self.vote_options_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.vote_options_layout.setContentsMargins(0, 0, 4, 0)
        self.vote_options_layout.setSpacing(6)
        opts_scroll.setWidget(opts_host)
        setup_layout.addWidget(opts_scroll)

        for opt in self.state.vote_options:
            self._add_option_row(opt.trigger, opt.label)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self.add_opt_btn = QPushButton("+ 添加选项")
        self.add_opt_btn.setObjectName("textButton")
        self.add_opt_btn.setCursor(Qt.PointingHandCursor)
        self.add_opt_btn.clicked.connect(self._on_add_option_clicked)
        self._sync_option_delete_buttons()

        self.single_vote_check = QCheckBox("每人限投 1 票")
        self.single_vote_check.setChecked(True)

        self.reset_vote_btn = QPushButton("重置票数")
        self.reset_vote_btn.setObjectName("textButton")
        self.reset_vote_btn.setCursor(Qt.PointingHandCursor)
        self.reset_vote_btn.clicked.connect(self._on_reset_vote)

        self.toggle_vote_btn = QPushButton("开始投票")
        self.toggle_vote_btn.setObjectName("filledButton")
        self.toggle_vote_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_vote_btn.clicked.connect(self._on_toggle_vote)

        ctrl_row.addWidget(self.add_opt_btn)
        ctrl_row.addWidget(self.single_vote_check)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self.reset_vote_btn)
        ctrl_row.addWidget(self.toggle_vote_btn)
        setup_layout.addLayout(ctrl_row)
        layout.addWidget(setup_card)

        # 实时投票结果卡片
        result_card = QFrame()
        result_card.setObjectName("sectionCard")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(16, 12, 16, 12)
        result_layout.setSpacing(8)

        res_head = QHBoxLayout()
        res_title = QLabel("📊 实时投票数据")
        res_title.setObjectName("listHeading")
        self.vote_summary_label = QLabel("未开始 · 0 人参与 · 共 0 票")
        self.vote_summary_label.setObjectName("statusLabel")
        res_head.addWidget(res_title)
        res_head.addStretch(1)
        res_head.addWidget(self.vote_summary_label)
        result_layout.addLayout(res_head)

        res_scroll = QScrollArea()
        res_scroll.setWidgetResizable(True)
        res_host = QWidget()
        self.vote_results_layout = QVBoxLayout(res_host)
        self.vote_results_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.vote_results_layout.setContentsMargins(0, 0, 4, 0)
        self.vote_results_layout.setSpacing(8)
        self.vote_results_layout.addStretch(1)
        res_scroll.setWidget(res_host)
        result_layout.addWidget(res_scroll, 1)
        layout.addWidget(result_card, 1)
        return page

    # --- 主题与分页 ----------------------------------------------------------

    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet((DARK if self.dark else LIGHT).qss())
        self.theme_button.setText("☀️ 浅色" if self.dark else "🌙 深色")
        self.subtitle.setText(self.subtitle.text())

    def toggle_theme(self) -> None:
        self.dark = not self.dark
        self.apply_theme()

    def switch_tab(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.songs_tab_btn.setProperty("active", "true" if index == 0 else "false")
        self.vote_tab_btn.setProperty("active", "true" if index == 1 else "false")
        for btn in (self.songs_tab_btn, self.vote_tab_btn):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.state.set_active_tab("songs" if index == 0 else "vote")

    # --- OBS 控制 ------------------------------------------------------------

    def _on_obs_mode_changed(self) -> None:
        mode = self.obs_mode_combo.currentData()
        if mode:
            self.state.set_obs_mode(mode)

    def _copy_obs_url(self) -> None:
        mode = self.obs_mode_combo.currentData() or "auto"
        url = self.obs_server.overlay_url(mode)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(url)
        self.status_label.setText(f"已复制 OBS 浏览器源地址：{url}")

    def _preview_obs_overlay(self) -> None:
        mode = self.obs_mode_combo.currentData() or "auto"
        url = self.obs_server.overlay_url(mode)
        QDesktopServices.openUrl(QUrl(url))

    # --- 监听控制 ------------------------------------------------------------

    def toggle_listening(self) -> None:
        if self.thread is not None:
            self.stop_listening()
            return
        if self.messages is not None:
            self.start_listening("demo")
            return
        room_id = self.room_input.text().strip()
        if not room_id.isdigit():
            self.status_label.setText("房间号要是纯数字")
            return
        self.start_listening(room_id)

    def start_listening(self, room_id: str) -> None:
        self.room_input.setEnabled(False)
        self.start_button.setText("停止监听")
        self.subtitle.setText(f"直播间 roomId：{room_id}")
        self.status_label.setText("正在推送演示弹幕…" if self.messages else "正在连接聊天服务器…")
        self.state.set_listening(True)
        self.thread = ListenerThread(room_id, self.cookie, self.messages, self)
        self.thread.danmaku_received.connect(self._on_danmaku_received)
        self.thread.status.connect(self.set_status)
        self.thread.danmaku_count.connect(self._show_count)
        self.thread.finished.connect(self._on_thread_finished)
        self.thread.start()

    def stop_listening(self) -> None:
        if self.thread is None:
            return
        self.thread.stop()
        self.thread.wait(4000)

    def _on_thread_finished(self) -> None:
        self.thread = None
        self.state.set_listening(False)
        self.room_input.setEnabled(True)
        self.start_button.setText("开始监听")

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _show_count(self, total: int) -> None:
        self._total_danmaku = total
        snap = self.state.snapshot()
        self.status_label.setText(
            f"已收到 {total} 条弹幕 · {snap['songs']['count']} 首点歌 · "
            f"投票 {snap['vote']['total_votes']} 票"
        )

    def _on_danmaku_received(self, danmaku) -> None:
        req = parse(danmaku)
        if req is not None and self.state.add_song_request(req):
            self._refresh_songs_ui()
        if self.state.process_vote_danmaku(danmaku) is not None:
            self._refresh_vote_results_ui()

    # --- 点歌管理 ------------------------------------------------------------

    def add_request(self, request: SongRequest) -> None:
        if self.state.add_song_request(request):
            self._refresh_songs_ui()

    def _remove_song(self, song_key: str) -> None:
        if self.state.remove_song(song_key):
            self._refresh_songs_ui()

    def clear_list(self) -> None:
        self.state.clear_songs()
        self._refresh_songs_ui()

    def _refresh_songs_ui(self) -> None:
        snap = self.state.snapshot()["songs"]
        items = snap["items"]
        self.song_count_label.setText(f"{snap['count']} 首 · {snap['participants']} 人参与")

        # 清理旧卡片（保留最后的 hint 与 stretch）
        for i in reversed(range(self.song_list_layout.count())):
            item = self.song_list_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, SongCard):
                self.song_list_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()

        self.song_hint.setVisible(len(items) == 0)
        for idx, entry in enumerate(items):
            card = SongCard(entry, self._remove_song)
            self.song_list_layout.insertWidget(idx, card)

    # --- 弹幕投票设置与展示 --------------------------------------------------

    def _add_option_row(self, trigger: str, label: str) -> None:
        row = VoteOptionInputRow(trigger, label, self._delete_option_row)
        self._option_rows.append(row)
        self.vote_options_layout.addWidget(row)
        self._sync_option_delete_buttons()

    def _delete_option_row(self, row: VoteOptionInputRow) -> None:
        if len(self._option_rows) <= MIN_VOTE_OPTIONS:
            return
        self._option_rows.remove(row)
        self.vote_options_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._sync_option_delete_buttons()

    def _sync_option_delete_buttons(self) -> None:
        can_del = len(self._option_rows) > MIN_VOTE_OPTIONS
        for r in self._option_rows:
            r.del_btn.setEnabled(can_del)
        if hasattr(self, "add_opt_btn"):
            self.add_opt_btn.setEnabled(len(self._option_rows) < MAX_VOTE_OPTIONS)

    def _on_add_option_clicked(self) -> None:
        if len(self._option_rows) >= MAX_VOTE_OPTIONS:
            return
        idx = len(self._option_rows) + 1
        self._add_option_row(str(idx), f"支持{idx}选项")

    def _apply_vote_config(self) -> None:
        question = self.vote_question_edit.text().strip()
        pairs: List[Tuple[str, str]] = [
            (r.trigger_edit.text(), r.label_edit.text())
            for r in self._option_rows
        ]
        self.state.configure_vote(
            question=question,
            options=pairs,
            single_vote_per_user=self.single_vote_check.isChecked(),
        )

    def _on_toggle_vote(self) -> None:
        snap = self.state.snapshot()["vote"]
        if snap["active"]:
            self.state.set_vote_active(False)
            self.toggle_vote_btn.setText("开始投票")
        else:
            self._apply_vote_config()
            self.state.set_vote_active(True)
            self.toggle_vote_btn.setText("结束投票")
        self._refresh_vote_results_ui()

    def _on_reset_vote(self) -> None:
        self._apply_vote_config()
        self.state.reset_votes()
        self._refresh_vote_results_ui()

    def _refresh_vote_results_ui(self) -> None:
        vote = self.state.snapshot()["vote"]
        state_text = "投票中" if vote["active"] else "未开始/已结束"
        self.vote_summary_label.setText(
            f"{state_text} · {vote['participants']} 人参与 · 共 {vote['total_votes']} 票"
        )
        self.toggle_vote_btn.setText("结束投票" if vote["active"] else "开始投票")

        for i in reversed(range(self.vote_results_layout.count())):
            item = self.vote_results_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, VoteResultCard):
                self.vote_results_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()

        for idx, opt in enumerate(vote["options"]):
            self.vote_results_layout.insertWidget(idx, VoteResultCard(opt))

    def closeEvent(self, event) -> None:
        self.stop_listening()
        self.obs_server.stop()
        super().closeEvent(event)


def _guess_dark() -> bool:
    app = QApplication.instance()
    hints = app.styleHints() if app is not None else None
    scheme = getattr(hints, "colorScheme", None)
    if scheme is None:
        return False
    try:
        return scheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def build_window(room_id: str = "", dark: Optional[bool] = None, cookie: str = "",
                 messages=None) -> SongDisplayWindow:
    window = SongDisplayWindow(room_id=room_id, dark=dark, cookie=cookie, messages=messages)
    window.apply_theme()
    return window


def run(room_id: str = "", dark: Optional[bool] = None, cookie: str = "",
        messages=None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Orange BiliRequest")
    default_font = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
    app.setFont(QFont(default_font, 10))
    window = build_window(room_id, dark, cookie, messages)
    window.show()
    return app.exec()
