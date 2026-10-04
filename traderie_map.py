"""
traderie_map.py - mapowanie odczytow OCR (pliki .json z d2_ocr.py) na wlasciwosci Traderie.

Uzycie:
    py traderie_map.py screenshots

Dla kazdego <screen>.json powstaje <screen>.listing.json z:
  - item_id / slug / nazwa z Traderie
  - lista wlasciwosci (property_id + wartosc) gotowa do listingu
  - ostrzezenia walidacji (wartosci spoza zakresu, niezgodny Req. Level)
  - linie, ktorych nie udalo sie dopasowac
Definicje przedmiotow sa cache'owane w folderze cache/ (mozna tam tez recznie
wrzucic plik <slug>.json zapisany z przegladarki, jesli pobieranie nie dziala).
"""
import re
import unicodedata
import sys
import json
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

import paths

# --- ustawienia listingu (wymagane przez Traderie) ---
PLATFORM = "PC"                      # PC / switch / playstation / xbox
MODE = "softcore"                    # softcore / hardcore
LADDER = "Ladder"                    # Ladder / Non Ladder
GAME_VERSION = "reign of the warlock"  # classic (base game) / lord of destruction / reign of the warlock

INCLUDE_DEFENSE = True   # czy dolaczac Defense do listingu (wynika z ED, ale bywa filtrowana)
LISTING_FLAGS = {"Ethereal", "Unidentified"}  # cechy egzemplarza, zawsze wystawiane gdy obecne
# Pola wpisane/ustawione przez uzytkownika - ponowny odczyt nadpisuje .listing.json, wiec trzeba je przeniesc
KEEP_ON_REMAP = ("where", "planned_price", "sold", "sold_via", "removed")

API = "https://traderie.com/api/diablo2resurrected"
# Dodatkowe parametry zapytania o przedmiot. Jesli zadna wersja nie zwraca "properties",
# skopiuj z przegladarki pelny URL zapytania items?id=... i wklej tu jego czesc po slugu.
ITEM_QUERY_VARIANTS = [
    "&variants=&tags=&properties=true",
    "&properties=true",
    "&variants=true&tags=true&properties=true",
]
CACHE = Path("cache")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"

# linie tooltipa, ktorych nie wystawiamy (informacyjne)
IGNORE = [
    r"^durability", r"^required (strength|dexterity)", r"damage:", r"class\s*-",
    r"^belt size", r"^(quantity|throw damage)", r"^can be inserted",
    # podpowiedzi interfejsu gry
    r"click to", r"^keep in inventory", r"^inventory$", r"^right click",
    # runy runewordu ('TalThulOrtAmn') i szansa bloku tarczy
    r"^'.*'$", r"^chance to block",
    # elementy interfejsu, ktore wpadaja w kadr
    r"hold shift", r"^(life|mana): \d+\s*/\s*\d+", r"^stash$", r"^\(?[a-z]+ only\)?$",
]
# napisy interfejsu (zakladki skrzyni itp.), ktore moga trafic nad tooltip - nie sa nazwa przedmiotu
UI_WORDS = {"stash", "materials", "runes", "gems", "personal", "shared", "inventory", "equipment"}


def is_ui_line(line: str) -> bool:
    """Linia zlozona wylacznie z napisow interfejsu, np. 'GEMS MATERIALS RUNES'."""
    ws = re.findall(r"[a-z]+", normalize(line))
    return bool(ws) and all(w in UI_WORDS for w in ws)


# ---------- pomocnicze ----------
def plain(s: str) -> str:
    """Usuwa znaki diakrytyczne dodawane przez OCR (TOMBALE, MONARCH)."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(s: str) -> str:
    s = plain(s).lower().replace("\u2013", "-")
    s = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slugify(name: str) -> str:
    s = plain(name).lower().replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


AUTH_FILE = paths.secret("traderie_auth.txt")   # sekrety trzymamy w jednym katalogu
_AUTH = None


def load_auth() -> dict:
    """Naglowki z secrets/traderie_auth.txt ('Authorization: Bearer ...' albo 'Cookie: ...').
    Akceptuje tez zapis bez dwukropka ('Authorization Bearer ...'). Brak pliku = {}."""
    global _AUTH
    if _AUTH is None:
        _AUTH = {}
        if AUTH_FILE.exists():
            for line in AUTH_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                if ":" in line.split(" ", 1)[0]:
                    k, v = line.split(":", 1)
                else:
                    k, _, v = line.partition(" ")
                _AUTH[k.strip()] = v.strip()
        bad = {k: v for k, v in _AUTH.items()
               if "\u2026" in v or v.endswith("...") or any(ord(c) > 255 for c in v)}
        if bad:
            print(f"!!! {AUTH_FILE}: wartosc naglowka {', '.join(bad)} jest ucieta albo zawiera niedozwolone znaki "
                  "(np. wielokropek z widoku DevTools).")
            print("    Skopiuj naglowek z widoku 'Nieprzetworzone' (Raw) w DevTools. Na razie dzialam bez autoryzacji.")
            for k in bad:
                del _AUTH[k]
    return _AUTH


class SessionExpired(Exception):
    pass


def http_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **load_auth()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if "unauthorized jwt" in body.lower():
            raise SessionExpired("Sesja Traderie wygasla - skopiuj ponownie naglowek Authorization "
                                 "do secrets/traderie_auth.txt") from None
        raise


def has_props(data) -> bool:
    return bool(data.get("items")) and all("properties" in it for it in data["items"])


LOOKUP_FAILED = set()      # slugi, ktorych nie udalo sie pobrac (blad sieci) w tym przebiegu


def have_auth() -> bool:
    return bool(load_auth().get("Authorization"))


def local_only() -> bool:
    """Praca bez Traderie: nie ma tokenu, a sa dane wyciagniete z plikow gry.

    Okno pyta o to, zeby nie proponowac cen i nie oferowac wystawiania, kiedy i tak
    nie ma czym. Import w srodku, bo game_source korzysta z tego modulu.
    """
    import game_source
    return not have_auth() and game_source.dostepne()


def from_game(name: str):
    """Definicja z plikow gry albo None, gdy uzytkownik nie wyciagnal danych."""
    import game_source
    return game_source.get_item(name)


def get_item(name: str):
    """Definicja przedmiotu (z wlasciwosciami): cache -> API -> pliki gry.

    Bez tokenu pomijamy API (i tak odpowie 'Unauthorized'), ale cache nadal czytamy:
    definicje sciagniete wczesniej sa dokladniejsze od zlozonych z plikow gry, bo maja
    prawdziwe numery wlasciwosci Traderie.
    """
    CACHE.mkdir(exist_ok=True)
    slug = slugify(name)
    cached = CACHE / f"{slug}.json"
    data = None
    if cached.exists():
        data = json.loads(cached.read_text(encoding="utf-8"))
        if not has_props(data):
            cached.unlink()  # stary, niepelny wpis
            data = None
    if data is None and have_auth():
        for extra in ITEM_QUERY_VARIANTS:
            try:
                d = http_json(f"{API}/items?id={slug}{extra}")
            except Exception as e:
                print(f"   (pobieranie {slug} nie powiodlo sie: {e})")
                LOOKUP_FAILED.add(slug)      # blad sieci - NIE traktujemy tego jak "brak w Traderie"
                break
            if has_props(d):
                data = d
                break
        if data:
            cached.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if data is None:
        # brak w Traderie (magic/rare), blad nazwy albo brak tokenu - probujemy plikow gry,
        # a gdy i tego nie ma, zwracamy None i o rodzaju przedmiotu decyduje map_item
        return from_game(name)
    items = data.get("items") or []
    for it in items:
        if normalize(it.get("name", "")) == normalize(name):
            return it
    return items[0] if len(items) == 1 else from_game(name)


def stem(text: str) -> str:
    """Tekst bez wartosci i znakow - do laczenia opisu z szablonem wlasciwosci."""
    text = re.sub(r"\{\{\w+\}\}", " ", text)
    text = re.sub(r"[\d+%\-:()/]", " ", text)
    return normalize(text)


_REGEX_CACHE = {}


def template_regex(prop: dict, tolerant: bool = False):
    """Szablon Traderie ('+{{value}}% Enhanced Defense') -> regex dla linii z OCR.
    tolerant=True: znak tuz przed wartoscia moze byc inny niz w szablonie
    (np. 'Requirements +{{value}}%' vs 'Requirements -50%'); faktyczny znak trafia do grupy 'sign').

    Wynik zalezy tylko od trzech pol definicji, wiec trzymamy go w slowniku: definicje
    z plikow gry maja po kilkaset wlasciwosci na przedmiot i te same szablony wracaja
    przy kazdym przedmiocie."""
    klucz = (prop["property"], prop["type"],
             (prop.get("format") or {}).get("input_position"), tolerant)
    gotowy = _REGEX_CACHE.get(klucz)
    if gotowy is not None:
        return gotowy
    rx = _zbuduj_regex(prop, tolerant)
    _REGEX_CACHE[klucz] = rx
    return rx


def _zbuduj_regex(prop: dict, tolerant: bool):
    t = normalize(prop["property"])
    if "{{" not in t:
        left = (prop.get("format") or {}).get("input_position") == "left"
        if prop["type"] == "number" and left:   # np. "to Cold Arrow (Amazon Only)" -> "+2 to Cold Arrow ..."
            t = "+{{value}} " + t
        elif prop["type"] == "number":
            # "Defense" -> "Defense: 134", ale liczba moze sie w tooltipie wcale nie pojawic:
            # "Monster Lightning Immunity is Sundered" to na Traderie pole liczbowe (300), a w grze
            # tylko napis. Dlatego wartosc jest opcjonalna - ale tylko gdy linia na niej sie konczy,
            # inaczej "Defense per Level 2" udawaloby samo "Defense".
            esc = re.escape(t).replace(r"\ ", r"[\s:]+")
            return re.compile(r"^" + esc + r"(?:[\s:]+(?P<value>-?\d+)\b|\s*$)")
        else:                         # bool, np. "Ethereal"
            return re.compile(r"^" + re.escape(t).replace(r"\ ", r"[\s:]+") + r"\b")
    parts = re.split(r"(\{\{\w+\}\})", t)
    rx, seen, sign_used = "", set(), False
    for part in parts:
        m = re.fullmatch(r"\{\{(\w+)\}\}", part)
        if m:
            key = m.group(1)
            # powtorzony placeholder (np. 11/11 charges) - drugi raz bez nazwy
            rx += r"(?:-?\d+)" if key in seen else rf"(?P<{key}>-?\d+)"
            seen.add(key)
        else:
            if tolerant and not sign_used and part.endswith(("+", "-")):
                part = part[:-1]
                rx += re.escape(part).replace(r"\ ", r"[\s:]+") + r"(?P<sign>[+-])?"
                sign_used = True
            else:
                rx += re.escape(part).replace(r"\ ", r"[\s:]+")
    return re.compile(r"^" + rx + r"$")


STOP = {"to", "by", "of", "the", "on", "a", "an"}


def words(text: str) -> frozenset:
    """Zestaw slow bez wartosci i slow funkcyjnych - dopasowanie niezalezne od szyku."""
    return frozenset(w for w in stem(text).split() if w not in STOP)


COLOR_RX = re.compile(r"\[color=[^\]]+\]([^\[]*)\[/color\]")
RANGE_RX = re.compile(r"(-?\d+)\s*(?:-|to)\s*(-?\d+)")


def fix_range(lo: int, hi: int):
    """'-5-8%' to zakres 5..8 (stat ujemny), a nie -5..8. Wartosci statow typu '-{{value}}%'
    przechowujemy jako dodatnie, wiec zakres tez sprowadzamy do dodatnich."""
    if lo < 0 < hi or (lo < 0 and hi < 0):
        lo, hi = abs(lo), abs(hi)
    return lo, hi


def range_parts(description: str):
    """Wszystkie zmienne staty z opisu: lista grup, kazda grupa = [(slowa, min, max, etykieta)].
    Grupa z kilkoma pozycjami = stat do wyboru ('A or B' albo naglowek 'One of the following' + punkty)."""
    groups, one_of = [], None
    for raw in (description or "").splitlines():
        line = raw.replace("**", "").strip()
        if re.search(r"one of the following", line, flags=re.I):
            one_of = []                       # kolejne punkty to alternatywy jednej grupy
            groups.append(one_of)
            continue
        bullet = line.startswith("\u2022")
        line = line.replace("\u2022", " ").strip()
        if one_of is not None and not bullet:
            one_of = None                     # koniec listy alternatyw
        group = []
        for part in re.split(r"\s+or\s+", line, flags=re.I):
            v = re.search(r"\(varies\)", part, flags=re.I)
            if v:                             # runewordy: '+25-35% Faster Cast Rate (varies)'
                r = RANGE_RX.search(part)
                if not r:
                    continue
                rest = RANGE_RX.sub(" ", part.replace(v.group(0), " "))
            else:
                m = COLOR_RX.search(part)
                if not m:
                    continue
                r = RANGE_RX.search(m.group(1))
                if not r:
                    continue
                rest = COLOR_RX.sub(" ", part[:m.start()] + " " + part[m.end():])
            lo, hi = fix_range(int(r.group(1)), int(r.group(2)))
            label = re.sub(r"\s+", " ", re.sub(r"[+%]", " ", rest)).strip(" :")
            label = re.sub(r"^to ", "", label, flags=re.I)
            group.append((words(rest), min(lo, hi), max(lo, hi), label))
        if not group:
            continue
        if one_of is not None:
            one_of.extend(group)
        else:
            groups.append(group)
    return [g for g in groups if g]


def parse_ranges(description: str):
    """Zakresy zmiennych statow z opisu. Zwraca (zakresy {slowa: (min, max)}, grupy [[slowa, ...], ...]).
    Wystarczy, ze w przedmiocie wystapi jedna pozycja z kazdej grupy."""
    ranges, groups = {}, []
    for g in range_parts(description):
        for key, lo, hi, _ in g:
            ranges[key] = (lo, hi)
        groups.append([key for key, _, _, _ in g])
    return ranges, groups


CLASS_WORDS = {"amazon", "sorceress", "necromancer", "paladin", "barbarian", "druid", "assassin", "warlock",
               "class", "only"}


def range_key(ws: frozenset, ranges: dict):
    """Klucz zakresu dla zestawu slow: dokladnie albo w przyblizeniu. Dopiski klasowe ('(Amazon Only)',
    '(Class Only)') sa pomijane - Traderie raz je pisze, raz nie."""
    if ws in ranges:
        return ws
    core = ws - CLASS_WORDS
    best, score = None, 0.0
    for k in ranges:
        kc = k - CLASS_WORDS
        if kc and kc == core:
            return k
        common = len(core & kc)
        j = common / max(1, len(core | kc))
        if common >= 2 and j >= 0.6 and j > score:
            best, score = k, j
    return best


def ranges_expected(description: str) -> bool:
    """Czy opis zawiera kolorowe zakresy (czyli przedmiot MA zmienne staty)."""
    d = description or ""
    return (any(RANGE_RX.search(m.group(1)) for m in COLOR_RX.finditer(d))
            or bool(re.search(r"\(varies\)", d, flags=re.I)))


def parse_req_level(description: str):
    m = re.search(r"Req\. Level:\s*(\d+)", description)
    return int(m.group(1)) if m else None


NOT_BASES = {"uniques", "sets", "runewords", "runes", "gems"}
BASE_WORDS = ("ring", "amulet", "jewel", "charm", "circlet", "coronet", "tiara", "diadem")


def find_base(lines: list):
    """Baza przedmiotu magic/rare na Traderie. Zwraca (definicja, indeks pierwszej linii ze statami, 'rare'|'magic')
    albo (None, 2, None). Rare: druga linia tooltipa to baza ('RING', 'JARED'S STONE').
    Magic: baza jest w nazwie ('Russet Grand Charm of Life') - szukamy najdluzszego pasujacego fragmentu."""
    def ok(cand):
        it = get_item(plain(cand).strip().title().replace("'S ", "'s "))
        return it if it and it.get("type") not in NOT_BASES else None

    if len(lines) > 1 and not re.search(r"\d", lines[1]) and not is_ui_line(lines[1]):
        it = ok(lines[1])
        if it:
            return it, 2, "rare"
    words = re.sub(r"[^a-z' ]", " ", plain(lines[0]).lower()).split()
    if "of" in words:
        words = words[:words.index("of")]          # "... of Life" - sufiks nie jest czescia bazy
    spans = [" ".join(words[i:i + n]) for n in range(min(4, len(words)), 0, -1) for i in range(len(words) - n + 1)]
    spans.sort(key=lambda sp: (not any(w in sp for w in BASE_WORDS), -len(sp.split())))
    for sp in spans[:8]:
        it = ok(sp)
        if it:
            return it, 1, "magic"
    return None, 2, None


# ---------- glowna logika ----------
def map_item(ocr: dict) -> dict:
    lines = ocr["lines"]
    # nazwa przedmiotu = pierwsza linia, ktora nie jest napisem interfejsu (zakladka skrzyni itp.)
    start = 0
    while start < min(6, len(lines) - 1) and (is_ui_line(lines[start])
                                                 or any(re.search(p, normalize(lines[start])) for p in IGNORE)):
        start += 1
    lines = lines[start:]
    name = plain(lines[0]).strip().title().replace("'S ", "'s ")
    out = {"source": ocr["file"], "ocr_name": lines[0], "warnings": [], "unmatched": [], "properties": []}

    if any(normalize(l) == "unidentified" for l in lines):
        out["skipped"] = "niezidentyfikowany - pominiety"
        return out

    hint = ocr.get("rarity_guess", "")
    rarity, first = None, 2          # first = indeks pierwszej linii ze statami
    item = get_item(name)            # nazwa rare/magic jest losowa, wiec dokladna nazwa z Traderie = unikat/set/baza
    if not item and slugify(name) in LOOKUP_FAILED:
        out["warnings"].append(f"nie udalo sie pobrac '{name}' z Traderie (blad polaczenia) - "
                               "sprobuj odczytac ponownie, zanim wystawisz")
        out["needs_review"] = True
        return out
    if not item and hint not in ("unique/runeword", "set"):
        # magic/rare: losowa nazwa. Na Traderie wystawia sie je jako baze (Ring, Grand Charm...) z Rarity.
        # Kolor nazwy bywa zle rozpoznany, wiec decyduje tekst: baza w 2. linii = rare, baza w nazwie = magic.
        item, first, kind = find_base(lines)
        if item:
            rarity = kind                                  # wartosc wysylana do Traderie (tylko rare/magic)
            out["rarity"] = rarity
            out["kind"] = "crafted" if (kind == "rare" and hint == "crafted") else kind   # etykieta dla uzytkownika
            out["rare_name"] = lines[0].strip().title()
            if out["kind"] == "crafted":
                out["warnings"].append("crafted: Traderie nie ma takiej rzadkosci - zostanie wystawiony jako rare, "
                                       "sprawdz przed wystawieniem")
    if not item:
        if hint in ("unique/runeword", "set"):
            out["warnings"].append(f"nie znaleziono '{name}' w Traderie, a kolor wskazuje na {hint} - sprawdz nazwe "
                                   f"(albo zapisz JSON z przegladarki jako cache/{slugify(name)}.json)")
            out["needs_review"] = True
        else:
            out["warnings"].append(f"nie rozpoznano przedmiotu ani bazy (linie: '{lines[0]}' / "
                                   f"'{lines[1] if len(lines) > 1 else ''}')")
            out["needs_review"] = True
        return out

    out.update({"item_id": item["id"], "slug": item["slug"], "name": item["name"], "type": item["type"]})
    if item.get("local"):
        # definicja z plikow gry: numery wlasciwosci sa wlasne, wiec tego listingu
        # nie wolno wystawic na Traderie (pilnuje tego traderie_post.build_payload)
        out["local"] = True
    out.setdefault("kind", {"uniques": "unique", "sets": "set", "runewords": "runeword",
                            "base": "baza"}.get(item["type"], item["type"]))
    if item["type"] == "base" and not rarity:
        out["skipped"] = "baza (bialy przedmiot) - na razie pominieta"
        return out
    props = [(p, template_regex(p), template_regex(p, tolerant=True)) for p in item["properties"]]
    word_index = {}
    for p in item["properties"]:
        if p["type"] == "number" and p["property"].count("{{") == 1:
            word_index.setdefault(words(p["property"]), p)
    desc = item.get("description") or ""
    ranges, groups = parse_ranges(desc)
    req_level = parse_req_level(desc)
    socketed = any(re.match(r"socketed", normalize(l)) for l in lines)

    # linia 0 = nazwa, linia 1 = baza (uniques/sety/rare); magic: baza jest w nazwie, staty od linii 1
    for raw in lines[first:]:
        line = normalize(raw)
        if any(re.search(p, line) for p in IGNORE):
            continue
        # "Adds 1-4 fire damage" = na Traderie dwa staty: minimalne i maksymalne obrazenia od zywiolu
        ad = re.match(r"adds (\d+)-(\d+) (fire|cold|lightning|magic|poison)?\s*damage$", line)
        if ad:
            elem = ad.group(3) or ""
            pair = []
            for which, val in (("minimum", ad.group(1)), ("maximum", ad.group(2))):
                cand = next((c for c, _, _ in props if re.search(rf"to {which} {elem}\s*damage$".replace("  ", " "),
                                                                    normalize(c["property"]))), None)
                if cand:
                    pair.append((cand, int(val)))
            if len(pair) == 2:
                for cand, val in pair:
                    out["properties"].append({"property_id": cand["property_id"], "property": cand["property"],
                                              "value": val, "variable": bool(rarity)})
                continue
        p, value, gd, flipped = None, None, {}, False
        for cand, strict, _ in props:          # 1) dokladnie jak w szablonie
            m = strict.match(line)
            if m:
                p, gd = cand, m.groupdict()
                break
        if not p:
            for cand, _, tol in props:          # 2) inny znak przed wartoscia
                m = tol.match(line)
                if m:
                    p, gd = cand, m.groupdict()
                    flipped = bool(gd.get("sign"))
                    break
        if not p:                               # 3) te same slowa w innym szyku
            nums = re.findall(r"-?\d+", line)
            cand = word_index.get(words(line))
            if cand and len(nums) == 1:
                p, gd = cand, {"value": nums[0]}
        if not p:
            rl = re.match(r"required level[\s:]+(\d+)$", line)
            if rl:
                if req_level and not rarity and int(rl.group(1)) != req_level:
                    out["warnings"].append(f"Required Level: odczytano {rl.group(1)}, powinno byc {req_level}")
                continue
            out["unmatched"].append(raw)
            continue
        if gd.get("value") is None:
            # stat bez liczby w linii: pole liczbowe dostaje wartosc domyslna z Traderie
            # (np. sunder = 300), pole logiczne (Ethereal, Half Freeze Duration) - True
            value = p["default_value"] if p["type"] == "number" and p.get("default_value") is not None else True
        else:
            value = abs(int(gd["value"])) if flipped else int(gd["value"])
        rkey = None if p["property_id"] == 1855 else range_key(words(p["property"]), ranges)  # 1855 = obrona calkowita
        rng = ranges.get(rkey) if rkey else None
        entry = {"property_id": p["property_id"], "property": p["property"], "value": value,
                 "variable": bool(rng) or bool(rarity)}     # w magic/rare kazdy stat jest losowy
        if rkey:
            entry["range_key"] = sorted(rkey)
        if flipped:
            entry["sign_in_game"] = gd["sign"]
        extra = {k: int(v) for k, v in gd.items() if k not in ("value", "sign") and v is not None}
        if extra:
            entry.update(extra)
        out["properties"].append(entry)

        # Walidacja tylko dla unikatow/setow/runewordow: opis w Traderie dotyczy wtedy tego przedmiotu.
        # Przy magic/rare opis bazy to tabela WSZYSTKICH mozliwych afiksow ("Fine | 1-3 max dmg & 10-20 AR"),
        # wiec zakresy i "stale wartosci" nie mowia nic o egzemplarzu - kazde ostrzezenie bylo falszywe.
        if not rarity:
            if rng and isinstance(value, int) and not (rng[0] <= value <= rng[1]):
                out["warnings"].append(f"{p['property']}: {value} poza zakresem {rng[0]}-{rng[1]}")
            elif (ranges and not rng and isinstance(value, int) and p.get("default_value") is not None
                  and "input_position" not in (p.get("format") or {}) and value != p["default_value"]):
                out["warnings"].append(f"{p['property']}: {value}, oczekiwano stalej wartosci {p['default_value']}")
        if p["property_id"] == 796 and req_level and not rarity and value != req_level:
            out["warnings"].append(f"Required Level: odczytano {value}, dla tego przedmiotu powinno byc {req_level}")

    # wymagane pola listingu
    by_name = {p["property"]: p["property_id"] for p in item["properties"]}
    for label, val in (("Platform", PLATFORM), ("Mode", MODE), ("Ladder", LADDER), ("Game version", GAME_VERSION)):
        if label in by_name:
            out["properties"].append({"property_id": by_name[label], "property": label, "value": val})

    required = {"Platform", "Mode", "Ladder", "Game version"}
    if rarity and "Rarity" in by_name:
        out["properties"].append({"property_id": by_name["Rarity"], "property": "Rarity", "value": rarity})
        required.add("Rarity")
    # inne wymagane pola z lista opcji (np. baza runewordu "Base Item (Shield, Sword) 4")
    # dopasowujemy do drugiej linii tooltipa (nazwa bazy, np. "MONARCH")
    base_line = normalize(lines[1]) if len(lines) > 1 else ""
    for bp in item["properties"]:
        if not bp.get("required") or not bp.get("options") or bp["property"] in required:
            continue
        opt = next((o for o in bp["options"] if normalize(o) == base_line), None)
        if opt:
            out["properties"].append({"property_id": bp["property_id"], "property": bp["property"], "value": opt})
            required.add(bp["property"])
        else:
            out["warnings"].append(f"wymagane pole '{bp['property']}': nie rozpoznano wartosci z linii '{lines[1] if len(lines) > 1 else ''}'")

    # listing = zmienne staty + cechy egzemplarza + (opcjonalnie) Defense + pola wymagane
    found = {frozenset(p["range_key"]) for p in out["properties"] if p.get("range_key")}
    if not rarity:   # magic/rare: w tabeli afiksow bazy brak wiersza nie znaczy, ze czegos nie odczytano
        for group in groups:
            if not any(k in found for k in group):
                label = " / ".join(" ".join(sorted(k)) + " ({}-{})".format(*ranges[k]) for k in group)
                out["warnings"].append(f"nie odczytano zmiennego statu: {label}")
        if not ranges and ranges_expected(desc):
            out["warnings"].append("opis Traderie ma zakresy, ale parser ich nie rozczytal - przeslij cache/"
                                   f"{item['slug']}.json do analizy")
    if socketed and out["unmatched"]:
        out["notes"] = ["przedmiot ma gniazda - niedopasowane linie moga pochodzic z runy/klejnotu w gniezdzie"]
    out["listing"] = [
        {"property_id": p["property_id"], "value": p["value"], **{k: v for k, v in p.items()
         if k not in ("property_id", "property", "value", "variable", "sign_in_game", "range_key")}}
        for p in out["properties"]
        if p.get("variable") or p["property"] in LISTING_FLAGS or p["property"] in required
        or (INCLUDE_DEFENSE and p["property_id"] == 1855)
    ]

    out["needs_review"] = bool(out["warnings"] or ocr.get("needs_review"))
    return out


def run(folder: Path, verbose: bool = True):
    files = sorted(p for p in folder.glob("*.json")
                   if not p.name.endswith((".listing.json", ".raw.json")))
    ready, review, skipped = [], [], []
    for f in files:
        ocr = json.loads(f.read_text(encoding="utf-8"))
        if "lines" not in ocr or not ocr["lines"]:
            continue
        out_file = f.with_suffix(".listing.json")
        prev = {}
        if out_file.exists():
            prev = json.loads(out_file.read_text(encoding="utf-8"))
            if prev.get("posted"):
                continue  # juz wystawiony - nie ruszamy (inaczej zniknalby znacznik i przedmiot poszedlby drugi raz)
        res = map_item(ocr)
        for key in KEEP_ON_REMAP:   # to, co wpisal uzytkownik, nie moze zniknac po ponownym odczycie
            if prev.get(key) is not None and res.get(key) is None:
                res[key] = prev[key]
        out_file.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

        if res.get("skipped"):
            skipped.append(res["ocr_name"])
            continue
        (review if res.get("needs_review") else ready).append(res.get("name", res["ocr_name"]))

        if not verbose:
            if res.get("needs_review"):
                why = res["warnings"] or ["odczyty OCR niezgodne - sprawdz screen"]
                print(f"   ! {res.get('name', res['ocr_name'])} ({f.stem}): " + "; ".join(why))
            continue
        flag = "  !!! REVIEW" if res.get("needs_review") else ""
        print(f"\n=== {res.get('name', res['ocr_name'])}  [{res.get('type', '?')} / {res.get('slug', '?')} / {res.get('item_id', '?')}]{flag}")
        listed = {p["property_id"] for p in res.get("listing", [])}
        for p in res["properties"]:
            extra = {k: v for k, v in p.items() if k not in ("property_id", "property", "value", "variable", "range_key")}
            mark = "ZMIENNY" if p.get("variable") else ("listing" if p["property_id"] in listed else "staly  ")
            print(f"   [{mark}] {p['property_id']:>5}  {p['property']}  = {p['value']}{'  ' + str(extra) if extra else ''}")
        for w in res["warnings"]:
            print(f"   UWAGA: {w}")
        for u in res["unmatched"]:
            print(f"   (pominieto, brak w Traderie: {u})")
        for n in res.get("notes", []):
            print(f"   info: {n}")

    print("\n" + "=" * 60)
    print(f"Gotowe do wystawienia: {len(ready)}")
    print(f"Do sprawdzenia:        {len(review)}" + (f"  ({', '.join(review)})" if review else ""))
    print(f"Pominiete (magic/rare/bazy): {len(skipped)}" + (f"  ({', '.join(skipped)})" if skipped else ""))


def main():
    run(Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots"))


if __name__ == "__main__":
    main()
