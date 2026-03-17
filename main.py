"""
Elon-Mascot — PyQt6 Live2D デスクトップマスコット
Mac Mini 上の Elon-AI API サーバーと通信する独立アプリ
"""
import json
import math
import os
import random
import subprocess
import sys
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QObject, QEvent, pyqtSignal, QPoint, QPointF, QRectF,
)
from PyQt6.QtGui import (
    QAction, QColor, QCursor, QFont, QIcon, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)

import api_client
from features.timer import TimerWindow

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "config.json"
HTML_PATH = APP_DIR / "live2d.html"
MODEL_JSON = APP_DIR / "model" / "034star.model3.json"
NOTIFY_FILE = Path.home() / ".config" / "elon-mascot" / "notifications.json"
CONFIG_DIR = Path.home() / ".config" / "elon-mascot"

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------
IDLE = "idle"
TALK = "talk"
ALERT = "alert"
THINK = "think"
HAPPY = "happy"
ERROR = "error"
TIRED = "tired"

# Expression / motion mapping per state
_STATE_EXPR = {
    IDLE:  ("",        ""),
    TALK:  ("",        "TalkA"),
    ALERT: ("f02",     ""),
    THINK: ("f04",     ""),
    HAPPY: ("f01",     ""),
    ERROR: ("f03",     ""),
    TIRED: ("f05",     ""),
}

# ---------------------------------------------------------------------------
# VOICEVOX helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _speak_voicevox(text: str):
    """VOICEVOX でテキストを読み上げる（ブロッキング）"""
    cfg = _load_config()
    base = cfg.get("voicevox_url", "http://127.0.0.1:50021").rstrip("/")
    speaker = int(cfg.get("voicevox_speaker", 1))
    try:
        # audio_query
        q_url = f"{base}/audio_query?text={urllib.request.quote(text)}&speaker={speaker}"
        with urllib.request.urlopen(q_url, timeout=10) as resp:
            query = resp.read()
        # synthesis
        req = urllib.request.Request(
            f"{base}/synthesis?speaker={speaker}",
            data=query,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            wav = resp.read()
        # play via afplay (macOS)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav)
            tmp = f.name
        subprocess.run(["afplay", tmp], check=False)
        os.unlink(tmp)
    except Exception:
        pass


def speak_async(text: str):
    """非同期で VOICEVOX 読み上げ"""
    threading.Thread(target=_speak_voicevox, args=(text,), daemon=True).start()


# ---------------------------------------------------------------------------
# launchd agent reader
# ---------------------------------------------------------------------------

def _read_launchd_agents() -> list[dict]:
    """~/Library/LaunchAgents の plist から有効なエージェント一覧を返す"""
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    results = []
    if not agents_dir.exists():
        return results
    for plist in sorted(agents_dir.glob("*.plist")):
        try:
            import plistlib
            data = plistlib.loads(plist.read_bytes())
            label = data.get("Label", plist.stem)
            program = data.get("Program") or (data.get("ProgramArguments") or [""])[0]
            enabled = not data.get("Disabled", False)
            results.append({
                "label": label,
                "program": program,
                "enabled": enabled,
                "plist": str(plist),
            })
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# SchedulePanel
# ---------------------------------------------------------------------------

class SchedulePanel(QWidget):
    """launchd エージェント一覧パネル"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("スケジュール / LaunchAgents")
        self.setMinimumSize(520, 360)
        self.setStyleSheet("""
            QWidget { background: #0d0d1f; color: #c0c0d0;
                      font-family: 'Hiragino Sans', sans-serif; }
            QLabel { font-size: 13px; }
            QPushButton {
                background: #1a1a30; color: #00ffcc;
                border: 1px solid #00ffcc; border-radius: 6px;
                padding: 5px 16px; font-size: 12px;
            }
            QPushButton:hover { background: #00ffcc22; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("LaunchAgents 一覧")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #00ffcc;")
        layout.addWidget(title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border: none;")
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setSpacing(6)
        self._inner_layout.addStretch()
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self):
        # clear
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        agents = _read_launchd_agents()
        if not agents:
            lbl = QLabel("LaunchAgents が見つかりません")
            lbl.setStyleSheet("color: #666;")
            self._inner_layout.insertWidget(0, lbl)
            return

        for i, ag in enumerate(agents):
            row = QHBoxLayout()
            status = "✅" if ag["enabled"] else "⛔"
            name_lbl = QLabel(f"{status}  {ag['label']}")
            name_lbl.setStyleSheet("font-size: 12px;")
            prog_lbl = QLabel(ag["program"])
            prog_lbl.setStyleSheet("font-size: 11px; color: #888;")
            col = QVBoxLayout()
            col.addWidget(name_lbl)
            col.addWidget(prog_lbl)
            row.addLayout(col)
            row.addStretch()
            container = QWidget()
            container.setLayout(row)
            container.setStyleSheet(
                "background: #12122a; border-radius: 6px; padding: 6px;"
                if i % 2 == 0 else
                "background: #0f0f22; border-radius: 6px; padding: 6px;"
            )
            self._inner_layout.insertWidget(i, container)


# ---------------------------------------------------------------------------
# ConnectionSettingsWindow
# ---------------------------------------------------------------------------

class ConnectionSettingsWindow(QDialog):
    """API接続設定ダイアログ"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("接続設定")
        self.setFixedSize(420, 260)
        self.setStyleSheet("""
            QDialog { background: #0d0d1f; color: #c0c0d0;
                      font-family: 'Hiragino Sans', sans-serif; }
            QLabel { font-size: 13px; }
            QLineEdit {
                background: #10102a; color: #c0c0d0;
                border: 1px solid #333; border-radius: 4px;
                padding: 5px; font-size: 13px;
            }
            QPushButton {
                background: #1a1a30; color: #00ffcc;
                border: 1px solid #00ffcc; border-radius: 6px;
                padding: 6px 20px; font-size: 13px;
            }
            QPushButton:hover { background: #00ffcc22; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://100.105.12.49:8765")
        form.addRow("API URL:", self._url_edit)

        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("elon_secret_key_2025")
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self._key_edit)

        self._sid_edit = QLineEdit()
        self._sid_edit.setPlaceholderText("mascot")
        form.addRow("Session ID:", self._sid_edit)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 300)
        self._timeout_spin.setSuffix(" 秒")
        self._timeout_spin.setStyleSheet(
            "background: #10102a; color: #c0c0d0; border: 1px solid #333; border-radius: 4px; padding: 4px;"
        )
        form.addRow("タイムアウト:", self._timeout_spin)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._load()

    def _load(self):
        cfg = api_client.load_config()
        self._url_edit.setText(cfg.get("elon_api_url", ""))
        self._key_edit.setText(cfg.get("elon_api_key", ""))
        self._sid_edit.setText(cfg.get("session_id", "mascot"))
        self._timeout_spin.setValue(int(cfg.get("timeout", 60)))

    def _save(self):
        try:
            cfg = api_client.load_config()
        except Exception:
            cfg = {}
        cfg["elon_api_url"] = self._url_edit.text().strip()
        cfg["elon_api_key"] = self._key_edit.text().strip()
        cfg["session_id"] = self._sid_edit.text().strip() or "mascot"
        cfg["timeout"] = self._timeout_spin.value()
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(self, "保存完了", "設定を保存しました。")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存失敗: {e}")


# ---------------------------------------------------------------------------
# Context cache  （バックグラウンドで5分ごとに更新）
# ---------------------------------------------------------------------------

_ctx_cache: dict = {
    "tasks": [],
    "trello_summary": "",
    "cal_summary": "",
    "updated_at": None,
}
_ctx_lock = threading.Lock()
_CTX_TTL = 5 * 60  # 5分


def _refresh_context_cache():
    """外部APIを叩いてキャッシュを更新する（別スレッドで実行）"""
    from integrations.ticktick import get_tasks as tt_tasks, is_enabled as tt_enabled
    from integrations.trello import get_cards, get_summary as trello_summary, is_enabled as trello_enabled
    from integrations.gcal import get_summary as gcal_summary, is_enabled as gcal_enabled

    tasks: list = []
    trello_str = ""
    cal_str = ""

    try:
        if tt_enabled():
            tasks = tt_tasks()
        if trello_enabled():
            if not tasks:
                tasks = get_cards()
            trello_str = trello_summary()
    except Exception:
        pass

    try:
        if gcal_enabled():
            cal_str = gcal_summary(days=7)
    except Exception:
        pass

    with _ctx_lock:
        _ctx_cache["tasks"] = tasks
        _ctx_cache["trello_summary"] = trello_str
        _ctx_cache["cal_summary"] = cal_str
        _ctx_cache["updated_at"] = datetime.now()


def refresh_context_async():
    """バックグラウンドでキャッシュを更新する"""
    threading.Thread(target=_refresh_context_cache, daemon=True).start()


def _build_context_message(user_msg: str) -> str:
    """キャッシュからコンテキストを組み立てメッセージに付加する（ノンブロッキング）"""
    now = datetime.now()
    with _ctx_lock:
        tasks = list(_ctx_cache["tasks"])
        trello_str = _ctx_cache["trello_summary"]
        cal_str = _ctx_cache["cal_summary"]
        updated = _ctx_cache["updated_at"]

    lines = [f"[システムコンテキスト] 現在日時: {now.strftime('%Y年%m月%d日（%A）%H:%M')}"]

    if tasks:
        p_map = {"high": "🔴", "normal": "🟡", "low": "🟢"}
        task_lines = [
            f"  {p_map.get(t.get('priority','normal'),'🟡')} {t['title']}"
            + (f" 〆{t['due_date']}" if t.get("due_date") else "")
            for t in tasks[:10]
        ]
        lines.append(f"【未完了タスク ({len(tasks)}件)】\n" + "\n".join(task_lines))
    else:
        lines.append("【未完了タスク】なし")

    if trello_str:
        lines.append(f"【Trelloボード】\n{trello_str}")

    if cal_str:
        lines.append(f"【今後7日間のカレンダー】\n{cal_str}")

    lines.append(f"\n【ユーザーの質問】{user_msg}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BubbleOverlay
# ---------------------------------------------------------------------------

class BubbleOverlay(QWidget):
    """吹き出しオーバーレイ（フレームレス透明ウィンドウ）"""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(320)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.setFixedWidth(292)  # padding分を引いた幅に固定
        self._label.setStyleSheet("""
            QLabel {
                color: #e8e8f0;
                font-family: 'Hiragino Sans', 'Noto Sans CJK JP', sans-serif;
                font-size: 13px;
                padding: 0px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 24)  # 下24pxは吹き出しの尻尾分
        layout.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text: str, duration: int = 6000):
        self._label.setText(text)
        # ラベルの高さをテキスト量に合わせて再計算
        self._label.adjustSize()
        # ウィンドウ全体の高さを再計算（上下マージン + ラベル高 + 尻尾）
        new_h = self._label.height() + 14 + 24  # top_margin + bottom(tail)
        self.setFixedHeight(max(new_h, 60))
        self.adjustSize()
        self._hide_timer.stop()
        self.show()
        if duration > 0:
            self._hide_timer.start(duration)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        tail = 14  # tail height at bottom

        path = QPainterPath()
        r = 12  # corner radius
        body_h = h - tail

        path.moveTo(r, 0)
        path.lineTo(w - r, 0)
        path.quadTo(w, 0, w, r)
        path.lineTo(w, body_h - r)
        path.quadTo(w, body_h, w - r, body_h)
        # tail pointing down-left
        path.lineTo(w // 2 + 20, body_h)
        path.lineTo(w // 2, body_h + tail)
        path.lineTo(w // 2 - 14, body_h)
        path.lineTo(r, body_h)
        path.quadTo(0, body_h, 0, body_h - r)
        path.lineTo(0, r)
        path.quadTo(0, 0, r, 0)
        path.closeSubpath()

        painter.fillPath(path, QColor(14, 14, 32, 220))
        painter.setPen(QPen(QColor(0, 255, 200, 80), 1))
        painter.drawPath(path)


# ---------------------------------------------------------------------------
# ClaudeCharacterView  — Claw'd ピクセルアートマスコット
# ---------------------------------------------------------------------------
# Claw'd の体色（Anthropicのサーモンオレンジ）
_CLAWD_COLOR  = QColor(0xC9, 0x70, 0x4E)
_CLAWD_DARK   = QColor(0xA0, 0x50, 0x30)   # 影・輪郭
_CLAWD_EYE    = QColor(0x18, 0x10, 0x0C)   # 目の黒

# ピクセルグリッド定義 (10×10)
# 1=体, 0=透明
# 画像に合わせた Claw'd 体型: 横幅広め、腕スタブは低め
_GRID_BODY = [
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 0  ← 体上部
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],  # row 1  ← 腕スタブ（上）
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],  # row 2  ← 腕スタブ（下）
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 3
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 4  ← 体下部
    [0, 1, 0, 1, 0, 1, 0, 1, 0, 0],  # row 5  ← 足（4本）
    [0, 1, 0, 1, 0, 1, 0, 1, 0, 0],  # row 6  ← 足（4本）
    [0, 1, 0, 1, 0, 1, 0, 1, 0, 0],  # row 7  ← 足（4本）
]
# 目のグリッド位置 (row, col) — 左目・右目（腕と同じ高さ row 1）
_EYE_L = (1, 3)
_EYE_R = (1, 6)


class ClaudeCharacterView(QWidget):
    """Claw'd スタイルのピクセルアートマスコット"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 260)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._state = IDLE
        self._lip   = 0.0      # 口パク 0.0〜1.0
        self._bob   = 0.0      # ふわふわ位相
        self._blink = 1.0      # 1.0=全開, 0.0=全閉

        # アニメーションタイマー（30fps）
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(33)

        # まばたきタイマー
        self._blink_dir = 0    # 0=待機, -1=閉じ中, 1=開き中
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._start_blink)
        self._blink_timer.start(random.randint(3000, 5000))

    def _tick(self):
        self._bob += 0.07
        if self._blink_dir == -1:
            self._blink = max(0.0, self._blink - 0.2)
            if self._blink == 0.0:
                self._blink_dir = 1
        elif self._blink_dir == 1:
            self._blink = min(1.0, self._blink + 0.2)
            if self._blink == 1.0:
                self._blink_dir = 0
                self._blink_timer.start(random.randint(2500, 5500))
        self.update()

    def _start_blink(self):
        self._blink_dir = -1

    def set_state(self, state: str):
        self._state = state
        self.update()

    def set_lip(self, value: float):
        self._lip = max(0.0, min(1.0, value))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # ピクセルアートなので無効

        W = self.width()
        U = 22  # 1グリッド単位 (px)
        cols = len(_GRID_BODY[0])  # 10
        rows = len(_GRID_BODY)     # 9
        # 水平中央揃え, 垂直は上下のボブ込みで計算
        bob_offset = int(math.sin(self._bob) * 5)
        ox = (W - cols * U) // 2
        oy = 18 + bob_offset

        # ── 影 ─────────────────────────────────────────
        p.setBrush(QColor(0, 0, 0, 35))
        p.setPen(Qt.PenStyle.NoPen)
        sx = ox + U
        sy = oy + rows * U + 4
        p.drawEllipse(QRectF(sx, sy, (cols - 2) * U, 10))

        # ── 白アウトライン（ステッカー風）──────────────────
        O = 4  # アウトライン幅(px)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 230))
        for r, row in enumerate(_GRID_BODY):
            for c, cell in enumerate(row):
                if cell:
                    rx = ox + c * U
                    ry = oy + r * U
                    p.drawRect(rx - O, ry - O, U + O * 2, U + O * 2)

        # ── ボディ ──────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        for r, row in enumerate(_GRID_BODY):
            for c, cell in enumerate(row):
                if cell:
                    rx = ox + c * U
                    ry = oy + r * U
                    p.setBrush(_CLAWD_COLOR)
                    p.drawRect(rx, ry, U, U)

        # ── 目 ─────────────────────────────────────────
        self._draw_eyes(p, ox, oy, U)

        # ── 口（TALKまたはlip > 0 のとき） ──────────────
        mouth_open = max(self._lip, 0.4 if self._state == TALK else 0.0)
        if mouth_open > 0.05:
            mh = max(2, int(mouth_open * U * 0.6))
            mw = U * 2
            mx = ox + 4 * U
            my = oy + 4 * U - mh // 2
            p.setBrush(_CLAWD_DARK)
            p.drawRect(mx, my, mw, mh)

        p.end()

    def _draw_eyes(self, p: QPainter, ox: int, oy: int, U: int):
        """状態に応じて目を描く"""
        lx = ox + _EYE_L[1] * U
        rx = ox + _EYE_R[1] * U
        ey = oy + _EYE_L[0] * U

        ES = U      # eye cell size
        EW = U      # 目の描画幅（1グリッド分）

        p.setPen(Qt.PenStyle.NoPen)

        if self._state == TIRED:
            # 横線目（半分閉じ）
            p.setBrush(_CLAWD_EYE)
            h = max(3, int(EW * 0.25))
            p.drawRect(lx, ey + ES // 2 - h // 2, EW, h)
            p.drawRect(rx, ey + ES // 2 - h // 2, EW, h)

        elif self._state == THINK:
            # 左: 横線、右: >< の半分 (>)
            pen = QPen(_CLAWD_EYE, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(lx, ey + ES // 2, lx + EW, ey + ES // 2)
            # 右目: >
            p.drawLine(rx,        ey + 2,      rx + EW // 2, ey + ES // 2)
            p.drawLine(rx + EW // 2, ey + ES // 2, rx,        ey + ES - 2)
            p.setPen(Qt.PenStyle.NoPen)

        elif self._state in (ALERT, ERROR):
            # 大きな四角目（驚き）
            blink_h = max(3, int(EW * 0.9 * self._blink))
            p.setBrush(_CLAWD_EYE)
            p.drawRect(lx - 2, ey - 2, EW + 4, blink_h)
            p.drawRect(rx - 2, ey - 2, EW + 4, blink_h)

        elif self._state == HAPPY:
            # >< 目（Claw'd ハッピー）
            line_w = max(3, int(6 * self._blink))
            pen = QPen(_CLAWD_EYE, line_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cy = ey + ES // 2
            # 左目: >
            p.drawLine(lx,            cy - ES // 2 + 2, lx + EW // 2, cy)
            p.drawLine(lx + EW // 2,  cy,               lx,           cy + ES // 2 - 2)
            # 右目: <
            p.drawLine(rx + EW,       cy - ES // 2 + 2, rx + EW // 2, cy)
            p.drawLine(rx + EW // 2,  cy,               rx + EW,      cy + ES // 2 - 2)
            p.setPen(Qt.PenStyle.NoPen)

        else:
            # IDLE / TALK: 四角い目（元のスタイル）
            blink_h = max(2, int(EW * self._blink))
            p.setBrush(_CLAWD_EYE)
            p.drawRect(lx, ey, EW, blink_h)
            p.drawRect(rx, ey, EW, blink_h)


# ---------------------------------------------------------------------------
# InputWindow
# ---------------------------------------------------------------------------

class InputWindow(QWidget):
    """テキスト入力ウィンドウ"""
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setStyleSheet("""
            QWidget#inputContainer {
                background: #0d0d1f;
                border: 1px solid #00ffcc44;
                border-radius: 14px;
            }
        """)
        container.setObjectName("inputContainer")
        inner = QVBoxLayout(container)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(10)

        header = QLabel("Elon に話しかける")
        header.setStyleSheet("color: #00ffcc; font-size: 13px; font-weight: bold;")
        inner.addWidget(header)

        self._text = QTextEdit()
        self._text.setFixedHeight(80)
        self._text.setPlaceholderText("メッセージを入力… (Shift+Enter で改行、Enter で送信)")
        self._text.setStyleSheet("""
            QTextEdit {
                background: #10102a; color: #e8e8f0;
                border: 1px solid #333; border-radius: 6px;
                padding: 8px; font-size: 13px;
                font-family: 'Hiragino Sans', sans-serif;
            }
        """)
        self._text.installEventFilter(self)
        inner.addWidget(self._text)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setStyleSheet("""
            QPushButton { background: #1a1a30; color: #888; border: 1px solid #444;
                          border-radius: 6px; padding: 5px 14px; font-size: 12px; }
            QPushButton:hover { background: #22223a; }
        """)
        cancel_btn.clicked.connect(self.hide)

        send_btn = QPushButton("送信")
        send_btn.setStyleSheet("""
            QPushButton { background: #1a1a30; color: #00ffcc; border: 1px solid #00ffcc;
                          border-radius: 6px; padding: 5px 14px; font-size: 12px; }
            QPushButton:hover { background: #00ffcc22; }
        """)
        send_btn.clicked.connect(self._submit)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(send_btn)
        inner.addLayout(btn_row)

        outer.addWidget(container)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        if obj is self._text and event.type() == QEvent.Type.KeyPress:
            ke = event
            if ke.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (ke.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._submit()
                    return True
        return super().eventFilter(obj, event)

    def _submit(self):
        text = self._text.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self._text.clear()
            self.hide()

    def show_at(self, pos: QPoint):
        self.move(pos)
        self.show()
        self._text.setFocus()


# ---------------------------------------------------------------------------
# MascotWindow
# ---------------------------------------------------------------------------

class MascotWindow(QWidget):
    """メインマスコットウィンドウ"""

    _secretary_done = pyqtSignal(str)
    _secretary_error = pyqtSignal(str)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(240, 260)

        # State
        self._state = IDLE
        self._drag_pos: QPoint | None = None
        self._right_click_count = 0
        self._right_click_timer = QTimer()
        self._right_click_timer.setSingleShot(True)
        self._right_click_timer.timeout.connect(self._reset_right_click)

        # Claw'd キャラクター
        self._view = ClaudeCharacterView(self)
        vw, vh = self._view.width(), self._view.height()
        self._view.move((self.width() - vw) // 2, (self.height() - vh) // 2)

        # Bubble overlay
        self._bubble = BubbleOverlay()

        # Input window
        self._input_win = InputWindow()
        self._input_win.submitted.connect(self._on_input)

        # Timer window
        self._timer_window = TimerWindow()
        self._timer_window.timer_done.connect(self._on_timer_done)

        # Schedule panel
        self._schedule_panel = SchedulePanel()

        # Signals
        self._secretary_done.connect(self._on_api_done)
        self._secretary_error.connect(self._on_api_error)

        # Tray
        self._setup_tray()

        # Timers
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)

        # Idle proactive message timer (10 min)
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._idle_message)
        self._idle_timer.start(10 * 60 * 1000)

        # Notification check timer (30 sec)
        self._notify_timer = QTimer(self)
        self._notify_timer.timeout.connect(self._check_notifications)
        self._notify_timer.start(30_000)

        # コンテキストキャッシュを5分ごとに更新
        self._ctx_timer = QTimer(self)
        self._ctx_timer.timeout.connect(refresh_context_async)
        self._ctx_timer.start(5 * 60 * 1000)
        # 起動直後に1回即時取得
        QTimer.singleShot(2000, refresh_context_async)

        # Lip sync simulation timer
        self._lip_timer = QTimer(self)
        self._lip_timer.timeout.connect(self._lip_tick)
        self._lip_state = False

        # launchd check timer (5 min)
        self._launchd_timer = QTimer(self)
        self._launchd_timer.timeout.connect(self._check_launchd)
        self._launchd_timer.start(5 * 60 * 1000)

        # Position: bottom-right
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - 320, screen.bottom() - 420)

        # Startup greeting
        QTimer.singleShot(1500, self._startup_greeting)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _setup_tray(self):
        # Create a simple tray icon programmatically
        pix = QPixmap(32, 32)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 255, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()

        self._tray = QSystemTrayIcon(QIcon(pix), self)
        self._tray.setToolTip("Elon Mascot")
        self._tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background: #0d0d1f; color: #c0c0d0; border: 1px solid #333; }
            QMenu::item:selected { background: #1a1a40; color: #00ffcc; }
        """)

        chat_act = QAction("💬 話しかける", self)
        chat_act.triggered.connect(self._open_input)
        menu.addAction(chat_act)

        timer_act = QAction("⏱ タイマー", self)
        timer_act.triggered.connect(self._open_timer)
        menu.addAction(timer_act)

        schedule_act = QAction("📋 スケジュール", self)
        schedule_act.triggered.connect(self._schedule_panel.show)
        menu.addAction(schedule_act)

        settings_act = QAction("⚙ 接続設定", self)
        settings_act.triggered.connect(self._open_settings)
        menu.addAction(settings_act)

        health_act = QAction("🔌 ヘルスチェック", self)
        health_act.triggered.connect(self._do_health_check)
        menu.addAction(health_act)

        menu.addSeparator()

        quit_act = QAction("終了", self)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(quit_act)

        self._tray.setContextMenu(menu)
        self._tray.show()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _set_state(self, state: str):
        self._state = state
        self._view.set_state(state)

    # ------------------------------------------------------------------
    # Bubble
    # ------------------------------------------------------------------

    def show_bubble(self, text: str, duration: int = 6000, speak: bool = False):
        # テキストをセットしてサイズを確定してから配置する
        self._bubble.show_text(text, duration)
        self._bubble.adjustSize()

        bw = self._bubble.width()
        bh = self._bubble.height()

        pos = self.pos()
        # 吹き出しをマスコットの真上（上端より上）に配置
        bx = pos.x() + self.width() // 2 - bw // 2
        by = pos.y() - bh - 8  # 8px のギャップ

        # 画面からはみ出さないようにクランプ
        screen = QApplication.primaryScreen().availableGeometry()
        bx = max(screen.left() + 4, min(bx, screen.right() - bw - 4))
        by = max(screen.top() + 4, by)
        # 下にはみ出す場合はマスコットの右横に出す
        if by + bh > screen.bottom():
            by = pos.y()
            bx = max(screen.left() + 4, min(pos.x() - bw - 8, screen.right() - bw - 4))

        self._bubble.move(bx, by)
        if speak:
            speak_async(text)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.MouseButton.RightButton:
            self._right_click_count += 1
            if not self._right_click_timer.isActive():
                self._right_click_timer.start(400)
            if self._right_click_count >= 2:
                self._right_click_count = 0
                self._right_click_timer.stop()
                self._open_timer()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            # 吹き出しも追従（位置のみ更新）
            if self._bubble.isVisible():
                bw = self._bubble.width()
                bh = self._bubble.height()
                bx = new_pos.x() + self.width() // 2 - bw // 2
                by = new_pos.y() - bh - 8
                screen = QApplication.primaryScreen().availableGeometry()
                bx = max(screen.left() + 4, min(bx, screen.right() - bw - 4))
                by = max(screen.top() + 4, by)
                self._bubble.move(bx, by)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_input()

    def _reset_right_click(self):
        self._right_click_count = 0

    # ------------------------------------------------------------------
    # Input / API
    # ------------------------------------------------------------------

    def _open_input(self):
        pos = self.pos()
        iw = self._input_win
        ix = pos.x() + self.width() // 2 - iw.width() // 2
        iy = pos.y() - iw.height() - 20
        screen = QApplication.primaryScreen().availableGeometry()
        ix = max(screen.left(), min(ix, screen.right() - iw.width()))
        iy = max(screen.top(), iy)
        iw.show_at(QPoint(ix, iy))

    def _on_input(self, text: str):
        if not text:
            return
        self._set_state(THINK)
        self.show_bubble("🌐 Mac Miniに問い合わせ中...", duration=60000)
        enriched = _build_context_message(text)
        api_client.call_api(
            enriched,
            on_done=self._secretary_done.emit,
            on_error=self._secretary_error.emit,
        )

    def _on_api_done(self, reply: str):
        self._set_state(TALK)
        self._lip_timer.start(150)
        self.show_bubble(reply, duration=8000, speak=True)
        QTimer.singleShot(8000, lambda: (self._lip_timer.stop(), self._set_state(IDLE)))

    def _on_api_error(self, msg: str):
        self._set_state(ERROR)
        self.show_bubble(f"❌ {msg}", duration=6000)
        QTimer.singleShot(6000, lambda: self._set_state(IDLE))

    # ------------------------------------------------------------------
    # Lip sync simulation
    # ------------------------------------------------------------------

    def _lip_tick(self):
        self._lip_state = not self._lip_state
        self._view.set_lip(1.0 if self._lip_state else 0.2)

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _open_timer(self):
        self._timer_window.show()
        self._timer_window.raise_()

    def _on_timer_done(self, label: str):
        self._set_state(ALERT)
        self.show_bubble(f"⏰ {label} が完了しました！", duration=10000, speak=True)

    # ------------------------------------------------------------------
    # Settings / Health
    # ------------------------------------------------------------------

    def _open_settings(self):
        dlg = ConnectionSettingsWindow(self)
        dlg.exec()

    def _do_health_check(self):
        self._set_state(THINK)
        self.show_bubble("🔌 ヘルスチェック中...", duration=10000)
        api_client.check_health(
            on_done=self._secretary_done.emit,
            on_error=self._secretary_error.emit,
        )

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _check_notifications(self):
        if not NOTIFY_FILE.exists():
            return
        try:
            notifications = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
            if not notifications:
                return
            # Process first notification
            note = notifications.pop(0)
            msg = note.get("message", "")
            state = note.get("state", ALERT)
            if msg:
                self._set_state(state)
                self.show_bubble(msg, duration=8000, speak=note.get("speak", False))
                QTimer.singleShot(8000, lambda: self._set_state(IDLE))
            # Write back remaining
            NOTIFY_FILE.write_text(json.dumps(notifications, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # launchd check
    # ------------------------------------------------------------------

    def _check_launchd(self):
        agents = _read_launchd_agents()
        disabled = [a for a in agents if not a["enabled"]]
        if disabled:
            names = "、".join(a["label"].split(".")[-1] for a in disabled[:3])
            self.show_bubble(f"⚠️ 無効なLaunchAgent: {names}", duration=5000)

    # ------------------------------------------------------------------
    # Idle / proactive secretary
    # ------------------------------------------------------------------

    def _idle_message(self):
        """10分ごとにキャッシュ済みデータを使ってプロアクティブに話しかける"""
        if self._state != IDLE:
            return
        self._set_state(THINK)

        # キャッシュから即座に取得（ブロッキングなし）
        with _ctx_lock:
            tasks = list(_ctx_cache["tasks"])
            cal_str = _ctx_cache["cal_summary"]

        now = datetime.now()
        parts = [f"[システムコンテキスト] 現在日時: {now.strftime('%Y年%m月%d日（%A）%H:%M')}"]

        if tasks:
            today_str = now.date().isoformat()
            overdue = [t for t in tasks if t.get("due_date") and t["due_date"] < today_str]
            due_today = [t for t in tasks if t.get("due_date") == today_str]
            high = [t for t in tasks if t.get("priority") == "high"]
            if overdue:
                parts.append(f"期限切れタスク {len(overdue)}件: " + "、".join(t["title"] for t in overdue[:3]))
            elif due_today:
                parts.append(f"本日期限のタスク: " + "、".join(t["title"] for t in due_today[:3]))
            elif high:
                parts.append(f"高優先タスク {len(high)}件: " + "、".join(t["title"] for t in high[:3]))
            else:
                parts.append(f"未完了タスク {len(tasks)}件あります。")
        else:
            parts.append("現在のタスクリストは空です。")

        if cal_str:
            parts.append(f"カレンダー: {cal_str[:100]}")

        parts.append(
            "\n以上の情報をもとに、ユーザーへの短い（2〜3文）プロアクティブなコメントや"
            "リマインダーを日本語でしてください。"
        )
        api_client.call_api(
            "\n".join(parts),
            on_done=self._secretary_done.emit,
            on_error=lambda e: None,  # アイドルメッセージのエラーは無視
        )

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _startup_greeting(self):
        self._set_state(HAPPY)
        self.show_bubble("おはようございます！Elon Mascot 起動しました 🌟", duration=5000, speak=True)
        QTimer.singleShot(5000, lambda: self._set_state(IDLE))

    # ------------------------------------------------------------------
    # Tray activation
    # ------------------------------------------------------------------

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
                self._bubble.hide()
            else:
                self.show()
                self.raise_()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    # Ensure config dir exists
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName("Elon Mascot")
    app.setQuitOnLastWindowClosed(False)

    # Add APP_DIR to sys.path so integrations can be imported
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    window = MascotWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
