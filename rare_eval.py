"""
rare_eval.py - pomoc przy wycenie przedmiotow magic/rare.

1) ocena: kluczowe staty dla slotu w porownaniu z maksimum z plikow gry (affixes_data.json)
2) transakcje podobnych egzemplarzy z Traderie: ta sama baza i rzadkosc, filtr na 2 najwazniejsze staty
Program NIE ustawia ceny sam - podaje poziomy z transakcji do klikniecia, decyzja nalezy do Ciebie.
"""
import re
import json
import math
from pathlib import Path

import paths
import traderie_map as tm
import traderie_price as tpr

# Maksima statow per slot: najpierw baza wyciagnieta z gry uzytkownika (game_extract.py),
# bo zna tez afiksy dodane przez moda, a dopiero potem plik z repozytorium - zeby ocena
# rzutu dzialala od razu po sklonowaniu, bez instalowania gry.
ZRODLA_MAKSIMOW = (paths.DATA / "game_data" / "affixes_data.json",
                   Path(__file__).with_name("affixes_data.json"))


def wczytaj_maksima() -> dict:
    for p in ZRODLA_MAKSIMOW:
        try:
            return json.loads(p.read_text(encoding="utf-8"))["slots"]
        except Exception:
            continue
    return {}


DATA = wczytaj_maksima()


def przeladuj():
    """Po zbudowaniu bazy z gry trzeba wziac nowe maksima - inaczej oceniamy po starych."""
    global DATA
    DATA = wczytaj_maksima()
CLASSES = r"(amazon|sorceress|necromancer|paladin|barbarian|druid|assassin|warlock)"
STAT_RX = {   # klucz statu -> wzorzec na tekscie wlasciwosci Traderie (po normalize)
    "fcr": r"faster cast rate", "ias": r"increased attack speed", "fhr": r"faster hit recovery",
    "frw": r"faster run", "fbr": r"faster block", "allres": r"all resistances", "fres": r"^fire resist",
    "cres": r"^cold resist", "lres": r"^lightning resist", "pres": r"^poison resist",
    "life": r"^\+?\{\{value\}\} to life$", "mana": r"^\+?\{\{value\}\} to mana$", "str": r"to strength$",
    "dex": r"to dexterity$", "vit": r"to vitality$", "enr": r"to energy$", "ll": r"life stolen per hit",
    "ml": r"mana stolen per hit", "mf": r"magic items", "gf": r"extra gold", "ar": r"to attack rating$",
    "ed_def": r"enhanced defense", "ed": r"enhanced damage", "mindmg": r"to minimum damage$",
    "maxdmg": r"to maximum damage$", "dr": r"^damage reduced by", "mdr": r"magic damage reduced",
    "allsk": r"to all skills", "classsk": CLASSES + r" skill levels", "tab": r"skills \(" + CLASSES + r" only\)",
    "regen": r"replenish life", "manakill": r"mana after each kill", "sock": r"socket",
}
LABEL = {"fcr": "FCR", "ias": "IAS", "fhr": "FHR", "frw": "FRW", "fbr": "FBR", "allres": "@res", "fres": "fire res",
         "cres": "cold res", "lres": "light res", "pres": "psn res", "life": "life", "mana": "mana", "str": "str",
         "dex": "dex", "vit": "vit", "enr": "ene", "ll": "LL", "ml": "ML", "mf": "MF", "gf": "GF", "ar": "AR",
         "ed_def": "ED", "ed": "ED", "mindmg": "min dmg", "maxdmg": "max dmg", "dr": "DR", "mdr": "MDR",
         "allsk": "+skills", "classsk": "+class skills", "tab": "+tab skills", "regen": "repl. life",
         "manakill": "mana/kill", "sock": "sockets"}
KEYS = {   # najwazniejsze staty dla slotu (kolejnosc = waznosc)
    "ring": ["fcr", "allres", "str", "dex", "ll", "ml", "life", "mana", "mf", "ar"],
    "amul": ["tab", "classsk", "allsk", "fcr", "allres", "str", "dex", "ll", "life", "mf"],
    "circ": ["tab", "classsk", "frw", "fcr", "sock", "allres", "str", "dex", "life", "fhr"],
    "glov": ["tab", "ias", "ll", "ml", "str", "dex", "fres", "cres", "lres", "mf", "gf"],
    "boot": ["frw", "fhr", "fres", "cres", "lres", "pres", "dex", "str", "mf", "gf"],
    "belt": ["fhr", "str", "life", "fres", "cres", "lres", "pres", "mf", "dr"],
    "jewl": ["ed", "ias", "allres", "maxdmg", "mindmg", "fhr", "str", "dex", "life"],
    "scha": ["life", "allres", "fres", "cres", "lres", "pres", "mf", "maxdmg", "ar", "fhr"],
    "mcha": ["mf", "life", "allres", "fres", "cres", "lres", "pres", "maxdmg", "ar", "fhr"],
    "lcha": ["tab", "life", "fhr", "frw", "maxdmg", "ar", "allres"],
    "helm": ["classsk", "fhr", "allres", "life", "sock", "str", "dex"],
    "tors": ["fhr", "allres", "life", "str", "dex", "sock"],
    "shld": ["fbr", "allres", "fhr", "sock", "life"],
    "weap": ["ed", "ias", "ll", "sock", "maxdmg", "cb", "ds"],
    "orb": ["classsk", "fcr", "tab", "allres", "life", "mana", "sock"],
}
TAG_SLOT = {"ring": "ring", "amulet": "amul", "circlet": "circ", "gloves": "glov", "boots": "boot", "belt": "belt",
            "jewel": "jewl", "small charm": "scha", "large charm": "mcha", "grand charm": "lcha", "helm": "helm",
            "armor": "tors", "shield": "shld", "orb": "orb"}
STRONG = 0.75      # stat >= 75% maksimum = mocny
MIN_TRADES = 3

# Opis slowny jakosci rzutu - czytelniejszy niz samo "90%". Progi dobrane tak, zeby
# "prawie maks" zaczynal sie powyzej STRONG: mocny stat to jeszcze nie swietny rzut.
QUALITY_LABELS = ((1.0, "maksymalny rzut"), (0.85, "prawie maks"), (0.6, "wysoki"),
                  (0.4, "sredni"), (0.15, "niski"), (0.0, "prawie min"))
# Progi uzywane przez okno do pomalowania paska jakosci. Trzymane tutaj, przy
# QUALITY_LABELS, zeby kolor i slowo nie rozjechaly sie przy zmianie jednego z nich.
# Same kolory naleza do okna - logika nic o nich nie wie.
MID_ROLL = 0.6     # od tego "wysoki"
LOW_ROLL = 0.4     # od tego "sredni"
WEAK_ROLL = 0.15   # ponizej: "prawie min" / "minimalny rzut"


def quality_label(q):
    """Jakosc rzutu (0..1) -> opis. None, gdy nie znamy maksimum dla tego statu."""
    if q is None:
        return None
    if q <= 0:
        return "minimalny rzut"
    for prog, opis in QUALITY_LABELS:
        if q >= prog:
            return opis
    return "minimalny rzut"

# Twarde warunki wartosci handlowej per slot. Sam prog STRONG nie wystarcza: Grand Charm z maksymalna
# mana albo rezystem to zlom, bo cala cena bierze sie ze skillera - bez niego "podobne transakcje"
# dotycza skillerow i cena wychodzi absurdalna (stad bral sie "mal za smieciowy charm").
#   must   - te staty musza byc na przedmiocie (jakakolwiek wartosc), inaczej nie podajemy ceny
#   meta   - staty, ktore w tym slocie naprawde buduja cene (mocny stat poza ta lista sie nie liczy)
#   need   - ile mocnych statow z meta musi byc poza tymi z must
#   strong - wlasny prog "mocnego" statu dla tego slotu
# Zrodla: almarsguides "Loot Worth Keeping" (co warto trzymac i jakie kombinacje), d2r-lootgoblin
# "Item Valuation" (staty meta per slot), ceny skillerow (45 life > 12% FHR > sam skiller).
RULES = {
    "lcha": {"must": ["tab"], "need": 0,
             "meta": ["tab", "life", "fhr", "frw", "maxdmg", "ar"],
             "why": "Grand Charm bez skillera (+1 do drzewka umiejetnosci) nie ma wartosci handlowej - "
                    "cena bierze sie ze skillera, a nie z zycia, many czy rezystow"},
    "mcha": {"need": 2, "strong": 0.9,
             "meta": ["mf", "life", "allres", "fres", "cres", "lres", "pres", "maxdmg", "ar", "fhr"],
             "why": "Large Charm zajmuje dwa pola w ekwipunku, wiec sprzedaje sie tylko z dwoma statami "
                    "blisko maksimum (albo z maksymalnym MF)"},
    "scha": {"need": 1,
             "meta": ["life", "allres", "fres", "cres", "lres", "pres", "mf", "maxdmg", "ar"],
             "why": "Small Charm sprzedaje sie tylko z mocnym statem meta (zycie, @res, pojedynczy res, "
                    "MF, max dmg/AR) - sam FHR, mana albo atrybut to zlom"},
}


def slot_of(item: dict) -> str:
    tags = [str(t.get("tag", "")).lower() for t in item.get("tags") or []]
    for tag in tags + [str(item.get("name", "")).lower()]:
        for name, code in TAG_SLOT.items():
            if tag == name or tag.endswith(" " + name) or tag == name + "s":
                return code
    return "weap" if any(t in ("weapon", "1 handed", "2 handed") for t in tags) else ""


def stat_key(prop_text: str):
    n = tm.normalize(prop_text)
    return next((k for k, rx in STAT_RX.items() if re.search(rx, n)), None)


def evaluate(listing: dict, item: dict) -> dict:
    """{'slot', 'stats': [(klucz, pid, wartosc, max, q, kluczowy)], 'verdict', 'strong'}"""
    rarity = listing.get("rarity", "rare")
    slot = slot_of(item)
    maxima = DATA.get(slot, {})
    keys = KEYS.get(slot, [])
    defs = {p["property_id"]: p for p in item["properties"]}
    stats = []
    for e in listing.get("listing", []):
        d = defs.get(e["property_id"]) or {"property": e.get("property", "")}
        if d.get("required") or not isinstance(e["value"], (int, float)) or isinstance(e["value"], bool):
            continue
        k = stat_key(d.get("property", ""))
        mx = (maxima.get(k) or {}).get(rarity) if k else None
        q = min(1.0, abs(e["value"]) / mx) if mx else None
        stats.append((k, e["property_id"], e["value"], mx, q, k in keys))
    rule = RULES.get(slot, {})
    meta, prog = rule.get("meta"), rule.get("strong", STRONG)
    strong = [s for s in stats if s[5] and s[4] is not None and s[4] >= prog
              and (meta is None or s[0] in meta)]
    required = [s for s in stats if s[0] in rule.get("must", [])]          # staty obowiazkowe dla slotu
    brak_must = len(required) < len(rule.get("must", []))
    blocked = rule.get("why") if brak_must or len(strong) - len(required) < rule.get("need", 1) else None
    verdict = ("obiecujacy - kilka mocnych kluczowych statow" if len(strong) >= 3 else
               "moze byc cos wart - sprawdz podobne transakcje" if len(strong) == 2 else
               "raczej slaby - malo mocnych kluczowych statow")
    if blocked:
        verdict = "bez wartosci handlowej"
    elif required and len(strong) <= len(required):
        verdict = "sprzedawalny, ale bez dodatkowego mocnego statu"
    return {"slot": slot, "stats": stats, "verdict": verdict, "strong": strong, "keys": keys,
            "blocked": blocked, "required": required}


def rolls(listing: dict, item: dict):
    """Jak traderie_price.rolls, ale dla magic/rare: zakres = 1..maksimum afiksu dla slotu i rzadkosci.
    Zwraca [(pid, nazwa, wartosc, min, max, udzial)] - najpierw staty kluczowe dla slotu."""
    ev = evaluate(listing, item)
    defs = {p["property_id"]: p for p in item["properties"]}
    out = []
    for k, pid, v, mx, q, key in ev["stats"]:
        if not mx:
            continue
        name = tpr.stat_name((defs.get(pid) or {}).get("property", "")) or LABEL.get(k, k)
        out.append((pid, name, v, 1, mx, q, key))
    out.sort(key=lambda r: (not r[6], ev["keys"].index(stat_key((defs.get(r[0]) or {}).get("property", "")) or "")
                            if r[6] else 99))
    return [r[:6] for r in out]


def suggest(listing: dict, item: dict) -> dict:
    rarity = listing.get("rarity", "rare")
    ev = evaluate(listing, item)
    lines = []
    shown = sorted((s for s in ev["stats"] if s[0]), key=lambda s: (not s[5], ev["keys"].index(s[0]) if s[5] else 99))
    desc = ", ".join(f"{LABEL.get(k, k)} {v}" + (f"/{mx}" if mx else "") for k, _, v, mx, _, _ in shown[:6])
    lines.append(f"   ocena ({rarity}): {ev['verdict']}" + (f" | {desc}" if desc else ""))

    # filtry: 2 najwazniejsze kluczowe staty, ktore przedmiot ma (najpierw wg waznosci dla slotu)
    keyed = [s for s in ev["stats"] if s[5] and s[4] is not None]
    keyed.sort(key=lambda s: (ev["keys"].index(s[0]), -(s[4] or 0)))
    # Cena ma sens tylko wtedy, gdy mamy po czym filtrowac MOCNY stat. Inaczej do wynikow wchodza
    # dobre egzemplarze (np. skillery wsrod charmow z zyciem) i cena jest zawyzona.
    if ev["blocked"] or not ev["strong"]:
        powod = ev["blocked"] or ("zaden kluczowy stat nie jest wysoki - cena z transakcji bylaby mylaca "
                                  f"(zawyzaja ja dobre egzemplarze {LABEL.get(ev['keys'][0], '')})")
        lines.append("   " + powod + ".")
        lines.append("   Nie podaje ceny - lepiej jej nie podac niz podac mylaca.")
        return {"text": "\n".join(lines), "price": "", "levels": {}}
    # bez tokenu Traderie zostaje sama ocena rzutu - transakcji nie ma skad wziac
    if tm.local_only():
        lines.append("   " + tpr.NO_TRADERIE)
        return {"text": "\n".join(lines), "price": "", "levels": {}}
    # staty z "must" zawsze wchodza do filtra - w charmie to konkretne drzewko decyduje o cenie
    keyed = (ev["required"] + [k for k in ev["strong"] if k not in ev["required"]]
             + [k for k in keyed if k not in ev["strong"] and k not in ev["required"]])
    base = tpr.filters_for(listing) + f"&prop_Rarity={rarity}"
    pc, used = None, []
    for n in (2, 1):
        chosen = keyed[:n]
        f = base + "".join(f"&prop_{pid}Min={max(1, math.floor(v * 0.85))}" for _, pid, v, _, _, _ in chosen)
        got = tpr.price_check(listing["item_id"], f)
        if got and got.get("valuedTrades", 0) >= MIN_TRADES:
            pc, used = got, chosen
            break
    if pc:
        if pc.get("runeValues"):
            tpr.RUNE_VALUES.update({k: v for k, v in pc["runeValues"].items() if k.endswith(" Rune") or k in tpr.ALIASES})
        what = ", ".join(f"{LABEL.get(k, k)} >= {max(1, math.floor(v * 0.85))}" for k, _, v, _, _, _ in used)
        lines.append("   " + tpr.fmt_pc(pc) + f" - podobne z {what}")
        pct = pc["percentiles"]
        levels = {k: tpr.rune_combo(pct[k]) for k in ("floor", "typical", "good", "high") if pct.get(k)}
        lines.append("   to tylko pomoc: rare'y roznia sie pozostalymi statami - przy dobrych rozwaz 'offer'")
        return {"text": "\n".join(lines), "price": "", "levels": levels}
    lines.append("   za malo podobnych transakcji (ta sama baza i zblizone kluczowe staty) - "
                 "rozwaz wystawienie z 'offer' (czekam na oferty)")
    return {"text": "\n".join(lines), "price": "", "levels": {}}
