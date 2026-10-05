"""
game_db.py - katalog nazw przedmiotow z plikow gry (game_items.json).

Po co: zanim zapytamy Traderie, warto wiedziec, czy taka nazwa w ogole istnieje
w grze. quick_price probuje coraz krotszych poczatkow zapytania ("harlequin crest
def 136" -> 3 slowa, 2, 1) i kazda nietrafiona proba to osobne zapytanie do API.
Majac nazwy lokalnie, dlugosc nazwy ustalamy bez sieci i pytamy raz.

Katalog powstaje z CASC D2R (projekt d2r_assets, tools/export_item_names.py).
Brak pliku nie jest bledem - wtedy wszystko dziala jak wczesniej, tylko bez skrotu.
"""
import json
from pathlib import Path

import traderie_map as tm

PLIK = Path(__file__).with_name("game_items.json")

_INDEKS = None       # nazwa po normalize() -> {name, kind, base}
PIERWSZENSTWO = {"base": 0, "unique": 1, "set": 2, "runeword": 3}


def _wpisy() -> list:
    """Nazwy do zindeksowania: z pliku w repozytorium, a jesli uzytkownik wyciagnal dane
    z wlasnej gry - takze z nich. Ten drugi katalog jest dokladniejszy (zna nazwy dodane
    i zmienione przez moda), wiec idzie na koniec i nadpisuje."""
    out = []
    try:
        out += json.loads(PLIK.read_text(encoding="utf-8")).get("items") or []
    except Exception:
        pass
    import game_source
    for wpis in game_source.wszystkie():
        out.append({"name": wpis["name"], "kind": wpis["kind"], "base": wpis.get("base"),
                    "aliases": wpis.get("aliases")})
    return out


def indeks() -> dict:
    """Katalog wczytany leniwie. Pusty slownik, gdy nie ma ani pliku, ani danych z gry."""
    global _INDEKS
    if _INDEKS is None:
        _INDEKS = {}
        for wpis in _wpisy():
            klucz = tm.normalize(wpis.get("name") or "")
            if not klucz:
                continue
            klucze = [klucz] + [tm.normalize(a) for a in wpis.get("aliases") or []]
            # gra nazywa ten unikat "The Stone of Jordan", a wpisuje sie "stone of jordan"
            klucze += [k[4:] for k in list(klucze) if k.startswith("the ")]
            for k in klucze:
                stary = _INDEKS.get(k)
                # przy powtorzonej nazwie wygrywa baza: "Ring" to przede wszystkim baza
                if not k or (stary and PIERWSZENSTWO.get(stary["kind"], 9)
                             <= PIERWSZENSTWO.get(wpis["kind"], 9)):
                    continue
                _INDEKS[k] = wpis
    return _INDEKS


def dostepny() -> bool:
    """Czy katalog jest wczytany - jesli nie, wolajacy ma dzialac po staremu."""
    return bool(indeks())


def znajdz(nazwa: str):
    """Wpis katalogu dla nazwy albo None."""
    return indeks().get(tm.normalize(nazwa or ""))


def zna(nazwa: str) -> bool:
    return znajdz(nazwa) is not None


def najdluzsza_nazwa(slowa: list, maks: int = None):
    """Najdluzszy poczatek listy slow, ktory jest nazwa przedmiotu w grze.

    Zwraca (liczba_slow, wpis) albo (0, None). Dzieki temu z 'harlequin crest def 136'
    wychodzi od razu 'harlequin crest', bez pytania Traderie o 'harlequin crest def'.
    """
    gora = len(slowa) if maks is None else min(maks, len(slowa))
    for n in range(gora, 0, -1):
        wpis = znajdz(" ".join(slowa[:n]))
        if wpis:
            return n, wpis
    return 0, None
