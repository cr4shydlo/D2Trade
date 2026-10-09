"""
traderie_post.py - wystawianie ofert na Traderie z plikow .listing.json (z traderie_map.py).

Uzycie:
    py traderie_post.py screenshots          # PODGLAD: pokazuje, co zostaloby wyslane (nic nie wysyla)
    py traderie_post.py screenshots --send   # faktyczne wystawianie
    dodaj --no-prices, zeby nie pobierac podpowiedzi cen z aktywnych ofert

Najpierw pyta o ceny wszystkich przedmiotow, potem po jednym potwierdzeniu wystawia je sam
(z przerwami miedzy ofertami). Skladnia ceny:
    sur            -> 1x Sur Rune
    ist+mal        -> Ist Rune ORAZ Mal Rune (razem)
    2 ist          -> 2x Ist Rune
    3 pamy         -> 3x Perfect Amethyst
    ber | jah      -> Ber Rune ALBO Jah Rune (alternatywy)
    offer          -> bez ceny, "Ask for Offers"
    [Enter]        -> ostatnio uzyta cena dla tego przedmiotu (jesli jest)
    s              -> pomin ten przedmiot,  q -> zakoncz

Autoryzacja: plik secrets/traderie_auth.txt obok skryptu, z liniami naglowkow skopiowanymi
z DevTools (np. "Authorization: Bearer ..." albo "Cookie: ..."). Ten plik to dostep
do Twojego konta - nie wysylaj go nikomu i nie wklejaj do czatu.
"""
import sys
import json
import time
import random
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from pathlib import Path

import traderie_map as tm
import traderie_price as tpr

PRICES_FILE = Path("prices.json")      # zapamietane ceny per przedmiot
POSTED_FILE = Path("posted.json")      # rejestr wystawionych przedmiotow (po zawartosci, nie po pliku)


def fingerprint(lst: dict) -> str:
    """Odcisk przedmiotu: nazwa + wszystkie wystawiane wartosci. Drugi screen tego samego przedmiotu da ten sam odcisk."""
    vals = sorted((e["property_id"], str(e["value"])) for e in lst.get("listing", []))
    return json.dumps([lst.get("slug"), vals])


def describe(lst: dict, item: dict):
    """(ustawienia, staty) do wyswietlenia, np. (['PC', 'Ladder'], ['Enhanced Defense 178', ...])."""
    defs = {p["property_id"]: p for p in item["properties"]} if item else {}
    settings, stats = [], []
    for e in lst.get("listing", []):
        d = defs.get(e["property_id"]) or {"property": e.get("property", str(e["property_id"]))}
        if d.get("required") or d.get("property") in REQUIRED | {"Ethereal", "Unidentified"}:
            flags = {"Ethereal": "ETH", "Unidentified": "UNID"}
            settings.append(flags.get(d.get("property"), str(e["value"])))
        else:
            stats.append(f"{tpr.stat_name(d.get('property', str(e['property_id'])))} {e['value']}")
    return settings, stats


def load_registry(folder: Path) -> dict:
    reg = json.loads(POSTED_FILE.read_text(encoding="utf-8")) if POSTED_FILE.exists() else {}
    # przedmioty wystawione przed wprowadzeniem rejestru
    for f in folder.glob("*.listing.json"):
        lst = json.loads(f.read_text(encoding="utf-8"))
        if lst.get("posted"):
            reg.setdefault(fingerprint(lst), {"name": lst.get("name"), **lst["posted"], "source": f.name,
                                              "stats": describe(lst, tm.get_item(lst["name"]))[1]})
    return reg


def save_registry(reg: dict):
    POSTED_FILE.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
DELAY = (45, 90)                       # losowa przerwa miedzy wystawieniami (s)
REFRESH_DELAY = (8, 15)                # losowa przerwa miedzy odnowieniami ofert (s)
                                       # krotsza niz DELAY: odnowienie nie tworzy nowej oferty
# Odnawianie oferty. Metoda to PUT - tak wysyla to strona (jak /listings/toggle).
# Przy POST serwer zwraca 404 "Can't find ... on this server!", czyli ten sam komunikat co przy
# nieznanej sciezce - stad mylny trop. {api} = https://traderie.com/api/diablo2resurrected.
REFRESH_PATH = "{api}/listings/refresh"
REFRESH_METHOD = "PUT"
REQUIRED = {"Platform", "Mode", "Ladder", "Game version"}


def load_auth() -> dict:
    auth = tm.load_auth()
    if not auth:
        sys.exit(f"Brak lub pusty plik {tm.AUTH_FILE} - patrz opis na gorze skryptu.")
    return auth


def search_items(query: str, limit: int = 15) -> list:
    """Wyszukiwarka przedmiotow Traderie -> lista nazw."""
    import urllib.parse
    d = tm.http_json(f"{tm.API}/items?search={urllib.parse.quote(query)}")
    return [it["name"] for it in (d.get("items") or []) if it.get("name")][:limit]


def rune_item(token: str):
    """Przedmiot uzyty jako cena: 'sur' -> Sur Rune, 'pamy' -> Perfect Amethyst,
    'key of terror' -> Key of Terror, albo cokolwiek z wyszukiwarki Traderie."""
    t = token.strip().lower()
    alias = {v: k for k, v in tpr.ALIASES.items()}
    if t in alias:
        return tm.get_item(alias[t])
    if " " not in t:                                   # pojedyncze slowo = najpierw runa
        it = tm.get_item(t.title() + " Rune")
        if it:
            return it
    it = tm.get_item(t.title())
    if it and tm.normalize(it.get("name", "")) == tm.normalize(t):
        return it
    try:                                               # ostatecznie wyszukiwarka - dokladna nazwa
        for name in search_items(t):
            if tm.normalize(name) == tm.normalize(t):
                return tm.get_item(name)
    except Exception:
        pass
    return it


def parse_price(text: str):
    """Zwraca (lista przedmiotow ceny, make_offer) albo rzuca ValueError."""
    text = text.strip().lower()
    if text == "offer":
        return [], True
    price, index = [], 0
    for group, alt in enumerate(text.split("|")):
        for part in alt.split("+"):
            part = part.strip()
            qty = 1
            if part[:1].isdigit():
                q, part = part.split(None, 1)
                qty = int(q)
            it = rune_item(part)
            if not it:
                raise ValueError(f"nie znaleziono przedmiotu '{part}'")
            price.append({
                "quantity": qty, "diy": False, "canCatalog": False,
                "properties": [p for p in it["properties"] if p.get("required")],
                "variant": None, "value": it["id"], "label": it["name"], "variants": None,
                "img_url": it.get("img"), "index": index, "group": group,
            })
            index += 1
    if not price:
        raise ValueError("pusta cena")
    return price, False


def build_properties(listing: dict, item: dict) -> list:
    defs = {p["property_id"]: p for p in item["properties"]}
    out = []
    for e in listing["listing"]:
        d = defs.get(e["property_id"])
        if not d:
            continue
        value = e["value"]
        if d["property"] == "Ladder":
            value = (value == "Ladder")          # Traderie: Ladder = true, Non Ladder = false
        # Kszalt pozycji po zmianie API (pazdziernik 2026), zdjety z zadania samej strony:
        # nazwa jako 'name', wartosc pod kluczem o nazwie typu ('number' / 'string' / 'bool').
        # Pola 'property' i 'option' sa w nowym schemacie zadeklarowane jako "never" - ich
        # obecnosc to 400, a brak wartosci pod kluczem typu tez ("properties.2.bool:
        # expected boolean, received undefined").
        if d["property"] == "Game version":
            # ta jedna pozycja idzie cala definicja (tak robi strona) - bez 'property', bo to
            # pole jest zakazane, i bez 'preferred' na wierzchu, ktorego strona tu nie wysyla
            echo = {k: v for k, v in d.items() if k != "property"}
            out.append({**echo, "id": d["property_id"], "name": d["property"], d["type"]: value})
            continue
        prop = {"id": d["property_id"], "name": d["property"], "type": d["type"], d["type"]: value}
        if d["property"] in REQUIRED:
            prop["preferred"] = True
        out.append(prop)
    return out


LOCAL_LISTING = ("Ten przedmiot zostal rozpoznany z plikow gry, bez Traderie - numery wlasciwosci sa "
                 "wlasne, wiec oferta byla by bledna. Wklej token w Ustawieniach i odczytaj screena "
                 "ponownie, zeby go wystawic.")


def build_payload(listing: dict, item: dict, price: list, make_offer: bool) -> dict:
    if listing.get("local") or (item or {}).get("local"):
        raise ValueError(LOCAL_LISTING)
    return {
        "acceptListingPrice": False, "captcha": "", "captchaManaged": False,
        "currencyGroupPrices": [], "diy": False, "endTime": "", "free": False,
        "item": listing["item_id"], "itemMode": None, "itemType": listing["type"],
        "makeOffer": make_offer, "needMaterials": False, "offerBells": False, "offerNmt": False,
        "offerWishlist": False, "offerWishlistId": "", "selling": True, "standingListing": False,
        "stockListing": False, "touchTrading": False, "wishlist": "", "amount": "1",
        "items": price,
        "properties": build_properties(listing, item),
    }


def post(payload: dict, auth: dict):
    req = urllib.request.Request(
        f"{tm.API}/listings/create",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"User-Agent": tm.UA, "Content-Type": "application/json", "Accept": "application/json",
                 "Origin": "https://traderie.com", "Referer": "https://traderie.com/diablo2resurrected",
                 **auth},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # powod odmowy Traderie podaje w CIELE odpowiedzi; bez tego z okna leci goly
        # "HTTP Error 400: Bad Request" ze sladem wyjatku, a do_post() umie pokazac powod
        return e.code, e.read().decode("utf-8", "replace")


def ask_prices(todo: list, hints: bool, prices: dict, registry: dict = None) -> list:
    """Faza 1: pyta o ceny wszystkich przedmiotow. Zwraca [(plik, listing, item, cena_tekst, cena, make_offer)]."""
    plan = []
    # podpowiedzi cen pobierane w tle z wyprzedzeniem (2 naraz), zeby nie czekac miedzy przedmiotami
    pool = ThreadPoolExecutor(max_workers=2)
    futures = [pool.submit(lambda l: tpr.suggest(l, tm.get_item(l["name"])), lst)
               if hints and not lst.get("planned_price") else None
               for _, lst in todo]
    for n, (f, lst) in enumerate(todo, 1):
        item = tm.get_item(lst["name"])
        settings, stats = describe(lst, item)
        print(f"\n[{n}/{len(todo)}] {lst['name']}   [{' | '.join(settings)}]")
        if not hints and stats:
            print("   " + ", ".join(stats))

        dup = (registry or {}).get(fingerprint(lst))
        if dup:
            print(f"   ! wyglada na przedmiot juz wystawiony {dup.get('time', '')} za {dup.get('price', '?')} "
                  f"({dup.get('source', '?')})")
            print(f"     wtedy: {', '.join(dup.get('stats') or []) or '(brak statow w listingu)'}")
            print(f"     teraz: {', '.join(stats) or '(brak statow w listingu)'}")
            if not stats:
                print("     (zadnych zmiennych statow w listingu - pewnie nie zostaly odczytane; sprawdz screen)")
            hint_price = ""
            if futures[n - 1] is not None:
                try:
                    hint = futures[n - 1].result()
                    print(hint["text"])
                    hint_price = hint["price"]
                except Exception:
                    pass
            try:
                ans = input(f"   cena [Enter = pomin{', podpowiedz: ' + hint_price if hint_price else ''}]: ").strip()
            except EOFError:
                return plan
            if ans.lower() == "q":
                return plan
            if not ans or ans.lower() == "s":
                print("   pominieto")
                continue
            try:
                price, make_offer = parse_price(ans)
            except ValueError as e:
                print(f"   ! {e} - pomijam")
                continue
            lst["planned_price"] = ans
            f.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
            plan.append((f, lst, item, ans, price, make_offer))
            continue

        # domyslna cena: zaplanowana wczesniej (przerwany przebieg) > podpowiedz > ostatnio uzyta
        default = lst.get("planned_price") or prices.get(lst["slug"])
        if futures[n - 1] is not None:
            try:
                hint = futures[n - 1].result()
            except Exception as e:
                hint = {"text": f"   (podpowiedz ceny nie powiodla sie: {e})", "price": ""}
            print(hint["text"])
            if hint["price"]:
                if default and default != hint["price"]:
                    print(f"   (ostatnio wystawiales za: {default})")
                default = hint["price"]
        while True:
            try:
                ans = input(f"   cena{f' [Enter = {default}]' if default else ''}: ").strip() or (default or "")
            except EOFError:
                return plan
            if ans.lower() == "q":
                return plan
            if ans.lower() in ("s", ""):
                print("   pominieto")
                break
            try:
                price, make_offer = parse_price(ans)
            except ValueError as e:
                print(f"   ! {e}")
                continue
            lst["planned_price"] = ans            # zapamietane na wypadek przerwania
            f.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
            plan.append((f, lst, item, ans, price, make_offer))
            break
    return plan


SESSION_EXPIRED = ("Sesja Traderie wygasla (Unauthorized jwt). Skopiuj ponownie naglowek Authorization "
                   "z DevTools (widok Nieprzetworzone) do secrets/traderie_auth.txt.")


def is_expired(body: str) -> bool:
    return "unauthorized jwt" in (body or "").lower()


def _sell_call(listing_id: str, auth: dict, remove: bool):
    req = urllib.request.Request(
        f"{tm.API}/sell",
        data=json.dumps({"listing": str(listing_id), "selling": True, "remove": remove}).encode("utf-8"),
        method="POST",
        headers={"User-Agent": tm.UA, "Content-Type": "application/json", "Accept": "application/json",
                 "Origin": "https://traderie.com", "Referer": "https://traderie.com/diablo2resurrected", **auth},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
    if is_expired(body):
        return False, SESSION_EXPIRED
    try:
        resp = json.loads(body)
    except json.JSONDecodeError:
        resp = {}
    if resp.get("error"):
        return False, f"Traderie: {resp['error']}"
    if not resp.get("success"):
        return False, f"nieoczekiwana odpowiedz: {body[:200]}"
    return True, body[:200]


def mark_sold(listing_id: str, auth: dict):
    """Oznacza oferte jako sprzedana na Traderie (jak przycisk Mark Sold). Zwraca (ok, komunikat)."""
    return _sell_call(listing_id, auth, remove=False)


def remove_listing(listing_id: str, auth: dict):
    """Usuwa oferte z Traderie (jak przycisk Remove). Zwraca (ok, komunikat)."""
    return _sell_call(listing_id, auth, remove=True)


def set_visible(listing_id: str, visible: bool, auth: dict):
    """Ukrywa (visible=False) albo przywraca (True) oferte na Traderie - jak Hide/Unhide Listing."""
    req = urllib.request.Request(
        f"{tm.API}/listings/toggle",
        data=json.dumps({"listing": str(listing_id), "active": bool(visible)}).encode("utf-8"),
        method="PUT",   # tak wysyla strona (Hide/Unhide Listing)
        headers={"User-Agent": tm.UA, "Content-Type": "application/json", "Accept": "application/json",
                 "Origin": "https://traderie.com", "Referer": "https://traderie.com/diablo2resurrected", **auth},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
    if is_expired(body):
        return False, SESSION_EXPIRED
    try:
        resp = json.loads(body)
    except json.JSONDecodeError:
        resp = {}
    if not resp.get("success"):
        return False, resp.get("error") or f"nieoczekiwana odpowiedz: {body[:200]}"
    return True, "ok"


def refresh_listing(listing_id: str, auth: dict):
    """Odnawia oferte na Traderie (przycisk ze strzalkami na stronie) - wraca na gore listy.
    Traderie pozwala na to raz na ~20 h od ostatniego wystawienia/odnowienia (traderie_sync.RELIST_HOURS).
    Odpowiedz strony: {"success":true,"version":"1.3.0"}."""
    req = urllib.request.Request(
        REFRESH_PATH.format(api=tm.API, id=listing_id),
        data=json.dumps({"listing": str(listing_id)}).encode("utf-8"),
        method=REFRESH_METHOD,
        headers={"User-Agent": tm.UA, "Content-Type": "application/json", "Accept": "application/json",
                 "Origin": "https://traderie.com", "Referer": "https://traderie.com/diablo2resurrected", **auth},
    )
    status = 0
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8", "replace")
    if is_expired(body):
        return False, SESSION_EXPIRED
    try:
        resp = json.loads(body)
    except json.JSONDecodeError:
        resp = {}
    if resp.get("error"):
        return False, f"Traderie: {resp['error']}"
    # Zadnych zalozen: za sukces uznajemy tylko wyrazne potwierdzenie. Odpowiedz bez bledu nie
    # znaczy, ze oferta zostala odnowiona - raz zdarzylo sie, ze licznik na Traderie nie drgnal,
    # a program pokazal "odnowiono". Tresc wraca do logu, bo to jedyny slad, co odpowiedzial serwer.
    if resp.get("success") is True or (isinstance(resp.get("listing"), (str, int, dict)) and status == 200):
        return True, "ok"
    return False, f"HTTP {status}, odpowiedz: {body[:300] or '(pusta)'}"


def unregister(lst: dict):
    """Usuwa przedmiot z rejestru wystawionych (po zdjeciu oferty mozna go wystawic ponownie bez ostrzezenia)."""
    if POSTED_FILE.exists():
        reg = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        if reg.pop(fingerprint(lst), None) is not None:
            save_registry(reg)


def run(folder: Path, send: bool = False, hints: bool = True):
    auth = load_auth() if send else {}
    prices = json.loads(PRICES_FILE.read_text(encoding="utf-8")) if PRICES_FILE.exists() else {}
    registry = load_registry(folder)

    todo = []
    for f in sorted(folder.glob("*.listing.json")):
        lst = json.loads(f.read_text(encoding="utf-8"))
        if lst.get("skipped") or lst.get("needs_review") or lst.get("posted") or "listing" not in lst:
            continue
        todo.append((f, lst))
    if not todo:
        print("   nic do wystawienia")
        return

    print(f"Wycena - przedmiotow: {len(todo)}   (Enter = podpowiedz, s = pomin, q = koniec wyceny)")
    plan = ask_prices(todo, hints, prices, registry)
    if not plan:
        print("\n   nic nie wybrano do wystawienia")
        return

    print("\n" + "=" * 60)
    for _, lst, _, ans, _, _ in plan:
        print(f"   {lst['name']:<34} {ans}")
    if not send:
        print(f"\nPODGLAD - {len(plan)} przedmiotow z cenami jak wyzej. Uruchom z --send, zeby wystawic.")
        return
    avg = sum(DELAY) / 2
    print(f"\nDo wystawienia: {len(plan)}, potrwa ok. {round((len(plan) - 1) * avg / 60) or 1} min.")
    try:
        confirm = input("Wystawic? [t/N]: ").strip().lower()
    except EOFError:
        confirm = ""
    if confirm not in ("t", "tak", "y"):
        print("   anulowano - ceny zostaly zapamietane, przy nastepnym uruchomieniu beda domyslne")
        return

    # Faza 2: wystawianie bez udzialu uzytkownika
    ok = 0
    try:
        for i, (f, lst, item, ans, price, make_offer) in enumerate(plan, 1):
            if i > 1:
                wait = random.randint(*DELAY)
                print(f"   ... {wait} s", flush=True)
                time.sleep(wait)
            payload = build_payload(lst, item, price, make_offer)
            try:
                status, body = post(payload, auth)
            except Exception as e:
                print(f"[{i}/{len(plan)}] {lst['name']}: ! blad wysylania: {e}")
                print("   Przerywam (wygasla sesja? captcha?). Reszta zostaje z zapamietanymi cenami.")
                break
            try:
                resp = json.loads(body)
            except json.JSONDecodeError:
                resp = {}
            if not resp.get("success") or not resp.get("listing"):
                why = "captcha" if "captcha" in body.lower() else (SESSION_EXPIRED if is_expired(body) else "nieoczekiwana odpowiedz")
                print(f"[{i}/{len(plan)}] {lst['name']}: ! {why} ({status}): {body[:200]}")
                print("   Przerywam. Reszta zostaje z zapamietanymi cenami.")
                break
            lst["posted"] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "price": ans, "listing_id": resp["listing"]}
            lst.pop("planned_price", None)
            f.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
            registry[fingerprint(lst)] = {"name": lst["name"], **lst["posted"], "source": f.name,
                                          "stats": describe(lst, item)[1]}
            save_registry(registry)
            prices[lst["slug"]] = ans
            PRICES_FILE.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
            ok += 1
            print(f"[{i}/{len(plan)}] {lst['name']}: wystawiono za {ans}", flush=True)
    except KeyboardInterrupt:
        print("\n   przerwano (Ctrl+C) - reszta zostaje z zapamietanymi cenami")
    print(f"\nWystawiono: {ok}/{len(plan)}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(Path(args[0] if args else "screenshots"), send="--send" in sys.argv, hints="--no-prices" not in sys.argv)


if __name__ == "__main__":
    main()
