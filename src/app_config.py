"""
app_config.py - ustawienia programu: ID konta Traderie, token, platforma/tryb/ladder/wersja gry.

Ustawienia (bez sekretow) -> settings.json; token Traderie -> traderie_auth.txt,
klucz API modelu -> plik wskazany przez llm_key_file (domyslnie api_OVH.txt).
apply() wczytuje je i podmienia wartosci w modulach, wiec dziala to i w oknie, i w konsoli.
"""
import re
import json
import base64
from datetime import datetime

import i18n
import llm
import traderie_map as tm
import traderie_sync

FIELDS = {  # klucz w settings.json -> (modul, atrybut)
    "seller_id": (traderie_sync, "SELLER_ID"),
    "platform": (tm, "PLATFORM"),
    "mode": (tm, "MODE"),
    "ladder": (tm, "LADDER"),
    "game_version": (tm, "GAME_VERSION"),
}
LLM_FIELDS = ["llm_provider", "llm_model", "llm_model_cloud", "llm_url", "llm_key_file"]
OPTIONS = {
    "llm_provider": ["ollama", "openai"],
    "platform": ["PC", "playstation", "xbox", "switch"],
    "mode": ["softcore", "hardcore"],
    "ladder": ["Ladder", "Non Ladder"],
    "game_version": ["reign of the warlock", "lord of destruction", "classic (base game)"],
}


def apply():
    s = i18n.settings()
    for key, (mod, attr) in FIELDS.items():
        if s.get(key):
            setattr(mod, attr, s[key])
    tm._AUTH = None            # wymus ponowne wczytanie tokenu


def current() -> dict:
    out = {key: getattr(mod, attr) for key, (mod, attr) in FIELDS.items()}
    out.update({k: llm.cfg(k) for k in LLM_FIELDS})
    out["token"] = (tm.load_auth().get("Authorization") or "")
    out["llm_key"] = llm.api_key()          # z pliku; w oknie pokazywany jak token - ukryty
    return out


def normalize_token(raw: str) -> str:
    """'Authorization: Bearer x', 'Bearer x', 'x' -> 'Bearer x' (bez spacji i przejsc do nowej linii)."""
    t = re.sub(r"\s+", " ", raw or "").strip()
    t = re.sub(r"^authorization\s*:?\s*", "", t, flags=re.I)
    t = re.sub(r"^bearer\s+", "", t, flags=re.I).replace(" ", "")
    return f"Bearer {t}" if t else ""


def token_problem(token: str):
    """Opis problemu z tokenem albo None."""
    raw = token.replace("Bearer ", "")
    if not raw:
        return "pusty token"
    if "\u2026" in raw or raw.endswith("..."):
        return "token jest uciety (wielokropek) - skopiuj go z widoku Nieprzetworzone"
    if raw.count(".") != 2:
        return "to nie wyglada na token JWT (powinien miec 3 czesci rozdzielone kropkami)"
    return None


def token_info(token: str) -> dict:
    """Odczyt danych zapisanych w tokenie JWT (bez weryfikacji podpisu): wygasniecie i ID uzytkownika."""
    try:
        part = token.replace("Bearer ", "").split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}
    info = {}
    if isinstance(data.get("exp"), (int, float)):
        info["expires"] = datetime.fromtimestamp(data["exp"])
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    for k in ("id", "userId", "user_id", "uid", "sub"):
        v = data.get(k) or user.get(k)
        if v and str(v).isdigit():
            info["user_id"] = str(v)
            break
    return info


def save(values: dict):
    s = i18n.settings()
    for key in LLM_FIELDS:
        if values.get(key) is not None:
            s[key] = values[key].strip()
    for key in FIELDS:
        if values.get(key) is not None:
            s[key] = values[key].strip()
    i18n.SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    token = normalize_token(values.get("token", ""))
    if token:
        keep = []
        if tm.AUTH_FILE.exists():   # inne naglowki (np. Cookie) zostawiamy
            keep = [l for l in tm.AUTH_FILE.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.lower().startswith("authorization")]
        tm.AUTH_FILE.write_text("\n".join([f"Authorization: {token}"] + keep) + "\n", encoding="utf-8")
    llm.save_api_key(values.get("llm_key", ""), values.get("llm_key_file", ""))
    apply()


def test_connection():
    """(ok, komunikat) - pobiera aktywne oferty z obecnymi ustawieniami."""
    try:
        active = traderie_sync.own_listings(completed=False)
    except tm.SessionExpired:
        return False, "token wygasl albo jest nieprawidlowy (Unauthorized jwt)"
    except Exception as e:
        return False, str(e)
    return True, f"polaczenie dziala - aktywnych ofert: {len(active)}"
