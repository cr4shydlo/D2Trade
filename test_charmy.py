"""Wycena charmow: twarde warunki per slot (Grand Charm bez skillera nie moze dostac ceny)."""
import json
from pathlib import Path

import rare_eval


def grand_charm():
    return json.loads(Path("cache/grand-charm.json").read_text(encoding="utf-8"))["items"][0]


def oferta(item, staty):
    props = {p["property"]: p["property_id"] for p in item["properties"]}
    return {"item_id": item["id"], "rarity": "magic", "name": "Grand Charm",
            "listing": [{"property_id": props[k], "value": v} for k, v in staty]}


def test_grand_charm_bez_skillera_nie_ma_ceny(monkeypatch):
    item = grand_charm()
    props = {p["property"]: p["property_id"] for p in item["properties"]}
    tab = next(k for k in props if "Skills (" in k and "Only)" in k)
    life = "+{{value}} to Life"
    pytania = []
    monkeypatch.setattr(rare_eval.tpr, "price_check",
                        lambda iid, f: pytania.append(f) or {"valuedTrades": 9, "runeValues": {"Ist Rune": 1},
                                                             "percentiles": {"floor": 1, "typical": 2,
                                                                             "good": 3, "high": 5}})
    # 45 life bez skillera: maksymalny rzut, a mimo to zlom - nie wolno pytac o cene
    zlom = rare_eval.suggest(oferta(item, [(life, 45)]), item)
    print("zlom:", zlom["text"].splitlines()[1].strip())
    assert not zlom["levels"] and not pytania
    assert "skillera" in zlom["text"]

    # skiller + 42 life: cena liczona z filtrem na drzewko ORAZ na zycie
    dobry = rare_eval.suggest(oferta(item, [(tab, 1), (life, 42)]), item)
    print("dobry:", dobry["text"].splitlines()[1].strip())
    assert dobry["levels"]
    assert f"prop_{props[tab]}Min=1" in pytania[0] and f"prop_{props[life]}Min=35" in pytania[0]

    # sam skiller tez jest sprzedawalny, ale filtr jest tylko na drzewko
    pytania.clear()
    goly = rare_eval.suggest(oferta(item, [(tab, 1)]), item)
    print("goly skiller:", goly["text"].splitlines()[0].strip())
    assert goly["levels"] and f"prop_{props[tab]}Min=1" in pytania[0]


def test_prawdziwy_charm_ze_screena():
    """Grand Charm z max rezystem trucizny z prawdziwego odczytu - bez wartosci handlowej."""
    lst = json.loads(Path("screenshots/item_20261001_174317_634.listing.json").read_text(encoding="utf-8"))
    item = json.loads(Path(f"cache/{lst['slug']}.json").read_text(encoding="utf-8"))["items"][0]
    ev = rare_eval.evaluate(lst, item)
    print(lst["name"], "slot:", ev["slot"], "| ocena:", ev["verdict"])
    assert ev["slot"] == "lcha" and ev["blocked"]


def test_small_charm_z_mocnym_statem_dostaje_cene():
    lst = json.loads(Path("screenshots/item_20261001_174324_164.listing.json").read_text(encoding="utf-8"))
    item = json.loads(Path(f"cache/{lst['slug']}.json").read_text(encoding="utf-8"))["items"][0]
    ev = rare_eval.evaluate(lst, item)
    print(lst["name"], "mocne:", [(s[0], s[2], s[3]) for s in ev["strong"]])
    assert ev["slot"] == "scha" and not ev["blocked"]
