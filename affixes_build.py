"""
affixes_build.py - buduje affixes_data.json z plikow danych gry (MagicPrefix/MagicSuffix/ItemTypes).

Zrodlo: https://github.com/blizzhackers/d2data (pliki .txt z gry przekonwertowane do JSON).
Uruchom ponownie po patchu, ktory zmienia afiksy:   py -3.11 affixes_build.py
"""
import json
import urllib.request
from pathlib import Path

SRC = "https://raw.githubusercontent.com/blizzhackers/d2data/master/json/{}.json"
SLOTS = ["ring", "amul", "circ", "glov", "boot", "belt", "jewl", "scha", "mcha", "lcha", "helm", "tors", "shld", "weap", "orb"]
CLASS = {"ama": "amazon", "sor": "sorceress", "nec": "necromancer", "pal": "paladin", "bar": "barbarian",
         "dru": "druid", "ass": "assassin", "war": "warlock"}
MODS = {  # kod moda z gry -> klucz statu
    "cast1": "fcr", "cast2": "fcr", "cast3": "fcr", "swing1": "ias", "swing2": "ias", "swing3": "ias",
    "balance1": "fhr", "balance2": "fhr", "balance3": "fhr", "move1": "frw", "move2": "frw", "move3": "frw",
    "block1": "fbr", "block2": "fbr", "block3": "fbr", "res-all": "allres", "res-fire": "fres", "res-cold": "cres",
    "res-ltng": "lres", "res-pois": "pres", "hp": "life", "mana": "mana", "str": "str", "dex": "dex", "vit": "vit",
    "enr": "enr", "lifesteal": "ll", "manasteal": "ml", "mag%": "mf", "gold%": "gf", "att": "ar", "ac%": "ed_def",
    "dmg%": "ed", "dmg-min": "mindmg", "dmg-max": "maxdmg", "red-dmg": "dr", "red-mag": "mdr", "allskills": "allsk",
    "skilltab": "tab", "regen": "regen", "mana-kill": "manakill", "sock": "sock", "crush": "cb", "openwounds": "ow",
    "deadly": "ds", **{c: "classsk" for c in CLASS},
}


def load(name):
    with urllib.request.urlopen(SRC.format(name), timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    return list(d.values()) if isinstance(d, dict) else d


def ancestors(code, types):
    out, todo = set(), [code]
    while todo:
        c = todo.pop()
        if c and c not in out:
            out.add(c)
            t = types.get(c) or {}
            todo += [t.get("Equiv1"), t.get("Equiv2")]
    return out


def main():
    types = {t["Code"]: t for t in load("itemtypes") if t.get("Code")}
    affixes = [a for a in load("magicprefix") + load("magicsuffix") if a.get("spawnable") == 1]
    data = {}
    for slot in SLOTS:
        anc = ancestors(slot, types)
        res = {}
        for a in affixes:
            itypes = {a.get(f"itype{i}") for i in range(1, 8)} - {None}
            etypes = {a.get(f"etype{i}") for i in range(1, 6)} - {None}
            if not itypes & anc or etypes & anc:
                continue
            for i in (1, 2, 3):
                key = MODS.get(a.get(f"mod{i}code"))
                hi = a.get(f"mod{i}max")
                if not key or not isinstance(hi, (int, float)):
                    continue
                r = res.setdefault(key, {"magic": 0, "rare": 0})
                r["magic"] = max(r["magic"], hi)
                if a.get("rare") == 1:
                    r["rare"] = max(r["rare"], hi)
        data[slot] = res
    out = Path(__file__).with_name("affixes_data.json")
    out.write_text(json.dumps({"source": "blizzhackers/d2data (MagicPrefix/MagicSuffix/ItemTypes)",
                               "slots": data}, indent=1), encoding="utf-8")
    print(f"zapisano {out} ({len(affixes)} afiksow)")


if __name__ == "__main__":
    main()
