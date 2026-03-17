"""
TickTick 連携
公開 iCal フィード（webcal://）から予定・タスクを取得する
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from datetime import datetime, date

try:
    import urllib.request
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False


def _get_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8")).get("ticktick", {})
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _get_config()
    return cfg.get("enabled", False) and bool(cfg.get("ical_url", ""))


def _fetch_ical() -> str:
    """iCal フィードを取得してテキストを返す"""
    cfg = _get_config()
    url = cfg.get("ical_url", "").replace("webcal://", "https://")
    if not url:
        return ""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _parse_ical_value(line: str) -> str:
    """SUMMARY;LANGUAGE=ja:タイトル → タイトル"""
    return line.split(":", 1)[-1].strip() if ":" in line else line.strip()


def _parse_ical_date(val: str) -> str | None:
    """DTSTART;VALUE=DATE:20260314 または DTSTART:20260314T000000Z → YYYY-MM-DD"""
    val = val.split(":", 1)[-1].strip()
    try:
        if "T" in val:
            return datetime.strptime(val[:8], "%Y%m%d").date().isoformat()
        else:
            return datetime.strptime(val[:8], "%Y%m%d").date().isoformat()
    except Exception:
        return None


def get_tasks() -> list:
    """
    TickTick の iCal フィードから予定をタスクとして取得する。
    TickTick の公開 iCal は VTODO ではなく VEVENT で出力されるため、
    VEVENT のうち今日以降・90日以内のものをタスクとして扱う。
    """
    if not is_enabled():
        return []
    raw = _fetch_ical()
    if not raw:
        return []

    today = date.today()
    tasks = []

    blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.DOTALL)
    for block in blocks:
        lines = block.strip().splitlines()
        props: dict[str, str] = {}
        for line in lines:
            if line.startswith(" ") or line.startswith("\t"):
                last_key = list(props.keys())[-1] if props else None
                if last_key:
                    props[last_key] += line[1:]
            elif ":" in line:
                key = line.split(":")[0].split(";")[0].upper()
                props[key] = _parse_ical_value(line)

        title = props.get("SUMMARY", "").strip()
        if not title:
            continue

        start_line = next((l for l in lines if l.upper().startswith("DTSTART")), None)
        due_date = _parse_ical_date(start_line) if start_line else None

        # 過去・90日以上先はスキップ
        if due_date:
            try:
                d = date.fromisoformat(due_date)
                if d < today or (d - today).days > 90:
                    continue
            except Exception:
                pass

        tasks.append({
            "id": props.get("UID", ""),
            "title": title,
            "priority": "normal",
            "due_date": due_date,
        })

    tasks.sort(key=lambda t: t["due_date"] or "9999-99-99")
    return tasks


def get_events(days: int = 7) -> list:
    """VEVENT コンポーネント（カレンダーイベント）を取得"""
    if not is_enabled():
        return []
    raw = _fetch_ical()
    if not raw:
        return []

    events = []
    today = date.today().isoformat()

    blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.DOTALL)
    for block in blocks:
        lines = block.strip().splitlines()
        props: dict[str, str] = {}
        for line in lines:
            if line.startswith(" ") or line.startswith("\t"):
                last_key = list(props.keys())[-1] if props else None
                if last_key:
                    props[last_key] += line[1:]
            elif ":" in line:
                key = line.split(":")[0].split(";")[0].upper()
                props[key] = _parse_ical_value(line)

        start_line = next((l for l in lines if l.startswith("DTSTART")), None)
        start_date = _parse_ical_date(start_line) if start_line else None
        if not start_date or start_date < today:
            continue

        title = props.get("SUMMARY", "").strip()
        if not title:
            continue

        events.append({
            "title": title,
            "start": start_date,
        })

    events.sort(key=lambda e: e["start"])
    return events[:days * 3]  # 概算で上限
