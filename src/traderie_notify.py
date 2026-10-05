"""
traderie_notify.py - odczyt powiadomien z Traderie (oferty, wiadomosci).

Format odpowiedzi Traderie nie jest udokumentowany - skrypt wyciaga tekst z typowych pol
i zapamietuje, ktore powiadomienia juz pokazal (notifications_seen.json).
"""
import json
import hashlib
from pathlib import Path

import traderie_map as tm

SEEN_FILE = Path("notifications_seen.json")
URL = f"{tm.API}/notifications"
TEXT_KEYS = ("message", "text", "body", "title", "content", "description", "type")


def _text(n: dict) -> str:
    parts = []
    for k in TEXT_KEYS:
        v = n.get(k)
        if isinstance(v, str) and v.strip() and v not in parts:
            parts.append(v.strip())
    for k in ("item", "listing", "user", "sender", "from"):   # zagniezdzone: nazwa przedmiotu / uzytkownika
        v = n.get(k)
        if isinstance(v, dict):
            name = v.get("name") or v.get("username") or v.get("item_name")
            if name:
                parts.append(f"{k}: {name}")
        elif isinstance(v, str) and len(v) < 60:
            parts.append(f"{k}: {v}")
    return " | ".join(parts) or json.dumps(n, ensure_ascii=False)[:200]


def _id(n: dict) -> str:
    for k in ("id", "notification_id", "_id"):
        if n.get(k):
            return str(n[k])
    return hashlib.sha1(json.dumps(n, sort_keys=True).encode()).hexdigest()


def fetch_new() -> list:
    """Zwraca [(czas, tekst)] powiadomien, ktorych jeszcze nie pokazano."""
    data = tm.http_json(URL)
    items = data if isinstance(data, list) else (data.get("notifications") or data.get("items") or [])
    seen = set(json.loads(SEEN_FILE.read_text(encoding="utf-8"))) if SEEN_FILE.exists() else set()
    new = []
    for n in items:
        if not isinstance(n, dict):
            continue
        nid = _id(n)
        if nid in seen:
            continue
        seen.add(nid)
        when = str(n.get("created_at") or n.get("date") or n.get("updated_at") or "")[:16].replace("T", " ")
        new.append((when, _text(n)))
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    return new
