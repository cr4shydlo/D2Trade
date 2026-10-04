"""
game_source.py - definicje przedmiotow z plikow gry, gdy nie ma tokenu Traderie.

Bez tokenu nie da sie pobrac z Traderie definicji przedmiotu, a bez niej program nie
wie, jakie linie tooltipa sa statami ani jakie maja zakresy. Te same dane sa w plikach
gry na dysku - wyciaga je game_extract.py do katalogu game_data/, a ten modul podaje
je w tym samym formacie, w jakim przychodza z Traderie. Dzieki temu traderie_map,
rare_eval i d2jsp_post dzialaja bez zadnej zmiany.

Czego taka definicja NIE ma: numerow wlasciwosci Traderie. Numery sa tu wlasne (ujemne),
bo to oznaczenia z ich bazy, ktorych w plikach gry nie ma. Listing zbudowany lokalnie
jest wiec oznaczony 'local' i traderie_post.build_payload() odmawia jego wystawienia -
inaczej poszlyby na serwer wlasciwosci o zmyslonych numerach.
"""
import json

import paths
import traderie_map as tm

# Baza lezy przy danych, nie przy kodzie: jest duza, powstaje z gry konkretnego uzytkownika
# i nie wchodzi do repozytorium. paths.KEEP pilnuje, zeby czyszczenie danych jej nie usunelo.
KATALOG = paths.DATA / "game_data"
IKONY = KATALOG / "icons"
ITEMS = KATALOG / "items.json"
PROPS = KATALOG / "props.json"
META = KATALOG / "meta.json"

_baza = None        # {"items": {klucz -> wpis}, "props": {pid -> definicja}}
PIERWSZENSTWO = {"base": 0, "runes": 0, "gems": 0, "unique": 1, "set": 2, "runeword": 3}


def _wczytaj():
    """Baza wczytana leniwie. Pusta, gdy katalogu nie ma - wtedy program dziala po staremu."""
    global _baza
    if _baza is not None:
        return _baza
    _baza = {"items": {}, "props": {}, "statowe": [], "meta": {}}
    try:
        items = json.loads(ITEMS.read_text(encoding="utf-8"))
        props = json.loads(PROPS.read_text(encoding="utf-8"))
    except Exception:
        return _baza
    _baza["props"] = {p["property_id"]: p for p in props["list"]}
    _baza["statowe"] = props.get("statowe") or []
    try:
        _baza["meta"] = json.loads(META.read_text(encoding="utf-8"))
    except Exception:
        pass
    for wpis in items:
        klucz = tm.normalize(wpis.get("name") or "")
        if not klucz:
            continue
        klucze = [klucz] + [tm.normalize(a) for a in wpis.get("aliases") or []]
        # gra nazywa ten unikat "The Stone of Jordan", a w tooltipie i w mowie to "Stone of Jordan"
        klucze += [k[4:] for k in list(klucze) if k.startswith("the ")]
        for k in klucze:
            if not k:
                continue
            stary = _baza["items"].get(k)
            # przy powtorzonej nazwie wygrywa baza: "Ring" to przede wszystkim baza
            if stary and PIERWSZENSTWO.get(stary["kind"], 9) <= PIERWSZENSTWO.get(wpis["kind"], 9):
                continue
            _baza["items"][k] = wpis
    return _baza


def dostepne() -> bool:
    """Czy jest z czego czytac (uzytkownik uruchomil game_extract.py)."""
    return bool(_wczytaj()["items"])


def meta() -> dict:
    """Skad i kiedy powstala baza - do pokazania w Ustawieniach."""
    return dict(_wczytaj()["meta"])


def odswiez():
    """Zapomina wczytana baze (po ponownym wyciagnieciu danych z gry)."""
    global _baza
    _baza = None


def ikona(wpis: dict):
    """Sciezka do pliku PNG z ikona przedmiotu albo None."""
    nazwa = (wpis or {}).get("icon")
    if not nazwa:
        return None
    p = IKONY / nazwa
    return p if p.is_file() else None


def znajdz(nazwa: str):
    """Surowy wpis z game_data/items.json albo None."""
    return _wczytaj()["items"].get(tm.normalize(nazwa or ""))


def wszystkie() -> list:
    """Wszystkie przedmioty (bez powtorzen) - do zbudowania katalogu nazw w game_db."""
    widziane, out = set(), []
    for wpis in _wczytaj()["items"].values():
        if id(wpis) not in widziane:
            widziane.add(id(wpis))
            out.append(wpis)
    return out


def get_item(nazwa: str):
    """Definicja przedmiotu w formacie Traderie albo None. Zamiennik tm.get_item()."""
    wpis = znajdz(nazwa)
    if not wpis:
        return None
    baza = _wczytaj()
    # Najpierw wlasciwosci tego przedmiotu, potem wszystkie pozostale staty. Kolejnosc ma
    # znaczenie: traderie_map bierze pierwszy pasujacy szablon, a przy tym samym tekscie
    # linii lepiej trafic we wlasciwosc, ktora ten przedmiot naprawde ma.
    kolejnosc = list(wpis.get("props") or []) + baza["statowe"]
    props, widziane = [], set()
    for pid in kolejnosc:
        if pid in widziane or pid not in baza["props"]:
            continue
        widziane.add(pid)
        props.append(baza["props"][pid])
    obrazek = ikona(wpis)
    return {
        "id": "local-%s" % wpis["slug"],
        "slug": wpis["slug"],
        "name": wpis["name"],
        "type": wpis["type"],
        "description": wpis.get("desc") or "",
        "properties": props,
        "tags": wpis.get("tags") or [],
        "img": str(obrazek) if obrazek else None,
        "local": True,            # po tym poznajemy listing zbudowany bez Traderie
        "variants": None,
        "recipe": None,
        "buy_price": 0,
        "active": True,
    }
