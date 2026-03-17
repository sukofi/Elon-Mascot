"""
タイマー機能
カウントダウンタイマー。完了時にコールバックで通知。
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont


class TimerWindow(QWidget):
    """カウントダウンタイマーウィンドウ"""
    timer_done = pyqtSignal(str)  # タイマー完了時に label を emit

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("タイマー")
        self.setFixedSize(300, 220)
        self.setStyleSheet("""
            QWidget { background: #0a0a1a; color: #c0c0d0;
                      font-family: 'Hiragino Sans', sans-serif; }
            QPushButton {
                background: #1a1a30; color: #00ffcc;
                border: 1px solid #00ffcc; border-radius: 6px;
                padding: 6px 18px; font-size: 13px;
            }
            QPushButton:hover { background: #00ffcc22; }
            QPushButton:disabled { color: #444; border-color: #444; }
            QSpinBox {
                background: #10102a; color: #c0c0d0;
                border: 1px solid #333; border-radius: 4px;
                padding: 4px; font-size: 14px;
            }
        """)

        self._remaining = 0
        self._label_text = ""
        self._qt_timer = QTimer()
        self._qt_timer.timeout.connect(self._tick)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 入力行
        input_row = QHBoxLayout()
        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 99)
        self._min_spin.setValue(25)
        self._min_spin.setSuffix(" 分")
        self._min_spin.setFixedWidth(90)
        self._sec_spin = QSpinBox()
        self._sec_spin.setRange(0, 59)
        self._sec_spin.setValue(0)
        self._sec_spin.setSuffix(" 秒")
        self._sec_spin.setFixedWidth(90)
        input_row.addWidget(QLabel("時間:"))
        input_row.addWidget(self._min_spin)
        input_row.addWidget(self._sec_spin)
        input_row.addStretch()
        layout.addLayout(input_row)

        # 表示
        self._display = QLabel("25:00")
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Helvetica Neue", 38, QFont.Weight.Bold)
        self._display.setFont(font)
        self._display.setStyleSheet("color: #00ffcc;")
        layout.addWidget(self._display)

        # ボタン
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ 開始")
        self._start_btn.clicked.connect(self._start)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        layout.addLayout(btn_row)

    def _start(self):
        secs = self._min_spin.value() * 60 + self._sec_spin.value()
        if secs <= 0:
            return
        self._remaining = secs
        self._label_text = f"{self._min_spin.value()}分タイマー"
        self._update_display()
        self._qt_timer.start(1000)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

    def _stop(self):
        self._qt_timer.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _tick(self):
        self._remaining -= 1
        self._update_display()
        if self._remaining <= 0:
            self._stop()
            self.timer_done.emit(self._label_text)

    def _update_display(self):
        m, s = divmod(self._remaining, 60)
        self._display.setText(f"{m:02d}:{s:02d}")
