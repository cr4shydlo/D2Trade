"""
Wyciaganie danych z plikow gry (game_casc.py + game_extract.py).

Test nie wymaga zainstalowanej gry: buduje w katalogu tymczasowym maly, ale prawdziwy
w formie zestaw tabel i tekstow D2R i przepuszcza go przez caly wyciag. Dzieki temu
sprawdzamy to, co najlatwiej zepsuc - zamiane formatow gry ('%+d%%') na szablony linii
tooltipa i skladanie opisu z zakresami, ktory potem czyta traderie_map.
"""
import json
import struct

import pytest

import game_casc as gc
import game_extract as ge
import game_source as gs
import traderie_map as tm

# ---- maly, sztuczny D2R: tylko to, czego dotyka wyciag ----
TABELE = {
    "itemtypes": [
        {"Code": "any", "ItemType": "Any"},
        {"Code": "misc", "ItemType": "Miscellaneous", "Equiv1": "any"},
        {"Code": "ring", "ItemType": "Ring", "Equiv1": "misc"},
        {"Code": "armo", "ItemType": "Any Armor", "Equiv1": "any"},
        {"Code": "helm", "ItemType": "Helm", "Equiv1": "armo"},
    ],
    "armor": [{"code": "cap", "name": "Cap", "type": "helm", "levelreq": "1"}],
    "weapons": [],
    "misc": [{"code": "rin", "name": "Ring", "type": "ring", "levelreq": "1"}],
    "properties": [
        {"code": "mana", "stat1": "maxmana", "func1": "1"},
        {"code": "fcr", "stat1": "item_fastercastrate", "func1": "1"},
        {"code": "res-all", "stat1": "fireresist", "func1": "1"},
        {"code": "sor", "stat1": "item_addclassskills", "func1": "21", "val1": "1"},
        {"code": "skilltab", "stat1": "item_addskill_tab", "func1": "10"},
        {"code": "oskill", "stat1": "item_nonclassskill", "func1": "22"},
        {"code": "str/lvl", "stat1": "item_strength_perlevel", "func1": "17"},
        {"code": "dmg%", "stat1": "", "*Tooltip": "+#% Enhanced Damage"},
    ],
    "itemstatcost": [
        {"Stat": "maxmana", "descstrpos": "ModStrMana"},
        {"Stat": "item_fastercastrate", "descstrpos": "ModStrFcr"},
        {"Stat": "fireresist", "descstrpos": "ModStrFire"},
        {"Stat": "item_addclassskills", "descstrpos": "ModStr3a"},
        {"Stat": "item_addskill_tab", "descstrpos": "StrSklTabItem1"},
        {"Stat": "item_nonclassskill", "descstrpos": "ItemModifierNonClassSkill"},
        {"Stat": "item_strength_perlevel", "descstrpos": "ModStrStr"},
    ],
    "charstats": [
        {"class": "Amazon", "StrAllSkills": "AmaAll", "StrSkillTab1": "StrSklTabItem1",
         "StrClassOnly": "AmaOnly"},
        {"class": "Expansion"},
        {"class": "Sorceress", "StrAllSkills": "SorAll", "StrSkillTab1": "StrSklTabItem4",
         "StrClassOnly": "SorOnly"},
    ],
    "skills": [{"skill": "Teleport", "charclass": "sor", "skilldesc": "teleport"}],
    "skilldesc": [{"skilldesc": "teleport", "str name": "skillname43"}],
    "uniqueitems": [
        {"index": "Unique Ring 1", "code": "rin", "lvl": "39", "lvl req": "29",
         "prop1": "mana", "min1": "20", "max1": "30",
         "prop2": "fcr", "min2": "10", "max2": "10",
         "prop3": "oskill", "par3": "Teleport", "min3": "1", "max3": "1",
         "prop4": "str/lvl", "par4": "6",
         "prop5": "res-all", "min5": "10", "max5": "20"},
        {"index": "Rings"},                      # naglowek sekcji - musi zostac pominiety
    ],
    "setitems": [{"index": "Set Ring 1", "item": "rin", "set": "Test Set", "lvl req": "9",
                  "prop1": "mana", "min1": "5", "max1": "5"}],
    "runes": [{"Name": "Runeword1", "*Rune Name": "Hustle (armor)", "Rune1": "r01", "Rune2": "r02",
               "itype1": "ring", "complete": "1",
               "T1Code1": "fcr", "T1Min1": "15", "T1Max1": "15"}],
    "magicprefix": [{"Name": "Fine", "mod1code": "fcr", "mod1min": "5", "mod1max": "10"},
                    {"Name": "Magus", "mod1code": "sor", "mod1min": "1", "mod1max": "2"},
                    {"Name": "Spear", "mod1code": "skilltab", "mod1param": "0",
                     "mod1min": "1", "mod1max": "1"}],
    "magicsuffix": [{"Name": "of Mana", "mod1code": "mana", "mod1min": "10", "mod1max": "20"}],
    "automagic": [],
}
TEKSTY = {
    "item-modifiers": {
        "ModStrMana": "%+d to Mana",
        "ModStrFcr": "%+d%% Faster Cast Rate",
        "ModStrFire": "Fire Resist %+d%%",
        "ModStrStr": "%+d to Strength",
        "ModStr3a": "%+d to Amazon Skill Levels",
        "StrSklTabItem1": "%+d to Javelin and Spear Skills",
        "StrSklTabItem4": "%+d to Fire Skills",
        "ItemModifierNonClassSkill": "%+d to %s",
        "AmaAll": "%+d to Amazon Skill Levels",
        "SorAll": "%+d to Sorceress Skill Levels",
        "AmaOnly": "(Amazon Only)",
        "SorOnly": "(Sorceress Only)",
        "strModAllResistances": "All Resistances %+d",
        "Moditem2allattrib": "%+d to all Attributes",
        "ModStre9c": "(Based on Character Level)",
    },
    "item-names": {"rin": "Ring", "cap": "Cap", "Unique Ring 1": "The Stone of Jordan",
                   "Set Ring 1": "Test Ring"},
    "item-runes": {"Runeword1": "Hysteria"},
    "skills": {"skillname43": "Teleport"},
}


def zapisz_tabele(katalog, nazwa, wiersze):
    """Lista slownikow -> plik gry rozdzielany tabulatorami (naglowek z sumy kluczy)."""
    kolumny = []
    for w in wiersze:
        for k in w:
            if k not in kolumny:
                kolumny.append(k)
    kolumny = kolumny or ["code"]
    linie = ["\t".join(kolumny)]
    for w in wiersze:
        linie.append("\t".join(str(w.get(k, "")) for k in kolumny))
    (katalog / (nazwa + ".txt")).write_text("\r\n".join(linie) + "\r\n", encoding="utf-8")


def zbuduj_sztuczna_gre(katalog):
    """Zapisuje w katalogu zestaw tabel i tekstow udajacy wypakowane pliki D2R.

    Osobna funkcja, a nie tylko fikstura, bo korzysta z niej takze test okna
    (test_local_mode) - przycisk 'Wyciagnij dane z gry' trzeba przetestowac na czyms,
    a nikt nie ma gwarancji, ze ma zainstalowana gre.
    """
    excel = katalog / "data" / "global" / "excel"
    stringi = katalog / "data" / "local" / "lng" / "strings"
    excel.mkdir(parents=True, exist_ok=True)
    stringi.mkdir(parents=True, exist_ok=True)
    for nazwa, wiersze in TABELE.items():
        zapisz_tabele(excel, nazwa, wiersze)
    for nazwa, pary in TEKSTY.items():
        dane = [{"id": i, "Key": k, "enUS": v} for i, (k, v) in enumerate(pary.items())]
        (stringi / (nazwa + ".json")).write_text(json.dumps(dane), encoding="utf-8")
    return katalog


@pytest.fixture
def gra(tmp_path):
    """Katalog udajacy wypakowane pliki gry."""
    return zbuduj_sztuczna_gre(tmp_path)


@pytest.fixture
def baza(gra):
    """Uruchomiony wyciag: zwraca (items, props) z game_data/."""
    assert ge.main(["game_extract.py", str(gra)]) == 0
    items = json.loads((ge.KATALOG / "items.json").read_text(encoding="utf-8"))
    props = json.loads((ge.KATALOG / "props.json").read_text(encoding="utf-8"))
    gs.odswiez()
    yield items, props
    gs.odswiez()


# ---------------- czytanie plikow gry ----------------
def test_tabela_czyta_naglowek_i_puste_pola():
    dane = b"code\tname\ttype\r\nrin\tRing\tring\r\n\r\ncap\tCap\r\n"
    wiersze = gc.tabela(dane)
    assert len(wiersze) == 2                       # pusta linia nie jest wierszem
    assert wiersze[0] == {"code": "rin", "name": "Ring", "type": "ring"}
    assert wiersze[1]["type"] == ""                # brakujace kolumny dopelniane


def test_otworz_rozpoznaje_wypakowany_katalog(gra):
    zrodlo = gc.otworz(gra)
    assert isinstance(zrodlo, gc.Katalog)
    with zrodlo as z:
        assert z.ma("data/global/excel/misc.txt")
        assert "data/global/excel/misc.txt" in z.lista("data/global/excel")


def test_otworz_mowi_wprost_czego_brakuje(tmp_path):
    with pytest.raises(gc.BrakZrodla) as e:
        gc.otworz(tmp_path)
    assert "Data" in str(e.value)
    with pytest.raises(gc.BrakZrodla):
        gc.otworz(tmp_path / "nie-ma-takiego")


def test_ikona_sprite_na_png():
    szer, wys = 2, 2
    piksele = bytes([0, 0, 0, 0] + [255, 0, 0, 255] + [0, 0, 0, 0] + [0, 0, 0, 0])
    naglowek = bytearray(gc.SPRITE_HEAD)
    naglowek[0:4] = gc.SPRITE_MAGIC
    struct.pack_into("<II", naglowek, 8, szer, wys)
    struct.pack_into("<I", naglowek, 32, len(piksele))
    png = gc.sprite_na_png(bytes(naglowek) + piksele)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError):
        gc.sprite_na_png(b"NIE" + bytes(60))


# ---------------- zamiana formatow gry na szablony ----------------
@pytest.mark.parametrize("wejscie,oczekiwane", [
    ("%+d to Mana", "+{{value}} to Mana"),
    ("%+d%% Faster Cast Rate", "+{{value}}% Faster Cast Rate"),
    ("Fire Resist %+d%%", "Fire Resist +{{value}}%"),
    ("%d%% Life stolen per hit", "{{value}}% Life stolen per hit"),
    ("Indestructible", "Indestructible"),
])
def test_na_szablon(wejscie, oczekiwane):
    assert ge.na_szablon(wejscie)[0] == oczekiwane


def test_na_szablon_typ_i_kolejne_liczby():
    assert ge.na_szablon("%+d to Mana")[1] == "number"
    assert ge.na_szablon("Indestructible")[1] == "bool"
    # druga i trzecia liczba dostaja wlasne nazwy, zeby regex mial osobne grupy
    szablon, _ = ge.na_szablon("Level %d %s (%d/%d Charges)", param="Ice Blast")
    assert szablon == "Level {{value}} Ice Blast ({{v2}}/{{v3}} Charges)"


def test_na_szablon_bez_wartosci_dla_s():
    """Bez parametru '%s' nie da sie uzupelnic - lepiej nie tworzyc kalekiego szablonu."""
    assert ge.na_szablon("%+d to %s") == (None, None)


@pytest.mark.parametrize("param,zakres", [(12, (1, 148)), (6, (0, 74)), (8, (1, 99))])
def test_zakres_per_poziom(param, zakres):
    """Wartosci sprawdzone na opisach z Traderie: Harlequin Crest ma '+1-148 To Life'
    (param 12), Enigma '+0-74 To Strength' (param 6) i '+1-99% MF' (param 8)."""
    assert ge.zakres_per_poziom(param) == zakres
    assert ge.zakres_per_poziom(None) == (None, None)


def test_linia_opisu_czytelna_dla_parsera():
    """Zakres musi wrocic z traderie_map.parse_ranges - inaczej stat nie trafi do oferty."""
    linia = ge.linia_opisu("+{{value}} to Mana", 20, 30)
    zakresy, _ = tm.parse_ranges(linia)
    assert zakresy[tm.words("+{{value}} to Mana")] == (20, 30)
    assert ge.linia_opisu("+{{value}} to Mana", 5, 5) == "+5 to Mana"


# ---------------- caly wyciag ----------------
def test_wyciag_sklada_wszystkie_rodzaje(baza):
    items, _ = baza
    po_nazwie = {i["name"]: i for i in items}
    assert set(po_nazwie) == {"Cap", "Ring", "The Stone of Jordan", "Test Ring", "Hysteria"}
    assert po_nazwie["Ring"]["kind"] == "base"
    assert po_nazwie["The Stone of Jordan"]["kind"] == "unique"
    assert po_nazwie["Hysteria"]["kind"] == "runeword"
    assert po_nazwie["Hysteria"]["runes"] == ["r01", "r02"]


def test_nazwy_bierzemy_z_tekstow_gry(baza):
    """Kolumna 'index'/'Name' to klucz wewnetrzny; gracz widzi tekst z plikow jezykowych."""
    items, _ = baza
    soj = next(i for i in items if i["name"] == "The Stone of Jordan")
    assert "Unique Ring 1" in soj["aliases"]
    hysteria = next(i for i in items if i["name"] == "Hysteria")
    assert "Hustle (armor)" in hysteria["aliases"]


def test_tag_typu_jest_najbardziej_szczegolowy(baza):
    items, _ = baza
    tagi = {i["name"]: [t["tag"] for t in i["tags"]] for i in items}
    assert tagi["Ring"] == ["Ring"]
    assert tagi["Cap"] == ["Helm"]
    assert tagi["The Stone of Jordan"] == ["Ring"]      # tag bierze sie z bazy unikatu


def test_szablony_trudnych_statow(baza):
    """Te cztery przypadki zepsuly sie w trakcie pracy, wiec maja wlasny test."""
    _, props = baza
    teksty = {p["property"] for p in props["list"]}
    # drzewko: tekst gry jest JUZ pelna linia, wiec nie wolno dokladac drugiego '+X to'
    assert "+{{value}} to Javelin and Spear Skills (Amazon Only)" in teksty
    assert not any(t.startswith("+{{value}} to +{{") for t in teksty)
    # umiejetnosci klasy: opis w grze dotyczy pierwszej klasy, val wskazuje wlasciwa
    assert "+{{value}} to Sorceress Skill Levels" in teksty
    # staty zbiorcze: jedna linia, nie cztery odpornosci
    assert "All Resistances +{{value}}" in teksty
    # stat zalezny od poziomu postaci to osobna wlasciwosc
    assert "+{{value}} to Strength (Based on Character Level)" in teksty
    # '%s' uzupelnione nazwa umiejetnosci z parametru
    assert "+{{value}} to Teleport" in teksty


def test_opis_unikatu_ma_zakresy_i_poziom(baza):
    items, _ = baza
    soj = next(i for i in items if i["name"] == "The Stone of Jordan")
    zakresy, _ = tm.parse_ranges(soj["desc"])
    assert zakresy[tm.words("+{{value}} to Mana")] == (20, 30)
    assert tm.parse_req_level(soj["desc"]) == 29
    assert "+10% Faster Cast Rate" in soj["desc"]       # stala wartosc bez zakresu


def test_baza_dostaje_rzadkosc_a_unikat_nie(baza):
    """Rarity jest polem wymaganym; na unikacie nie ma czego w nim ustawic, wiec go nie ma."""
    _, props = baza
    po_pid = {p["property_id"]: p for p in props["list"]}
    ring = gs.get_item("Ring")
    soj = gs.get_item("The Stone of Jordan")
    assert "Rarity" in {p["property"] for p in ring["properties"]}
    assert "Rarity" not in {p["property"] for p in soj["properties"]}
    assert all(po_pid[pid]["required"] is False for pid in props["statowe"])


def test_meta_mowi_skad_sa_dane(gra, baza):
    """Okno pokazuje te dane w Ustawieniach, zeby bylo widac, z czego baza powstala."""
    items, _ = baza
    meta = json.loads((ge.KATALOG / "meta.json").read_text(encoding="utf-8"))
    assert meta["items"] == len(items)
    assert meta["source"] == str(gra) and meta["kind"] == gc.Katalog.etykieta
    assert gs.meta()["items"] == len(items)
