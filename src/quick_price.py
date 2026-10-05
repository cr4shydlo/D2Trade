"""
quick_price.py - szybka wycena bez screena: nazwa przedmiotu + opcjonalnie staty.

Przyklady:  shako          harlequin crest def 136          spirit fcr 35 mana 110
            arach ed 120   griffon 15 pierce                annihilus attr 20 @20 xp 10
"""
import re
import urllib.parse

import traderie_map as tm
import traderie_price as tpr
import d2jsp_post
import game_db

# popularne skroty nazw (tylko jednoznaczne)
ALIASES = {
    "shako": "Harlequin Crest", "harle": "Harlequin Crest", "arach": "Arachnid Mesh",
    "anni": "Annihilus", "torch": "Hellfire Torch", "soj": "The Stone of Jordan",
    "mara": "Mara's Kaleidoscope", "griffon": "Griffon's Eye", "gheed": "Gheed's Fortune",
    "viper": "Skin of the Vipermagi", "vipermagi": "Skin of the Vipermagi", "cta": "Call to Arms",
    "hoto": "Heart of the Oak", "coh": "Chains of Honor", "wf": "Windforce",
    "tgods": "Thundergod's Vigor", "nightwing": "Nightwing's Veil", "magefist": "Magefist",
    "eschuta": "Eschuta's Temper", "eshuta": "Eschuta's Temper", "eshuta temper": "Eschuta's Temper",
    "eschuta temper": "Eschuta's Temper",
}
SETTINGS = (("Platform", lambda: tm.PLATFORM), ("Mode", lambda: tm.MODE),
            ("Ladder", lambda: tm.LADDER), ("Game version", lambda: tm.GAME_VERSION))


NUM = re.compile(r"([a-z@]*)(-?\d+)%?")


def tokens(q: str) -> list:
    return q.lower().replace(",", " ").replace("/", " ").split()


def parse_stats(t: list):
    """Staty w obu kolejnosciach: 'def 136', 'ed120', '@30', '8 mag pierce'. Zwraca ([(etykieta, liczba)], [smieci])."""
    pairs, junk, i = [], [], 0
    has_num = lambda x: re.search(r"\d", x) is not None
    while i < len(t):
        m = NUM.fullmatch(t[i])
        if m and m.group(1):                                   # 'ed120', '@30'
            pairs.append((m.group(1), int(m.group(2))))
            i += 1
        elif m:                                                # '8 mag pierce' (liczba, potem nazwa)
            j, words = i + 1, []
            while j < len(t) and not has_num(t[j]):
                words.append(t[j])
                j += 1
            if j < len(t) and words and NUM.fullmatch(t[j]) and not NUM.fullmatch(t[j]).group(1):
                words.pop()                                    # ostatnie slowo nalezy do nastepnej pary ('ed 178')
                j -= 1
            pairs.append((" ".join(words), int(m.group(2))))
            i = j
        else:                                                  # 'def 136' (nazwa, potem liczba)
            j, words = i, []
            while j < len(t) and not has_num(t[j]):
                words.append(t[j])
                j += 1
            if j < len(t) and NUM.fullmatch(t[j]) and not NUM.fullmatch(t[j]).group(1):
                pairs.append((" ".join(words), int(NUM.fullmatch(t[j]).group(2))))
                i = j + 1
            else:
                junk += words
                i = j
    return pairs, junk


def resolve(name: str):
    full = ALIASES.get(name.strip(), name)
    return tm.get_item(full.title().replace("'S ", "'s "))


def find_item(name: str):
    """Nazwa -> definicja przedmiotu z Traderie (alias, dokladna nazwa, wyszukiwarka)."""
    full = ALIASES.get(name.strip(), name)
    item = tm.get_item(full.title().replace("'S ", "'s "))
    if item:
        return item, []
    try:
        d = tm.http_json(f"{tm.API}/items?search={urllib.parse.quote(full)}")
    except Exception:
        return None, []
    found = [it for it in d.get("items") or [] if it.get("name")]
    if not found:
        return None, []
    words = set(tm.normalize(full).split())
    found.sort(key=lambda it: (tm.normalize(it["name"]) != tm.normalize(full),
                               not words <= set(tm.normalize(it["name"]).split())))
    best = tm.get_item(found[0]["name"])
    return best, [it["name"] for it in found[1:13]]


def stat_code(prop: str) -> str:
    """Skrot d2jsp dla wlasciwosci bez liczby, np. 'fcr', 'def', '@', 'coldres', 'mag pierce'."""
    code = d2jsp_post.short_stat(tpr.stat_name(prop), 0)
    return re.sub(r"[\d%+\-]", "", code).replace("  ", " ").strip()


def map_stats(item: dict, stats: list):
    """[(etykieta, wartosc)] -> ([{property_id, value}], [nierozpoznane])."""
    ranges, _ = tm.parse_ranges(item.get("description") or "")
    cands = []
    for p in item["properties"]:
        if p["type"] != "number" or p.get("required") or p["property"] in dict(SETTINGS):
            continue
        variable = tm.range_key(tm.words(p["property"]), ranges) is not None
        name = tm.normalize(tpr.stat_name(p["property"]))
        cands.append((not variable, p, stat_code(p["property"]).replace(" ", ""), name))
    cands.sort(key=lambda c: c[0])            # najpierw staty zmienne
    out, unknown = [], []
    for label, v in stats:
        lab = label.replace(" ", "")
        hit = None
        for _, p, code, name in cands:
            lw, nw = label.split(), name.split()
            words_ok = lw and all(any(n.startswith(w) for n in nw) for w in lw)   # 'absorb' ~ 'magic absorb'
            if lab and (lab == code or code.startswith(lab) or name.replace(" ", "").startswith(lab) or words_ok
                        or (lab in ("def", "defense") and p["property_id"] == 1855)):
                hit = p
                break
        if lab in ("def", "defense"):          # obrona calkowita ma pierwszenstwo przed '+X Defense'
            hit = next((p for _, p, _, _ in cands if p["property_id"] == 1855), hit)
        if hit:
            out.append({"property_id": hit["property_id"], "value": abs(v)})
        else:
            unknown.append(f"{label} {v}".strip())
    return out, unknown


def variable_stats(item: dict) -> str:
    """Czytelna lista zmiennych statow z zakresami, np. 'Enhanced Damage 40-60 | jeden z: Fire Arrow 1-3 / Cold Arrow 1-3'."""
    out = []
    for g in tm.range_parts(item.get("description") or ""):
        items = [f"{label} {lo}-{hi}" for _, lo, hi, label in g]
        out.append(("jeden z: " + " / ".join(items)) if len(items) > 1 else items[0])
    return "\n".join("  - " + x for x in out) if out else "  (brak - wszystkie staty stale)"


def quick_price(query: str) -> dict:
    """Zwraca {'title', 'text', 'levels', 'price'}."""
    t = tokens(query)
    if not t:
        return {"title": "Szybka wycena", "text": "Podaj nazwe przedmiotu, np. 'shako def 136'.", "levels": {}}
    first_num = next((i for i, x in enumerate(t) if re.search(r"\d", x)), len(t))
    item, others, cut = None, [], first_num
    # Najpierw katalog z plikow gry: ustala dlugosc nazwy bez pytania Traderie.
    # Bez tego kazdy nietrafiony poczatek zapytania to osobne zapytanie do API.
    n, wpis = game_db.najdluzsza_nazwa(t, maks=max(first_num, 1))
    if wpis:
        item = resolve(wpis["name"])
        if item:
            cut = n
    # nazwa = najdluzszy poczatek zapytania, ktory istnieje w Traderie ('harlequin crest def 136' -> 'harlequin crest')
    if not item:
        for n in range(max(first_num, 1), 0, -1):
            item = resolve(" ".join(t[:n]))
            if item:
                cut = n
                break
    if not item:
        for n in range(max(first_num, 1), 0, -1):
            item, others = find_item(" ".join(t[:n]))
            if item:
                cut = n
                break
    if not item:
        return {"title": "Szybka wycena", "text": f"Nie znaleziono przedmiotu '{' '.join(t[:first_num])}' na Traderie.",
                "levels": {}}
    stats, junk = parse_stats(t[cut:])
    listing_stats, unknown = map_stats(item, stats)
    unknown += junk
    by_name = {p["property"]: p["property_id"] for p in item["properties"]}
    props = [{"property_id": by_name[l], "property": l, "value": f()} for l, f in SETTINGS if l in by_name]
    lst = {"item_id": item["id"], "slug": item["slug"], "name": item["name"], "type": item["type"],
           "properties": props, "listing": listing_stats + [{"property_id": p["property_id"], "value": p["value"]}
                                                           for p in props]}
    res = tpr.suggest(lst, item)
    extra = []
    if unknown:
        extra.append("nie rozpoznano: " + ", ".join(unknown))
    text = res.get("text", "").replace("   ", "").strip()
    head = "Zmienne staty:\n" + variable_stats(item)
    return {"title": item["name"], "text": "\n".join([head, ""] + [text] + extra), "levels": res.get("levels") or {},
            "price": res.get("price", ""), "others": others, "item": item}
