"""
traderie_price.py - podpowiedz ceny na podstawie aktywnych ofert na Traderie.

Uzycie samodzielne (podglad podpowiedzi dla gotowych przedmiotow):
    py traderie_price.py screenshots
Uzywany tez przez traderie_post.py (podpowiedz jako domyslna cena).

Jak liczy:
  - pobiera aktywne oferty przedmiotu (kilka stron),
  - zostawia te z tymi samymi ustawieniami (platforma, tryb, ladder, wersja gry, eth, baza),
  - dzieli na "podobne" (zmienne staty blisko Twoich) i "bez podanych statow",
  - przelicza cene kazdej oferty na wspolna jednostke (pole 'value' run w Traderie);
    przy alternatywach ("A albo B") liczy tansza,
  - podaje mediane i najblizsza jej cene w runach.
Uwaga: to ceny WYWOLAWCZE aktywnych ofert, nie ceny faktycznej sprzedazy.
"""
import re
import sys
import json
import time
import urllib.parse
import statistics
from pathlib import Path

import traderie_map as tm

PAGES = 3                 # ile stron aktywnych ofert pobierac (po 50), gdy brak danych z price-check
PRICE_CHECK_LIMIT = 100   # ile ostatnich transakcji analizuje price-check
MIN_TRADES = 5            # ponizej tylu wycenionych transakcji price-check jest malo wiarygodny
# format jak w przegladarce; filtry statow: prop_<ID>Min / prop_<ID>Max
PRICE_CHECK_QUERY = "{api}/items/price-check?item={item}&limit={limit}{filters}"
PAGE_DELAY = 1.5          # przerwa miedzy stronami (s)
# format zapytania jak w przegladarce; priceValues=true dodaje wartosci run ('value') do cen
LISTINGS_QUERY = ("{api}/listings?itemTags=true&item={item}&selling=true&auction=false"
                  "&page={page}&priceValues=true{filters}")
SETTINGS = {"Platform", "Mode", "Ladder", "Game version", "Ethereal"}
DEFENSE_IDS = {399, 1855}  # Traderie ma dwie wlasciwosci obrony - traktujemy jak jedna

RUNE_VALUES = {}          # waluta (runy + Perfect Amethyst) -> wartosc; z price-check (w Ist) albo z ofert
RUNES_CACHE = Path("cache") / "rune_values.json"   # ostatnio widziane kursy - do przelicznika FG w d2jsp

# Wyniki price-check zmieniaja sie w skali dni, a serwer liczy je kilka sekund (stad timeout 60).
# Bez cache kazde otwarcie tego samego przedmiotu to nowe zapytanie. Klucz obejmuje filtry,
# bo ta sama baza z innym rzutem to inne pytanie.
PRICE_CACHE = Path("cache") / "price_check.json"
PRICE_TTL = 12 * 3600     # ile sekund wynik uznajemy za aktualny
PRICE_CACHE_MAX = 500     # ile wpisow trzymamy (najstarsze wypadaja)
ALIASES = {"Perfect Amethyst": "pamy"}   # krotkie nazwy walut w podpowiedziach (i w traderie_post)


def prop_value(p: dict):
    return {"number": p.get("number"), "string": p.get("string"), "bool": p.get("bool")}.get(p["type"])


def listing_props(l: dict) -> dict:
    out = {}
    for p in l.get("properties") or []:
        pid = 1855 if p["property_id"] in DEFENSE_IDS else p["property_id"]
        out[pid] = prop_value(p)
    return out


def load_runes() -> dict:
    """Kursy walut zapamietane przy poprzednich wycenach (zeby przelicznik FG dzialal od razu)."""
    if not RUNE_VALUES and RUNES_CACHE.exists():
        try:
            RUNE_VALUES.update(json.loads(RUNES_CACHE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return RUNE_VALUES


def save_runes():
    try:
        RUNES_CACHE.parent.mkdir(parents=True, exist_ok=True)
        RUNES_CACHE.write_text(json.dumps(RUNE_VALUES, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass          # brak kursow to nie powod, zeby przerywac wycene


def price_value(l: dict, table: dict = None):
    """Wartosc ceny oferty (tansza z alternatyw) albo None.
    Bez tabeli: pole 'value' z Traderie (jednostki HR). Z tabela: wartosci wg nazw (np. w Ist z price-check)."""
    groups = {}
    for p in l.get("prices") or []:
        if table is None and p.get("type") == "runes" and p.get("value") is not None:
            if RUNE_VALUES.get(p["name"]) != p["value"]:
                RUNE_VALUES[p["name"]] = p["value"]
                save_runes()
        v = table.get(p["name"]) if table is not None else p.get("value")
        g = groups.setdefault(p.get("group", 0), [0.0, True])
        if v is None:
            g[1] = False  # w grupie jest cos bez wyceny (np. inny przedmiot)
        else:
            g[0] += p["quantity"] * v
    vals = [v for v, ok in groups.values() if ok and v > 0]
    return min(vals) if vals else None


def price_label(l: dict) -> str:
    groups = {}
    for p in l.get("prices") or []:
        q = f"{p['quantity']} " if p["quantity"] > 1 else ""
        groups.setdefault(p.get("group", 0), []).append(q + p["name"].replace(" Rune", ""))
    return " | ".join("+".join(g) for _, g in sorted(groups.items())) or "offer"


def filters_for(listing: dict) -> str:
    """Filtry serwera jak w przegladarce: prop_Mode, prop_Ladder, prop_Game version."""
    vals = {e.get("property") or "": e["value"] for e in listing.get("properties", [])}
    f = {}
    if "Mode" in vals:
        f["prop_Mode"] = vals["Mode"]
    if "Ladder" in vals:
        f["prop_Ladder"] = "true" if vals["Ladder"] in ("Ladder", True) else "false"
    if "Game version" in vals:
        f["prop_Game version"] = vals["Game version"]
    if vals.get("Unidentified") is True or listing.get("unidentified"):
        f["prop_Unidentified"] = "true"
    return "".join(f"&{urllib.parse.quote(k)}={urllib.parse.quote(str(v))}" for k, v in f.items())


def fetch_listings(item_id: str, filters: str = "", pages: int = PAGES) -> list:
    out = []
    for page in range(pages):
        url = LISTINGS_QUERY.format(api=tm.API, item=item_id, page=page, filters=filters)
        try:
            d = tm.http_json(url)
        except Exception as e:
            print(f"   (pobieranie ofert nie powiodlo sie: {e})")
            break
        out += d.get("listings") or []
        if d.get("nextPage") in (None, False, page) or not d.get("listings"):
            break
        time.sleep(PAGE_DELAY)
    return out


NO_TRADERIE = ("ceny biora sie z transakcji na Traderie - bez tokenu ich nie ma. Jakosc rzutu "
               "wyzej policzona jest z plikow gry; cene ustal sam (np. po d2jsp)")
HIGH_ROLL = 0.85          # stat w gornych 15% zakresu = "wysoki rzut", za ktory sie doplaca
DEFENSE_FILTER_ID = 399   # tak filtruje strona price-check ("+X Defense")
DEFENSE_TOL = 0.02        # obrona +/- 2% (dla 136: 133-139)


def _price_cache_load() -> dict:
    if not PRICE_CACHE.exists():
        return {}
    try:
        return json.loads(PRICE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}   # uszkodzony cache nie moze blokowac wyceny


def _price_cache_save(cache: dict) -> None:
    teraz = time.time()
    swieze = {k: v for k, v in cache.items() if teraz - v.get("t", 0) < PRICE_TTL}
    if len(swieze) > PRICE_CACHE_MAX:
        najnowsze = sorted(swieze.items(), key=lambda kv: -kv[1].get("t", 0))[:PRICE_CACHE_MAX]
        swieze = dict(najnowsze)
    try:
        PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PRICE_CACHE.write_text(json.dumps(swieze, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"   (nie udalo sie zapisac cache price-check: {e})")


def price_check(item_id: str, filters: str, force: bool = False):
    """Podsumowanie zakonczonych transakcji z Traderie albo None.

    Wynik trafia do cache na PRICE_TTL - transakcje z ostatnich 100 sprzedazy
    nie zmieniaja sie z minuty na minute, a zapytanie jest kosztowne.
    force=True pomija cache (przycisk "sprawdz jeszcze raz")."""
    klucz = f"{item_id}|{filters}"
    cache = _price_cache_load()
    wpis = cache.get(klucz)
    if not force and wpis and time.time() - wpis.get("t", 0) < PRICE_TTL:
        return wpis.get("d")

    url = PRICE_CHECK_QUERY.format(api=tm.API, item=item_id, limit=PRICE_CHECK_LIMIT, filters=filters)
    try:
        d = tm.http_json(url, timeout=60)  # serwer liczy to kilka sekund
    except Exception as e:
        print(f"   (price-check nie powiodl sie: {e})")
        if wpis:   # lepiej podac wynik sprzed kilku godzin niz nic
            print("   (uzywam poprzedniego wyniku z cache)")
            return wpis.get("d")
        return None
    wynik = d if d.get("percentiles") else None
    # pustych odpowiedzi nie zapamietujemy - przedmiot moze sie dopiero sprzedac
    if wynik is not None:
        cache[klucz] = {"t": time.time(), "d": wynik}
        _price_cache_save(cache)
    return wynik


def short(name: str) -> str:
    return ALIASES.get(name, name.replace(" Rune", "")).lower()


def rune_combo(target: float) -> str:
    """Cena bliska wartosci target: 1-4x ta sama waluta albo dwie rozne; do 10% roznicy wygrywa prostsza.
    Pomija bardzo tanie runy (ponizej 1/10 Ist) - nikt nie placi 3x Ral."""
    ist = RUNE_VALUES.get("Ist Rune")
    floor = 0.1 * ist if ist else 0
    cur = sorted(((n, v) for n, v in RUNE_VALUES.items() if v >= floor or n in ALIASES), key=lambda kv: kv[1])
    if not cur or not target or target <= 0:
        return ""
    cands = []  # (wartosc, opis, zlozonosc, roznica wartosci skladnikow)
    for n, v in cur:
        cands.append((v, short(n), 0, 1))
        for k, cx in ((2, 1), (3, 3), (4, 4)):   # 2x prostsze niz para roznych, 3x/4x trudniejsze
            cands.append((k * v, f"{k} {short(n)}", cx, 1))
    for i, (a, va) in enumerate(cur):
        for b, vb in cur[i + 1:]:
            cands.append((va + vb, f"{short(b)}+{short(a)}", 2, vb / va))
    err = lambda c: abs(c[0] - target) / target
    close = [c for c in cands if err(c) <= 0.10]   # w granicach 10% wybieramy najprostsza cene
    val, label, _, _ = min(close, key=lambda c: (c[2], round(err(c), 2), c[3])) if close else min(cands, key=lambda c: (round(err(c), 2), c[2]))
    return label


def stat_name(prop: str) -> str:
    """'+{{value}}% Enhanced Defense' -> 'Enhanced Defense'."""
    name = re.sub(r"\s+", " ", re.sub(r"[+-]?\{\{\w+\}\}%?", "", prop)).strip(" :")
    return re.sub(r"^to ", "", name, flags=re.I)


def defense_range(description: str, eth: bool):
    rx = r"Def\. Eth\.\|\s*(\d+)-(\d+)" if eth else r"\|Defense\|\s*(\d+)-(\d+)"
    m = re.search(rx, description or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def rolls(listing: dict, item: dict):
    """Zmienne staty z jakoscia rzutu: [(pid, nazwa, wartosc, lo, hi, procent)]."""
    defs = {p["property_id"]: p for p in item["properties"]}
    ranges, _ = tm.parse_ranges(item.get("description") or "")
    vals = {e["property_id"]: e["value"] for e in listing["listing"]}
    eth = bool(vals.get(738))
    ed_variable = 425 in vals and tm.range_key(tm.words(defs.get(425, {}).get("property", "")), ranges) is not None
    out = []
    for pid, v in vals.items():
        if pid == 1855 and ed_variable:
            continue  # obrona wynika z Enhanced Defense - liczy sie rzut ED
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        if pid == 1855:
            r, name = defense_range(item.get("description"), eth), "Defense"
        else:
            d = defs.get(pid)
            k = tm.range_key(tm.words(d["property"]), ranges) if d else None
            r = ranges.get(k) if k else None
            name = stat_name(d["property"]) if d else str(pid)
        if not r:
            continue
        lo, hi = sorted((abs(r[0]), abs(r[1])))
        v = abs(v)
        pct = 1.0 if hi == lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
        out.append((pid, name, v, lo, hi, pct))
    return out


def high_filters(high: list) -> str:
    """Filtr price-check tylko dla wysokich rzutow: wartosc +/- tolerancja (w granicach zakresu)."""
    out = ""
    for pid, _, v, lo, hi, _ in high:
        if pid == 1855:
            t = max(2, round(DEFENSE_TOL * v))
            out += f"&prop_{DEFENSE_FILTER_ID}Min={v - t}&prop_{DEFENSE_FILTER_ID}Max={min(hi, v + t)}"
        else:
            t = max(1, round(0.1 * (hi - lo)))
            out += f"&prop_{pid}Min={max(lo, v - t)}&prop_{pid}Max={min(hi, v + t)}"
    return out


def fmt_pc(pc: dict) -> str:
    pct = pc["percentiles"]
    dr = pc.get("dateRange") or {}
    try:
        from datetime import date
        days = (date.fromisoformat(dr["newest"][:10]) - date.fromisoformat(dr["oldest"][:10])).days + 1
        when = f"ostatnie {days} dni" if days > 1 else "ostatni dzien"
    except Exception:
        when = "ostatnie"
    levels = " | ".join(f"{k} {rune_combo(pct[k])}" for k in ("floor", "typical", "good", "high") if pct.get(k))
    return f"transakcje ({when}, {pc['valuedTrades']} cen): {levels}"


def suggest(listing: dict, item: dict) -> dict:
    """Zwraca {'text': krotki opis, 'price': podpowiedz w skladni traderie_post albo ''}."""
    lines = []
    rl = rolls(listing, item)
    high = [r for r in rl if r[5] >= HIGH_ROLL]
    if rl:
        lines.append("   rzut: " + ", ".join(
            f"{n} {v} ({round(p * 100)}%{' WYSOKI' if p >= HIGH_ROLL else ''})" for _, n, v, _, _, p in rl))
    # Jakosc rzutu liczy sie z plikow gry, ale ceny biora sie z transakcji - a te sa tylko
    # na Traderie. Bez tokenu konczymy na ocenie rzutu; zgadywanie ceny byloby mylace.
    if tm.local_only():
        lines.append("   " + NO_TRADERIE)
        return {"text": "\n".join(lines), "price": "", "levels": {}}

    filters = filters_for(listing)
    pc, note = None, ""
    if high:
        pc = price_check(listing["item_id"], filters + high_filters(high))
        if pc and pc.get("valuedTrades", 0) >= MIN_TRADES:
            note = " - egzemplarze z wysokim rzutem"
        else:
            pc, note = None, " - za malo transakcji z wysokim rzutem, cena ogolna"
    if not pc:
        pc = price_check(listing["item_id"], filters)
    if pc and pc.get("runeValues"):
        RUNE_VALUES.clear()
        RUNE_VALUES.update({k: v for k, v in pc["runeValues"].items() if k.endswith(" Rune") or k in ALIASES})
        save_runes()      # kursy przydaja sie potem przelicznikowi FG w poscie d2jsp

    if pc and pc.get("valuedTrades", 0) >= MIN_TRADES:
        lines.append("   " + fmt_pc(pc) + note)
        pct = pc["percentiles"]
        levels = {k: rune_combo(pct[k]) for k in ("floor", "typical", "good", "high") if pct.get(k)}
        return {"text": "\n".join(lines), "price": levels.get("typical", ""), "levels": levels}

    # zapas: aktywne oferty (ceny wywolawcze), te same ustawienia
    table = pc.get("runeValues") if pc else None
    required = {p["property_id"] for p in item["properties"]
                if p.get("required") or p["property"] in SETTINGS}
    mine = {1855 if e["property_id"] in DEFENSE_IDS else e["property_id"]: e["value"] for e in listing["listing"]}
    if isinstance(mine.get(800), str):
        mine[800] = (mine[800] == "Ladder")
    vals = []
    for l in fetch_listings(listing["item_id"], filters):
        lp = listing_props(l)
        if any(pid in lp and pid in mine and lp[pid] != mine[pid] for pid in required):
            continue
        if l.get("make_offer") or not l.get("prices"):
            continue
        v = price_value(l, table)
        if v:
            vals.append(v)
    if not vals:
        lines.append("   brak danych o transakcjach i ofertach - wycen recznie")
        return {"text": "\n".join(lines), "price": ""}
    med = statistics.median(vals)
    lines.append(f"   brak transakcji - aktywne oferty (ceny wywolawcze): mediana {rune_combo(med)} ({len(vals)} ofert)")
    return {"text": "\n".join(lines), "price": rune_combo(med), "levels": {"typical": rune_combo(med)}}


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    for f in sorted(folder.glob("*.listing.json")):
        lst = json.loads(f.read_text(encoding="utf-8"))
        if lst.get("skipped") or lst.get("needs_review") or "listing" not in lst:
            continue
        item = tm.get_item(lst["name"])
        print(f"\n=== {lst['name']}")
        s = suggest(lst, item)
        print(s["text"])
        if s["price"]:
            print(f"   -> podpowiedz: {s['price']}")


if __name__ == "__main__":
    main()
