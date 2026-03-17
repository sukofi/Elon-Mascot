"""
Elon-AI リモートAPI クライアント
Mac Mini の api_server.py と通信する
"""
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def call_api(message: str, on_done, on_error):
    """非同期でAPIを呼び出す。on_done(reply: str), on_error(msg: str) はメインスレッドではなく別スレッドから呼ばれる"""
    def _run():
        cfg = load_config()
        url = cfg.get("elon_api_url", "").rstrip("/") + "/chat"
        api_key = cfg.get("elon_api_key", "")
        sid = cfg.get("session_id", "mascot")
        timeout = int(cfg.get("timeout", 60))

        body = json.dumps({"message": message, "session_id": sid}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            reply = data.get("reply", "（応答なし）")
            tool_log = data.get("tool_log", [])
            if tool_log:
                tools_used = "、".join(t.get("tool", "?") for t in tool_log[:3])
                reply += f"\n🔧 {tools_used}"
            on_done(reply)
        except urllib.error.HTTPError as e:
            on_error(f"APIエラー {e.code}: {e.read().decode('utf-8', errors='replace')[:80]}")
        except urllib.error.URLError as e:
            on_error(f"接続失敗: Mac Miniに繋がりません ({e.reason})")
        except Exception as e:
            on_error(f"エラー: {e}")

    threading.Thread(target=_run, daemon=True).start()


def check_health(on_done, on_error):
    """ヘルスチェック"""
    def _run():
        cfg = load_config()
        url = cfg.get("elon_api_url", "").rstrip("/") + "/health"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            on_done(data)
        except Exception as e:
            on_error(str(e))
    threading.Thread(target=_run, daemon=True).start()
