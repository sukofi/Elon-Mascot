#!/bin/bash
cd "$(dirname "$0")"

# 旧マスコットの動作確認済みvenvのPythonを使用
PYTHON="/Users/sukofi/Desktop/Elon-AI/apps/mascot/.venv/bin/python"

# 必要なパッケージ確認（requestsのみ追加インストール）
"$PYTHON" -c "import requests" 2>/dev/null || "$PYTHON" -m pip install requests -q

"$PYTHON" launch.py
