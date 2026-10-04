"""
conftest.py - wspolne ustawienia testow.

Testy NIE ruszaja prawdziwych danych: zmienna D2_DANE przenosi katalog danych do folderu
tymczasowego, a kazdy test dostaje swiezo rozpakowany wzorzec z sample_data/ (screenshots, cache,
ustawienia bez sekretow). posted.json, prices.json, screenshots/ i ustawienia w katalogu projektu
zostaja nietkniete. Traderie i model tez nie sa odpytywane - http_json jest atrapa.

Wzorzec odswiezysz tak: skopiuj wybrane pliki .json/.listing.json ze screenshots/ do sample_data/screenshots/.
"""
import os
import json
import shutil
import tempfile
import types
import sys
from pathlib import Path

import pytest

WZOR = Path(__file__).resolve().parent / "sample_data"

# D2_DANE musi byc ustawione PRZED importem paths - paths.DATA czyta je raz, przy imporcie.
# Jesli paths wjedzie wczesniej (np. przez wtyczke podana w -p, bo wtyczki laduja sie przed
# conftest.py), to DATA pokaze na katalog projektu i testy zapisza do PRAWDZIWYCH danych:
# ustawienia konta, klucz API w secrets/, pola w screenshots/*.listing.json. Zdarzylo sie
# 2 X 2026 - skonczylo sie nadpisanym kluczem OVH i wyczyszczonym seller_id.
# Dlatego nie "ufamy i jedziemy", tylko przerywamy caly przebieg.
if "paths" in sys.modules:
    raise RuntimeError(
        "paths zostal zaimportowany przed conftest.py - testy pisalyby po prawdziwych danych.\n"
        "Najczestsza przyczyna: wtyczka podana przez -p, ktora importuje i18n/paths/d2_web.\n"
        "Ustaw D2_DANE na katalog tymczasowy przed uruchomieniem pytest albo nie importuj\n"
        "modulow programu na poziomie wtyczki.")

DANE = Path(os.environ.setdefault("D2_DANE", tempfile.mkdtemp(prefix="d2_testy_")))

import paths  # noqa: E402  - po ustawieniu D2_DANE

if paths.DATA != DANE.resolve():
    raise RuntimeError(f"paths.DATA ({paths.DATA}) != katalog testowy ({DANE}) - przerywam, "
                       "zeby nie dotknac prawdziwych danych.")


def fresh_data():
    """Czysci katalog danych testowych i wklada tam wzorzec (sam katalog zostaje - jest biezacym)."""
    DANE.mkdir(parents=True, exist_ok=True)
    for p in DANE.iterdir():
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    for p in WZOR.iterdir():
        # dirs_exist_ok: katalogu uzywanego przez program (np. cache/) Windows nie pozwala usunac
        shutil.copytree(p, DANE / p.name, dirs_exist_ok=True) if p.is_dir() else shutil.copy2(p, DANE / p.name)


assert WZOR.is_dir(), f"brak wzorca danych: {WZOR} (zobacz docstring conftest.py)"
fresh_data()

sys.modules.setdefault("ollama", types.SimpleNamespace(Client=lambda **k: None))

import traderie_map as tm   # noqa: E402

pytest_plugins = ["nicegui.testing.user_plugin"]

PRICE_CHECK = {
    "valuedTrades": 20,
    "percentiles": {"floor": 0.5, "typical": 1, "good": 1.25, "high": 2.5},
    "runeValues": {"Ist Rune": 1, "Mal Rune": 0.5, "Gul Rune": 1.25, "Vex Rune": 2.5, "Um Rune": 0.4},
    "dateRange": {"oldest": "2026-09-20", "newest": "2026-09-29"},
}
OWN_LISTINGS = {"listings": [], "nextPage": None}       # podmien na prawdziwa odpowiedz, jesli potrzebna


KLUCZE = {"key-of-terror": "Key of Terror", "key-of-hate": "Key of Hate",
          "key-of-destruction": "Key of Destruction"}   # ceny w kluczach - uzywane w oknie ceny


def klucz_jako_przedmiot(slug: str) -> dict:
    """Minimalna definicja przedmiotu: tyle, ile potrzebuje traderie_post.parse_price."""
    wzor = json.loads((DANE / "cache" / "key-of-terror.json").read_text(encoding="utf-8"))["items"][0]
    return {**wzor, "slug": slug, "name": KLUCZE[slug], "id": "99" + str(abs(hash(slug)))[:6]}


def fake_http(url, timeout=30):
    """Atrapa API Traderie - dopasuj do tego, czego wymaga testowany kod."""
    if "seller=" in url:
        return OWN_LISTINGS if "completed=false" in url else {"listings": []}
    if "price-check" in url:
        return PRICE_CHECK
    if "search=" in url:
        return {"items": [{"name": n} for n in KLUCZE.values()]}
    slug = next((s for s in KLUCZE if f"id={s}&" in url or url.endswith("id=" + s)), None)
    if slug:
        return {"items": [klucz_jako_przedmiot(slug)]}
    return {"items": [], "listings": []}


@pytest.fixture(autouse=True)
def isolate():
    """Swieze dane i atrapa API przed kazdym testem."""
    tm.http_json = fake_http
    tm.load_auth = lambda: {"Authorization": "Bearer test.test.test"}
    fresh_data()
    os.chdir(DANE)          # d2_web robi to przy imporcie; po fresh_data() katalog jest ten sam
    yield
