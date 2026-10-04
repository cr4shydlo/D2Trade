"""
d2jsp_post.py - skladanie JEDNEGO posta sprzedazowego na d2jsp (BBCode) z listy przedmiotow.

Post kopiujesz i wklejasz na forum samodzielnie - regulamin d2jsp (pkt 20) zabrania automatyzacji
publikowania i odswiezania stron, wiec skrypt niczego na d2jsp nie wysyla ani nie sprawdza.

Ceny: domyslnie w runach (jak na Traderie). Forum Gold dochodzi, gdy w Ustawieniach (sekcja d2jsp)
wpiszesz, ile FG kosztuje jedna Ist - reszte walut program przelicza po kursach z Traderie
(zapamietanych przy wycenach). Kurs FG ustala sie recznie, z ofert na d2jsp: nie ma do tego
oficjalnego zrodla, a strony d2jsp nie odpytujemy (regulamin, pkt 20).
Plik d2jsp_fg.json nadal dziala i ma pierwszenstwo - mozna w nim poprawic pojedyncze waluty,
np. {"Ist Rune": 60, "Perfect Amethyst": 3}.
"""
import re
import json
import math
from pathlib import Path

import i18n
import traderie_map as tm
import traderie_post as tp
import traderie_price as tpr

FG_FILE = Path("d2jsp_fg.json")
THREADS_FILE = Path("d2jsp_threads.json")


def show_runes() -> bool:
    """Czy w poscie maja byc ceny w runach (domyslnie tak)."""
    return bool(i18n.settings().get("d2jsp_runes", True))


def show_fg() -> bool:
    """Czy w poscie maja byc ceny w FG (domyslnie tak, gdy wpisany jest kurs)."""
    return bool(i18n.settings().get("d2jsp_fg", bool(fg_per_ist())))


def fg_round(value: float) -> float:
    """Do pelnej polowki FG w dol (89.7 -> 89.5): przy cenie lepiej zejsc nizej niz zawyzyc."""
    return math.floor(value * 2) / 2


def fg_per_ist() -> float:
    """Ile FG za jedna Ist (0 = nie pokazuj FG)."""
    try:
        return max(0.0, float(i18n.settings().get("d2jsp_fg_per_ist") or 0))
    except (TypeError, ValueError):
        return 0.0


def fg_table() -> dict:
    """Kursy walut w FG: z przelicznika (kursy Traderie x cena Ist), poprawione plikiem d2jsp_fg.json."""
    table = {}
    kurs = fg_per_ist()
    if kurs:
        for name, w_ist in (tpr.load_runes() or {}).items():
            if w_ist:
                table[name] = round(w_ist * kurs, 2)
    if FG_FILE.exists():
        try:
            table.update(json.loads(FG_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return table


def price_fg(price: str, table: dict):
    """'ist+mal' -> suma FG (tansza z alternatyw) albo None, gdy brak kursu ktorejs waluty."""
    if not table or not price or price == "offer":
        return None
    try:
        items, _ = tp.parse_price(price)
    except ValueError:
        return None
    groups = {}
    for it in items:
        v = table.get(it["label"])
        g = groups.setdefault(it["group"], [0, True])
        if v is None:
            g[1] = False
        else:
            g[0] += v * it["quantity"]
    vals = [v for v, ok in groups.values() if ok]
    return fg_round(min(vals)) if vals else None


def price_text(price: str) -> str:
    if not price or price == "offer":
        return "c/o"
    return price.replace("+", " + ").replace("|", " or ").replace("pamy", "p-amy")


# ---------- grupowanie wedlug typu przedmiotu (tagi Traderie) ----------
GROUPS = [  # (naglowek, slowa kluczowe w tagach) - kolejnosc = priorytet i kolejnosc w poscie
    ("Charms", ("charm",)),
    ("Jewels", ("jewel",)),
    ("Amulets", ("amulet", "neck")),
    ("Rings", ("ring", "finger")),
    ("Helms", ("helm", "circlet", "pelt", "head")),
    ("Armor", ("armor", "torso")),
    ("Shields", ("shield", "voodoo")),
    ("Gloves", ("glove", "hands")),
    ("Belts", ("belt", "waist")),
    ("Boots", ("boot", "feet")),
    ("Weapons", ("sword", "axe", "polearm", "mace", "spear", "bow", "dagger", "javelin", "staff", "wand",
                 "scepter", "orb", "claw", "hammer", "club", "throwing", "katar", "knife", "scythe", "weapon",
                 "handed")),
]
ORDER = ["Helms", "Armor", "Shields", "Weapons", "Gloves", "Belts", "Boots",
         "Amulets", "Rings", "Charms", "Jewels", "Runewords", "Other"]


def group_of(item: dict) -> str:
    if item.get("type") == "runewords":
        return "Runewords"
    tags = [t.get("tag", "").lower() for t in item.get("tags") or []]
    for label, keys in GROUPS:
        if any(k in t for t in tags for k in keys):
            return label
    return "Other"


# ---------- skroty statow w stylu d2jsp ----------
ELEM = {"cold": "cold", "fire": "fire", "lightning": "light", "poison": "psn", "magic": "mag"}
SHORT = [  # (wzorzec nazwy statu po normalizacji, format)
    ("enhanced defense", "ed{v}"), ("enhanced damage", "ed{v}"), ("defense vs missile", "def vs missile {v}"),
    ("defense", "def {v}"), ("life stolen per hit", "ll{v}"), ("mana stolen per hit", "ml{v}"),
    ("all resistances", "@{v}"), ("all attributes", "attr{v}"), ("experience gained", "xp{v}"),
    ("faster cast rate", "fcr{v}"), ("increased attack speed", "ias{v}"), ("faster hit recovery", "fhr{v}"),
    ("faster run walk", "frw{v}"), ("faster block rate", "fbr{v}"), ("increased chance of blocking", "block{v}"),
    ("better chance of getting magic items", "mf{v}"), ("extra gold from monsters", "gf{v}"),
    ("attack rating", "ar{v}"), ("strength", "str{v}"), ("dexterity", "dex{v}"), ("vitality", "vit{v}"),
    ("energy", "ene{v}"), ("mana after each kill", "{v} mana/kill"), ("life after each kill", "{v} life/kill"),
    # trucizna to w tooltipie jedna linia z dwiema liczbami ("+50 poison damage over 3 seconds");
    # bez tego wpisu skrot wychodzil "poison damage over 50", czyli obrazenia udawaly sekundy
    ("poison damage over", "{v} psn dmg"),
    ("physical damage received reduced", "pdr{v}%"), ("magic damage reduced", "mdr{v}"),
    ("damage reduced", "dr{v}"), ("all skills", "+{v} skills"), ("crushing blow", "cb{v}"),
    ("deadly strike", "ds{v}"), ("open wounds", "ow{v}"), ("replenish life", "rep{v}"),
    ("light radius", "light{v}"), ("life", "life{v}"), ("mana", "mana{v}"),
]


def short_stat(name: str, value) -> str:
    n = tm.normalize(name).replace("/", " ")
    n = " ".join(w for w in n.split() if w not in ("to", "by", "of", "the"))
    v = value
    m = re.match(r"enemy (\w+) resistance", n)
    if m:
        return f"-{v}% {ELEM.get(m.group(1), m.group(1))} pierce"
    m = re.match(r"(\w+) resist(?:ance)?$", n)
    if m and m.group(1) in ELEM:
        return f"{ELEM[m.group(1)]}res {v}"
    m = re.match(r"(\w+) skill damage", n)
    if m:
        return f"+{v}% {ELEM.get(m.group(1), m.group(1))} dmg"
    m = re.match(r"(\w+) absorb", n)
    if m:
        return f"{ELEM.get(m.group(1), m.group(1))} abs {v}"
    m = re.match(r"(.+?) skill levels$", n) or re.match(r"(.+?) skills(?: \(.*\))?$", n)
    if m and m.group(1) not in ("all",):
        who = m.group(1).split()[0]
        return f"+{v} {{}} skills".format({"sorceress": "sorc", "necromancer": "necro", "barbarian": "barb",
                                           "paladin": "pal", "assassin": "sin", "amazon": "zon"}.get(who, who))
    for key, fmt in SHORT:
        k = " ".join(w for w in key.split() if w not in ("to", "by", "of", "the"))
        if n.startswith(k):
            return fmt.format(v=v)
    words = n.replace("(", "").replace(")", "").split()
    return f"{' '.join(words[:3])} {v}"


ELEM_DMG = re.compile(r"(?:to )?(min|max)imum (fire|cold|lightning|magic|poison)? ?damage")


def merge_pairs(pairs: list) -> list:
    """['minimum fire damage 1','maximum fire damage 4'] -> ['1-4 fire dmg'] (jak w grze)."""
    mins, out = {}, []
    for text in pairs:
        m = ELEM_DMG.match(text)
        if not m:
            out.append(text)
            continue
        elem, val = (m.group(2) or "").strip(), text.rsplit(" ", 1)[-1]
        if m.group(1) == "min":
            mins[elem] = val
            out.append(("PAIR", elem))
        elif elem in mins:
            out = [x for x in out if x != ("PAIR", elem)]
            out.append(f"{mins.pop(elem)}-{val}" + (f" {elem} dmg" if elem else " dmg"))
        else:
            out.append(text)
    return [f"{mins[e]} min {e} dmg".replace("  ", " ") if isinstance(x, tuple) else x
            for x, e in ((x, x[1] if isinstance(x, tuple) else "") for x in out)]


def short_stats(lst: dict, item: dict):
    """(['def 279', '@23', ...], ['eth', 'Monarch']) - skroty statow i dopiski (eth/unid/baza)."""
    defs = {p["property_id"]: p for p in item["properties"]} if item else {}
    stats, flags = [], []
    for e in lst.get("listing", []):
        d = defs.get(e["property_id"]) or {"property": e.get("property", "")}
        prop = d.get("property", "")
        if d.get("required") or prop in tp.REQUIRED:
            if prop.startswith("Base Item"):
                flags.append(str(e["value"]))
            continue
        if prop.startswith("Required Level"):     # wymagany poziom nie jest statem do posta
            continue
        if prop in ("Ethereal", "Unidentified"):
            flags.append("eth" if prop == "Ethereal" else "unid")
            continue
        stats.append(short_stat(tpr.stat_name(prop), e["value"]))
    return merge_pairs(stats), flags


def item_line(lst: dict, item: dict, price: str, table: dict) -> str:
    stats, flags = short_stats(lst, item)
    kind = lst.get("kind") if lst.get("kind") in ("rare", "magic", "crafted") else None
    name = (f"{kind.title()} " if kind else "") + lst["name"] + (f" ({', '.join(flags)})" if flags else "")
    czesci = [name, "/".join(stats), price_part(price, table)]      # bez cen linia konczy sie na statach
    return " - ".join(c for c in czesci if c)


def price_part(price: str, table: dict) -> str:
    """Cena w poscie wedlug dwoch przelacznikow z Ustawien (runy, FG):
    oba -> 'ist + mal (~90 fg)', same FG -> '90 fg', same runy -> 'ist + mal', zadne -> bez ceny.
    FG bez wpisanego kursu nie da sie policzyc, wiec wtedy zostaje to, co wybrano poza nim."""
    runy = price_text(price) if show_runes() else ""
    fg = price_fg(price, table) if show_fg() else None
    if runy and fg:
        return f"{runy} (~{fg:g} fg)"
    if fg:
        return f"{fg:g} fg"
    return runy


def build_post(entries: list) -> str:
    """entries: [(listing_dict, cena_tekst)]. Zwraca BBCode gotowy do wklejenia."""
    table = fg_table()
    groups = {}
    for lst, price in entries:
        item = tm.get_item(lst["name"])
        groups.setdefault(group_of(item) if item else "Other", []).append(item_line(lst, item, price, table))
    lines = []
    for g in ORDER:
        if g in groups:
            lines += ([""] if lines else []) + [f"[b][u]{g}[/u][/b]"] + sorted(groups[g])
    lines += ["", "[b]Accepting FG offers[/b] - post here or PM me."]
    return "\n".join(lines)


def threads() -> list:
    return json.loads(THREADS_FILE.read_text(encoding="utf-8")) if THREADS_FILE.exists() else []


def save_threads(urls: list):
    THREADS_FILE.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")
