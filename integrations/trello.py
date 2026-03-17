"""
Trello 連携
REST API (API Key + Token)
ボード内のリストとカードを取得・追加する
"""
from __future__ import annotations
import json
from pathlib import Path

try:
    import urllib.request
    import urllib.parse
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

_BASE_URL = "https://api.trello.com/1"


def _get_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8")).get("trello", {})
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _get_config()
    return (
        cfg.get("enabled", False)
        and bool(cfg.get("api_key"))
        and bool(cfg.get("token"))
    )


def _auth() -> dict:
    cfg = _get_config()
    return {"key": cfg.get("api_key", ""), "token": cfg.get("token", "")}


def _get(path: str, params: dict | None = None) -> list | dict:
    p = {**_auth(), **(params or {})}
    qs = urllib.parse.urlencode(p)
    url = f"{_BASE_URL}{path}?{qs}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path: str, params: dict) -> dict:
    p = {**_auth(), **params}
    qs = urllib.parse.urlencode(p)
    url = f"{_BASE_URL}{path}?{qs}"
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_lists_map(board_id: str) -> dict[str, str]:
    """list_id -> list_name のマップを返す"""
    try:
        lists = _get(f"/boards/{board_id}/lists", {"fields": "name"})
        return {l["id"]: l["name"] for l in lists}
    except Exception:
        return {}


def get_cards() -> list:
    """
    ボードのカードを取得。
    - exclude_lists に含まれるリストのカードは除外
    - my_lists に含まれるリストは詳細表示用フラグを立てる
    返値: [{id, title, priority, due_date, list_name, is_mine}, ...]
    """
    if not is_enabled():
        return []
    cfg = _get_config()
    board_id = cfg.get("board_id", "")
    if not board_id:
        return []

    exclude = {s.strip() for s in cfg.get("exclude_lists", "").split(",") if s.strip()}
    my_lists = {s.strip() for s in cfg.get("my_lists", "").split(",") if s.strip()}

    try:
        lists_map = _get_lists_map(board_id)
        cards_raw = _get(
            f"/boards/{board_id}/cards",
            {"fields": "name,idList,due,labels,closed"},
        )
        cards = []
        for c in cards_raw:
            if c.get("closed"):
                continue
            list_name = lists_map.get(c.get("idList", ""), "")
            if list_name in exclude:
                continue

            labels = [l.get("name", "") for l in c.get("labels", [])]
            label_str = " ".join(labels).lower()
            if "high" in label_str or "urgent" in label_str or "緊急" in label_str:
                priority = "high"
            elif "low" in label_str:
                priority = "low"
            else:
                priority = "normal"

            due = c.get("due", "")
            due_date = due[:10] if due else None

            cards.append({
                "id": c["id"],
                "title": c["name"],
                "priority": priority,
                "due_date": due_date,
                "list_name": list_name,
                "list_id": c.get("idList", ""),
                "is_mine": list_name in my_lists,
            })
        return cards
    except Exception:
        return []


def get_summary() -> str:
    """
    マスコット用サマリ文字列を返す。
    - my_lists のカードは個別表示
    - それ以外のリストは件数のみ
    """
    if not is_enabled():
        return ""
    cards = get_cards()
    if not cards:
        return "Trelloカードなし"

    mine = [c for c in cards if c["is_mine"]]
    others = [c for c in cards if not c["is_mine"]]

    lines = []
    if mine:
        lines.append("【自分のタスク】")
        p_map = {"high": "🔴", "normal": "🟡", "low": "🟢"}
        for c in mine[:10]:
            p = p_map.get(c["priority"], "🟡")
            due = f" 〆{c['due_date']}" if c["due_date"] else ""
            lines.append(f"  {p} [{c['list_name']}] {c['title']}{due}")

    # その他リストを件数集計
    if others:
        from collections import Counter
        counts = Counter(c["list_name"] for c in others)
        other_str = "、".join(f"{name}:{n}件" for name, n in counts.items())
        lines.append(f"【その他】{other_str}")

    return "\n".join(lines)


def add_card(title: str, list_name: str | None = None, due_date: str | None = None) -> dict | None:
    """
    カードを追加。
    list_name 未指定時は my_lists の最初のリスト、それもなければボードの最初のリストに追加。
    """
    if not is_enabled():
        return None
    cfg = _get_config()
    board_id = cfg.get("board_id", "")
    if not board_id:
        return None

    try:
        lists_map = _get_lists_map(board_id)
        name_to_id = {v: k for k, v in lists_map.items()}

        # ターゲットリストを解決
        target_id = None
        if list_name and list_name in name_to_id:
            target_id = name_to_id[list_name]
        else:
            my_lists_cfg = cfg.get("my_lists", "")
            for ml in my_lists_cfg.split(","):
                ml = ml.strip()
                if ml in name_to_id:
                    target_id = name_to_id[ml]
                    break
        if not target_id:
            target_id = list(lists_map.keys())[0] if lists_map else None
        if not target_id:
            return None

        params = {"name": title, "idList": target_id}
        if due_date:
            params["due"] = f"{due_date}T00:00:00.000Z"
        data = _post("/cards", params)
        return {"id": data["id"], "title": data["name"], "due_date": due_date, "list_id": target_id}
    except Exception:
        return None
