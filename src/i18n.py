"""
i18n.py - tlumaczenie interfejsu okna.

Teksty w kodzie sa po polsku i sluza jako klucze. Plik lang/<kod>.json zawiera:
  "_name":    nazwa jezyka w menu (np. "English")
  "_font":    opcjonalnie krój pisma (np. "Malgun Gothic" dla koreanskiego)
  "strings":  pelne teksty: {"Polski tekst": "Translation"}; {0}, {1} = wstawiane wartosci
  "phrases":  fragmenty podmieniane wewnatrz dluzszych tekstow (np. "rzut: " -> "roll: ")
Brakujace tlumaczenie = tekst zostaje po polsku. Nowy jezyk: skopiuj lang/en.json jako lang/xx.json
i przetlumacz wartosci (klucze zostaw). Sprawdzenie brakow:  py -3.11 i18n.py xx
"""
import re
import sys
import json
from pathlib import Path

import paths

LANG_DIR = paths.PROGRAM / "lang"
SETTINGS = paths.DATA / "settings.json"
DEFAULT_FONT = "Segoe UI"

_lang = "pl"
_strings, _templates, _phrases = {}, [], []
_font = DEFAULT_FONT


def settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_setting(key, value):
    s = settings()
    s[key] = value
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


BASE_DIR = paths.PROGRAM
PROBLEMS = []   # pliki jezykowe, ktorych nie dalo sie wczytac (pokazywane w logu okna)


def _lang_files() -> dict:
    """{kod: plik} - pliki jezykowe z lang/ albo bezposrednio z folderu programu (np. en.json, pt-br.json)."""
    found = {}
    for folder in (BASE_DIR, LANG_DIR):                # lang/ ma pierwszenstwo (nadpisuje)
        for f in sorted(folder.glob("*.json")):
            if re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", f.stem.lower()):
                found[f.stem.lower()] = f
    return found


def _read(f: Path):
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))   # -sig: tez pliki zapisane z BOM (Notatnik)
    except Exception as e:
        PROBLEMS.append(f"{f.name}: {e}")
        return None
    if not isinstance(data, dict) or "strings" not in data:
        PROBLEMS.append(f"{f.name}: to nie jest plik jezykowy (brak sekcji 'strings')")
        return None
    return data


def languages() -> dict:
    """{kod: nazwa} - polski zawsze + znalezione pliki jezykowe."""
    out = {"pl": "Polski"}
    for code, f in _lang_files().items():
        data = _read(f)
        if data:
            out[code] = data.get("_name", code)
    return out


def load(lang: str = None):
    global _lang, _strings, _templates, _phrases, _font
    _lang = lang or settings().get("lang", "pl")
    _strings, _templates, _phrases, _font = {}, [], [], DEFAULT_FONT
    if _lang == "pl":
        return
    f = _lang_files().get(_lang)
    data = _read(f) if f else None
    if not data:
        _lang = "pl"
        return
    _font = data.get("_font") or DEFAULT_FONT
    for src, dst in (data.get("strings") or {}).items():
        if not dst:
            continue
        if re.search(r"\{\d+\}", src):
            rx = re.escape(src)
            for m in re.findall(r"\\\{(\d+)\\\}", rx):
                rx = rx.replace(r"\{%s\}" % m, r"(?P<g%s>.+?)" % m, 1)
            _templates.append((re.compile("^" + rx + "$", re.S), dst))
        else:
            _strings[src] = dst
    _templates.sort(key=lambda t: -len(t[0].pattern))
    _phrases = sorted(((k, v) for k, v in (data.get("phrases") or {}).items() if v), key=lambda kv: -len(kv[0]))


def current() -> str:
    return _lang


def font() -> str:
    return _font


def _line(s: str) -> str:
    core = s.strip()
    if not core:
        return s
    lead, trail = s[:len(s) - len(s.lstrip())], s[len(s.rstrip()):]
    if core in _strings:
        return lead + _strings[core] + trail
    for rx, dst in _templates:
        m = rx.match(core)
        if m:
            vals = {k[1:]: _line(v) for k, v in m.groupdict().items()}
            return lead + re.sub(r"\{(\d+)\}", lambda x: vals.get(x.group(1), x.group(0)), dst) + trail
    for src, dst in _phrases:
        if src in core:
            core = core.replace(src, dst)
    return lead + core + trail


def tr(s):
    """Tlumaczy tekst (takze wielolinijkowy). Nie-teksty zwraca bez zmian."""
    if _lang == "pl" or not isinstance(s, str) or not s:
        return s
    if "\n" in s:
        whole = _line(s)
        if whole != s:
            return whole
        return "\n".join(_line(x) for x in s.split("\n"))
    return _line(s)


def missing(lang: str):
    """Teksty z en.json (wzorzec), ktorych brakuje w danym jezyku."""
    ref = json.loads((LANG_DIR / "en.json").read_text(encoding="utf-8"))
    cur = json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    for sect in ("strings", "phrases"):
        for k in ref.get(sect, {}):
            if not (cur.get(sect) or {}).get(k):
                print(f"[{sect}] {k}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        missing(sys.argv[1])
    else:
        print("Uzycie: py -3.11 i18n.py <kod jezyka>   - pokazuje brakujace tlumaczenia")
