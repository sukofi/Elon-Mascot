"""
PyQt6起動前にQtフレームワークをctypes.CDLLでプリロードするランチャー
"""
import ctypes
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent
# 旧マスコットの動作確認済みvenvを使用
SITE = Path("/Users/sukofi/Desktop/Elon-AI/apps/mascot/.venv/lib/python3.12/site-packages")
QT = SITE / "PyQt6" / "Qt6"

_FRAMEWORKS = [
    "QtCore", "QtDBus", "QtNetwork", "QtGui", "QtWidgets",
]

for fw in _FRAMEWORKS:
    fw_path = QT / "lib" / f"{fw}.framework" / "Versions" / "A" / fw
    try:
        ctypes.CDLL(str(fw_path))
    except Exception:
        pass

_plugin = QT / "plugins" / "platforms" / "libqcocoa.dylib"
try:
    ctypes.CDLL(str(_plugin))
except Exception as e:
    print(f"Warning: could not preload cocoa plugin: {e}", file=sys.stderr)

os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(QT / "plugins" / "platforms")

sys.path.insert(0, str(SITE))
sys.path.insert(0, str(APP_DIR))
import main
main.main()
