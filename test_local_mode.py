"""
Tryb lokalny: praca bez tokenu Traderie, na danych wyciagnietych z plikow gry.

Test buduje maly, sztuczny game_data/ w katalogu testowym - nie wymaga zainstalowanej gry
ani prawdziwej bazy. Sprawdzamy to, co musi dzialac bez Traderie: rozpoznanie przedmiotu,
odczyt statow z tooltipa, post d2jsp - i to, co dzialac NIE moze: wystawienie oferty.
"""
import asyncio
import json

import pytest
from nicegui.testing import User

import paths
import traderie_map as tm
import traderie_post as tp
import traderie_price as tpr
import game_source as gs
import game_db
import d2jsp_post

PIERSCIEN = "Ring"
# numery dodatnie tylko tam, gdzie kod traktuje wlasciwosc specjalnie (jak w game_extract.py)
PROPS = [
    {"property_id": 796, "id": 796, "property": "Required Level {{value}}", "type": "number",
     "required": False, "options": None, "default_value": None, "format": None},
    {"property_id": -1, "id": -1, "property": "+{{value}}% Faster Cast Rate", "type": "number",
     "required": False, "options": None, "default_value": None, "format": None},
    {"property_id": -2, "id": -2, "property": "+{{value}} to Mana", "type": "number",
     "required": False, "options": None, "default_value": None, "format": None},
    {"property_id": -3, "id": -3, "property": "All Resistances +{{value}}", "type": "number",
     "required": False, "options": None, "default_value": None, "format": None},
    {"property_id": -10, "id": -10, "property": "Platform", "type": "option",
     "required": True, "options": ["PC"], "default_value": None, "format": None},
    {"property_id": -11, "id": -11, "property": "Mode", "type": "option",
     "required": True, "options": ["softcore"], "default_value": None, "format": None},
    {"property_id": -12, "id": -12, "property": "Ladder", "type": "option",
     "required": True, "options": ["Ladder"], "default_value": None, "format": None},
    {"property_id": -13, "id": -13, "property": "Game version", "type": "option",
     "required": True, "options": ["reign of the warlock"], "default_value": None, "format": None},
    {"property_id": -14, "id": -14, "property": "Rarity", "type": "option",
     "required": True, "options": ["rare", "magic"], "default_value": None, "format": None},
]
STATOWE = [796, -1, -2, -3]
ITEMS = [
    {"kind": "base", "name": PIERSCIEN, "slug": "ring", "type": "base", "base": "rin",
     "tags": [{"tag": "Ring", "category": "Item Type"}], "levelreq": None, "asset": None,
     "aliases": [], "props": [-10, -11, -12, -13, -14], "desc": "", "icon": None},
    {"kind": "unique", "name": "The Stone of Jordan", "slug": "the-stone-of-jordan",
     "type": "uniques", "base": "rin", "tags": [{"tag": "Ring", "category": "Item Type"}],
     "levelreq": 29, "asset": None, "aliases": ["Stone of Jordan"],
     "props": [796, -1, -2], "icon": None,
     "desc": "+1 to All Skills\n+[color=Lime]20-30[/color] to Mana\nReq. Level: 29"},
]
TOOLTIP_RARE = {
    "file": "item_lokalny.png",
    "rarity_guess": "rare",
    "lines": ["CHAOS LOOP", "RING", "REQUIRED LEVEL 23", "+10% FASTER CAST RATE",
              "+15 TO MANA", "ALL RESISTANCES +8"],
}


@pytest.fixture
def lokalnie(monkeypatch):
    """Sztuczne game_data/ i brak tokenu - czyli dokladnie sytuacja nowego uzytkownika."""
    katalog = paths.DATA / "game_data"
    katalog.mkdir(parents=True, exist_ok=True)
    (katalog / "props.json").write_text(json.dumps({"list": PROPS, "statowe": STATOWE}), encoding="utf-8")
    (katalog / "items.json").write_text(json.dumps(ITEMS), encoding="utf-8")
    (katalog / "meta.json").write_text(json.dumps({"items": len(ITEMS), "created": "2026-10-04"}),
                                       encoding="utf-8")
    monkeypatch.setattr(tm, "load_auth", lambda: {})
    monkeypatch.setattr(tm, "CACHE", paths.DATA / "pusty_cache")   # cache z Traderie nie ma pomagac
    gs.odswiez()
    game_db._INDEKS = None
    yield katalog
    gs.odswiez()
    game_db._INDEKS = None


def test_tryb_lokalny_wlacza_sie_bez_tokenu(lokalnie):
    assert gs.dostepne()
    assert tm.local_only() is True
    assert tm.have_auth() is False


def test_bez_danych_z_gry_nie_ma_trybu_lokalnego(monkeypatch):
    """Sam brak tokenu nie wystarcza - bez game_data nie ma z czego czytac definicji."""
    monkeypatch.setattr(tm, "load_auth", lambda: {})
    monkeypatch.setattr(tm, "CACHE", paths.DATA / "pusty_cache")
    gs.odswiez()
    assert gs.dostepne() is False
    assert tm.local_only() is False
    assert tm.get_item(PIERSCIEN) is None


def test_cache_traderie_ma_pierwszenstwo_nad_plikami_gry(lokalnie, monkeypatch):
    """Definicja sciagnieta kiedys z Traderie jest dokladniejsza (ma prawdziwe numery
    wlasciwosci), wiec brak tokenu nie powod, zeby ja pominac."""
    monkeypatch.setattr(tm, "CACHE", paths.DATA / "cache")   # wzorzec ma tam ring.json
    it = tm.get_item(PIERSCIEN)
    assert it["name"] == PIERSCIEN and not it.get("local")


def test_definicja_ma_format_traderie(lokalnie):
    it = tm.get_item(PIERSCIEN)
    assert it["name"] == PIERSCIEN and it["local"] is True
    assert it["id"].startswith("local-")
    # baza dostaje tez wszystkie staty, bo moze sie trafic jako magic albo rare
    teksty = [p["property"] for p in it["properties"]]
    assert "+{{value}}% Faster Cast Rate" in teksty and "Rarity" in teksty
    assert len(teksty) == len(set(teksty)), "wlasciwosci nie moga sie powtarzac"


def test_alias_nazwy_dziala(lokalnie):
    """Gra nazywa ten unikat 'The Stone of Jordan', a tabela gry miala wlasny zapis."""
    for nazwa in ("The Stone of Jordan", "stone of jordan", "Stone of Jordan"):
        assert (tm.get_item(nazwa) or {}).get("name") == "The Stone of Jordan"


def test_odczyt_rarea_bez_traderie(lokalnie):
    out = tm.map_item(dict(TOOLTIP_RARE))
    assert out["name"] == PIERSCIEN and out["kind"] == "rare" and out["local"] is True
    assert not out["unmatched"], out["unmatched"]
    staty = {p["property"]: p["value"] for p in out["properties"]}
    assert staty["+{{value}}% Faster Cast Rate"] == 10
    assert staty["+{{value}} to Mana"] == 15
    assert staty["All Resistances +{{value}}"] == 8
    # pola wymagane przez listing sa na miejscu, wiec listing wyglada jak ten z Traderie
    assert staty["Rarity"] == "rare" and staty["Platform"] == tm.PLATFORM


def test_zakresy_unikatu_z_opisu(lokalnie):
    """Opis zlozony z tabel gry musi dawac te same zakresy, co opis z Traderie."""
    it = tm.get_item("The Stone of Jordan")
    zakresy, _ = tm.parse_ranges(it["description"])
    assert zakresy[tm.words("+{{value}} to Mana")] == (20, 30)
    assert tm.parse_req_level(it["description"]) == 29


def test_wystawienie_lokalnego_listingu_jest_zablokowane(lokalnie):
    out = tm.map_item(dict(TOOLTIP_RARE))
    with pytest.raises(ValueError) as e:
        tp.build_payload(out, tm.get_item(PIERSCIEN), [], False)
    assert "token" in str(e.value).lower()


def test_wycena_mowi_wprost_ze_nie_ma_cen(lokalnie, monkeypatch):
    def nie_wolno(*a, **k):
        raise AssertionError("bez tokenu nie wolno odpytywac Traderie")

    monkeypatch.setattr(tpr, "price_check", nie_wolno)
    monkeypatch.setattr(tpr, "fetch_listings", nie_wolno)
    out = tm.map_item(dict(TOOLTIP_RARE))
    res = tpr.suggest(out, tm.get_item(PIERSCIEN))
    assert res["price"] == "" and not res["levels"]
    assert "Traderie" in res["text"]


def test_post_d2jsp_z_danych_lokalnych(lokalnie):
    out = tm.map_item(dict(TOOLTIP_RARE))
    post = d2jsp_post.build_post([(out, "ist")])
    assert "Rare Ring" in post
    assert "fcr10" in post and "mana15" in post and "@8" in post


def test_katalog_nazw_korzysta_z_danych_z_gry(lokalnie):
    """game_db ma znac nazwy z gry uzytkownika, nawet gdy nie ma ich w pliku z repozytorium."""
    n, wpis = game_db.najdluzsza_nazwa(["the", "stone", "of", "jordan", "fcr", "10"])
    assert n == 4 and wpis["name"] == "The Stone of Jordan"


# ---------------- okno ----------------
async def test_ustawienia_maja_sekcje_dane_z_gry(user: User, lokalnie):
    import d2_web as W
    await user.open("/")
    W.settings_dialog()
    await asyncio.sleep(0.4)
    await user.should_see("Dane z gry")
    await user.should_see("Katalog z Diablo II: Resurrected:")
    await user.should_see("Odswiez baze")          # baza jest, wiec przycisk odswieza


async def test_pasek_boczny_mowi_zeby_wskazac_gre(user: User, monkeypatch):
    """Bez tokenu i bez danych z gry program nie rozpozna niczego - musi o tym powiedziec."""
    monkeypatch.setattr(tm, "load_auth", lambda: {})
    gs.odswiez()
    import d2_web as W
    await user.open("/")
    await user.should_see("wskaz katalog gry w Ustawieniach")


async def test_wystawianie_lokalnego_konczy_sie_komunikatem(user: User, lokalnie, monkeypatch):
    """Zamiast przerwac w polowie wystawiania, program mowi o tym przed startem."""
    import d2_web as W
    await user.open("/")
    monkeypatch.setattr(tm, "load_auth", lambda: {"Authorization": "Bearer test.test.test"})
    powiedziane = []
    monkeypatch.setattr(W, "say", lambda msg, kind="positive", **k: powiedziane.append((msg, kind)))
    iid = next(iter(W.S.order))
    it = W.S.items[iid]
    it["lst"]["local"] = True
    it["selected"], it["status"], it["price"] = True, "ready", "ist"
    await W.start_post()
    assert powiedziane and powiedziane[-1][1] == "negative"
    assert "Traderie" in powiedziane[-1][0]
