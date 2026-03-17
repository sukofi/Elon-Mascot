"""
Google Calendar 連携
google-auth + google-api-python-client
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta


def _get_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8")).get("gcal", {})
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _get_config()
    if not cfg.get("enabled", False):
        return False
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        return True
    except ImportError:
        return False


def _get_service():
    cfg = _get_config()
    token_path = Path(cfg.get("token_path", "~/.config/elon-mascot/gcal_token.json")).expanduser()
    creds_path = Path(cfg.get("credentials_path", "~/.config/elon-mascot/gcal_credentials.json")).expanduser()
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def get_events(days: int = 7) -> list:
    """今後 days 日間のイベントを取得"""
    if not is_enabled():
        return []
    try:
        service = _get_service()
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for e in result.get("items", []):
            start = e.get("start", {})
            dt_str = start.get("dateTime") or start.get("date", "")
            events.append({
                "id": e.get("id", ""),
                "title": e.get("summary", "（無題）"),
                "start": dt_str,
                "location": e.get("location", ""),
            })
        return events
    except Exception:
        return []


def get_summary(days: int = 7) -> str:
    """イベント一覧を文字列で返す"""
    events = get_events(days)
    if not events:
        return "予定なし"
    lines = []
    for e in events:
        try:
            if "T" in e["start"]:
                dt = datetime.fromisoformat(e["start"]).strftime("%m/%d %H:%M")
            else:
                dt = e["start"]
        except Exception:
            dt = e["start"]
        lines.append(f"  {dt} — {e['title']}")
    return "\n".join(lines)
