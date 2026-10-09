"""Dopasowanie do Traderie: magic/rare nie moze dostawac ostrzezen z tabeli afiksow bazy."""
import json
from pathlib import Path

import traderie_map as tm


def ocr(stem):
    return json.loads(Path(f"screenshots/{stem}.json").read_text(encoding="utf-8"))


def test_magic_bez_falszywych_ostrzezen():
    """Opis bazy w Traderie to tabela WSZYSTKICH afiksow - nie staty tego egzemplarza.

    Wczesniej Small Charm 'ruby ... of strength' dostawal kilkanascie ostrzezen
    ('oczekiwano stalej wartosci 3', 'nie odczytano zmiennego statu: & ar| dmg...') i ladowal
    w 'do sprawdzenia', mimo ze odczyt byl poprawny.
    """
    for stem in ("item_20261001_174324_164",      # Small Charm: +2 str, fire res 11
                 "item_20261001_174317_634",      # Grand Charm: psn res 29
                 "item_20261001_175615_369",      # Amulet: +3 cold skills, 34 MF
                 "item_20261001_190150_936"):     # Jewel: 15 IAS
        res = tm.map_item(ocr(stem))
        print("%-14s %-6s ostrzezenia: %s" % (res.get("name"), res.get("rarity"), res["warnings"]))
        assert res["rarity"] in ("magic", "rare")
        assert res["warnings"] == []
        assert not res.get("needs_review")
        assert res["listing"]


def test_unikat_nadal_pilnuje_zakresow():
    """Przy unikatach opis dotyczy tego przedmiotu, wiec walidacja zakresow musi zostac."""
    res = tm.map_item(ocr("item_20260930_163823_092"))     # Skin of the Vipermagi
    print(res["name"], "| ostrzezenia:", res["warnings"])
    assert res.get("kind") == "unique" and not res.get("rarity")
    # podkrecamy jeden stat poza zakres (Vipermagi ma 'ALL RESISTANCES +20-35') - program musi to zglosic
    psute = ocr("item_20260930_163823_092")
    psute["lines"] = [l.replace("ALL RESISTANCES +24", "ALL RESISTANCES +99") for l in psute["lines"]]
    assert "ALL RESISTANCES +99" in psute["lines"], "zmienil sie odczyt wzorcowy - popraw test"
    zle = tm.map_item(psute)
    print("po podmianie:", zle["warnings"])
    assert any("poza zakresem" in w for w in zle["warnings"])


def test_stat_bez_liczby_w_tooltipie():
    """'Monster Lightning Immunity is Sundered' to na Traderie pole liczbowe, a w grze tylko napis -
    bierzemy wartosc domyslna (300) zamiast zostawiac linie jako niedopasowana."""
    res = tm.map_item(ocr("item_20261001_174405_095"))      # Renewed Crack of the Heavens
    sunder = [p for p in res["properties"] if "Sundered" in p["property"]]
    print(res["name"], "->", [(p["property"], p["value"]) for p in sunder])
    assert sunder and sunder[0]["value"] == 300
    assert not [u for u in res["unmatched"] if "SUNDER" in u.upper()]


def test_etykieta_nie_zjada_dluzszej_linii():
    """Opcjonalna wartosc nie moze zamienic 'Defense per Level 2' w samo 'Defense'."""
    p = {"property": "Defense", "type": "number", "default_value": 1, "format": {}}
    rx = tm.template_regex(p)
    print("Defense: 279 ->", bool(rx.match(tm.normalize("DEFENSE: 279"))),
          "| defense per level 2 ->", bool(rx.match(tm.normalize("DEFENSE PER LEVEL 2"))))
    assert rx.match(tm.normalize("DEFENSE: 279")).group("value") == "279"
    assert rx.match(tm.normalize("DEFENSE")) is not None          # sam napis = wartosc domyslna
    assert rx.match(tm.normalize("DEFENSE PER LEVEL 2")) is None


def test_stat_ktorego_traderie_nie_ma_zostaje_zgloszony():
    """Craftowany Ring ma 'Regenerate Mana 9%', a definicja Ring w Traderie nie ma takiego pola -
    linia musi zostac w 'unmatched', zeby okno moglo o niej powiedziec."""
    res = tm.map_item(ocr("item_20261001_174332_096"))
    print(res["name"], "| niedopasowane:", res["unmatched"])
    assert any("Regenerate Mana" in u for u in res["unmatched"])
    item = tm.get_item(res["name"])
    assert not [p for p in item["properties"] if "regenerate mana" in p["property"].lower()]


def test_wywrotka_na_jednym_screenie_nie_zabiera_reszty(tmp_path, monkeypatch):
    """Blad przy jednym przedmiocie nie moze skasowac z listy wszystkich nastepnych.

    Okno buduje liste wylacznie z plikow .listing.json, wiec wyjatek przerywajacy petle
    run() znaczyl, ze kazdy nastepny screen - choc odczytany - byl w oknie niewidoczny
    (tak zniknelo 11 odczytow przy zmianie pola 'property' w API Traderie).
    """
    zly, dobry = "item_20261001_174324_164", "item_20261001_174317_634"
    folder = tmp_path / "screenshots"
    folder.mkdir()
    for stem in (zly, dobry):
        (folder / f"{stem}.json").write_text(json.dumps(ocr(stem)), encoding="utf-8")

    oryg = tm.map_item
    monkeypatch.setattr(tm, "map_item",
                        lambda o: (_ for _ in ()).throw(KeyError("property"))
                        if zly in o["file"] else oryg(o))
    tm.run(folder, verbose=False)

    padl = json.loads((folder / f"{zly}.listing.json").read_text(encoding="utf-8"))
    print("padl:", padl.get("ocr_name"), "|", padl["warnings"])
    assert padl["needs_review"] and any("blad programu" in w for w in padl["warnings"])
    assert padl["ocr_name"]        # bez nazwy nie dalo by sie go znalezc na liscie

    dalszy = json.loads((folder / f"{dobry}.listing.json").read_text(encoding="utf-8"))
    print("nastepny:", dalszy.get("name"), "| staty:", len(dalszy["properties"]))
    assert dalszy["listing"] and not dalszy["needs_review"]


def test_wywrotka_nie_kasuje_udanego_dopasowania(tmp_path, monkeypatch):
    """Gdy poprzedni odczyt sie udal, zostaje - lepsze stare staty niz zadne."""
    stem = "item_20261001_174324_164"
    folder = tmp_path / "screenshots"
    folder.mkdir()
    (folder / f"{stem}.json").write_text(json.dumps(ocr(stem)), encoding="utf-8")
    tm.run(folder, verbose=False)
    przed = json.loads((folder / f"{stem}.listing.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(tm, "map_item", lambda o: (_ for _ in ()).throw(KeyError("property")))
    tm.run(folder, verbose=False)
    po = json.loads((folder / f"{stem}.listing.json").read_text(encoding="utf-8"))
    print(f"staty przed: {len(przed['properties'])} -> po wywrotce: {len(po['properties'])}")
    assert po["listing"] == przed["listing"] and po["name"] == przed["name"]
    assert po["needs_review"] and any("blad programu" in w for w in po["warnings"])


def test_ponowny_odczyt_nie_gubi_wpisow(tmp_path):
    """Ponowny odczyt nadpisuje .listing.json - postac, skrzynia i cena musza przezyc."""
    stem = "item_20261001_174324_164"
    folder = tmp_path / "screenshots"
    folder.mkdir()
    (folder / f"{stem}.json").write_text(json.dumps(ocr(stem)), encoding="utf-8")
    lst = {"name": "Small Charm", "where": {"char": "Mularz", "stash": "Skrzynia wspolna 2"},
           "planned_price": "ist", "listing": []}
    (folder / f"{stem}.listing.json").write_text(json.dumps(lst), encoding="utf-8")

    tm.run(folder, verbose=False)
    po = json.loads((folder / f"{stem}.listing.json").read_text(encoding="utf-8"))
    print("po ponownym odczycie:", po.get("where"), "| cena:", po.get("planned_price"))
    assert po["where"] == {"char": "Mularz", "stash": "Skrzynia wspolna 2"}
    assert po["planned_price"] == "ist"
    assert po["listing"]          # a staty sa odczytane od nowa
