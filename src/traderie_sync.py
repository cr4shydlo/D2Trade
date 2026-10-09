"""
traderie_sync.py - oznaczanie jako sprzedanych przedmiotow, ktorych oferty zakonczyly sie na Traderie.

Przedmiot jest uznany za sprzedany tylko gdy jego oferta jest na liscie zakonczonych (completed=true)
i jednoczesnie NIE ma jej wsrod aktywnych (completed=false) - na wypadek, gdyby Traderie zignorowal filtr.
"""
import json
import time
from pathlib import Path

import traderie_map as tm

SELLER_ID = ""             # ustawia app_config.apply() z settings.json (Ustawienia -> ID konta)
BRAK_ID = ("Nie podano ID konta Traderie. Wpisz je w Ustawieniach - znajdziesz je w adresie "
           "listy swoich ofert na Traderie, po 'seller='.")
RELIST_HOURS = 20          # po tylu godzinach od wystawienia/odnowienia oferte mozna odnowic (licznik na stronie)
MAX_PAGES = 10
QUERY = ("{api}/listings?itemTags=true&selling=true&auction=false&page={page}&getMod=true"
         "&seller={seller}&completed={completed}&active=all&openOfferCheck=true")


def own_listings(completed: bool) -> dict:
    """Twoje oferty z Traderie: {id: wiersz}."""
    if not SELLER_ID:
        # bez ID zapytanie wrociloby z ofertami kogos innego albo z niczym - lepiej powiedziec wprost
        raise ValueError(BRAK_ID)
    out = {}
    for page in range(MAX_PAGES):
        d = tm.http_json(QUERY.format(api=tm.API, page=page, seller=SELLER_ID,
                                      completed="true" if completed else "false"))
        rows = d.get("listings") or []
        out.update({str(l["id"]): l for l in rows if l.get("id") is not None})
        if not rows or d.get("nextPage") in (None, False, page):
            break
        time.sleep(1.0)
    return out


def listing_ids(completed: bool) -> set:
    return set(own_listings(completed))


def hours_since(ts: str) -> float:
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def listing_status(active: dict) -> dict:
    """{id: {'relist': bool, 'hours_left': float, 'offers': int, 'hidden': bool}} dla aktywnych ofert."""
    out = {}
    for lid, l in active.items():
        age = hours_since(l.get("updated_at") or "")
        out[lid] = {"relist": age >= RELIST_HOURS, "hours_left": max(0.0, RELIST_HOURS - age),
                    "offers": int(l.get("total_offers") or 0), "hidden": l.get("active") is False}
    return out


TRASH = "_trash"   # podfolder screenshots/ z przedmiotami usunietymi z listy


def price_label(prices: list) -> str:
    """Ceny z Traderie -> skladnia jak w okienku ('ist+mal', '2 pamy', 'ber | jah')."""
    import traderie_price as tpr
    groups = {}
    for p in prices or []:
        q = int(p.get("quantity") or 1)
        name = tpr.short(p.get("name", "?"))
        groups.setdefault(p.get("group", 0), []).append(f"{q} {name}" if q > 1 else name)
    return " | ".join("+".join(g) for _, g in sorted(groups.items())) or "offer"


def known_ids(folder: Path) -> set:
    """ID ofert, ktore juz mamy lokalnie (takze sprzedane, zdjete i usuniete z listy)."""
    ids = set()
    for f in list(folder.glob("*.listing.json")) + list((folder / TRASH).glob("*.listing.json")):
        try:
            lst = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in ("posted", "removed"):
            lid = (lst.get(key) or {}).get("listing_id")
            if lid:
                ids.add(str(lid))
    return ids


def import_listings(folder: Path, active: dict) -> list:
    """Tworzy wpisy dla ofert wystawionych na Traderie poza skryptem. Zwraca nazwy zaimportowanych."""
    have = known_ids(folder)
    added = []
    for lid, l in active.items():
        if lid in have:
            continue
        item = l.get("item") or {}
        listing = []
        for p in l.get("properties") or []:
            # Traderie przezwalo pole z nazwa statu: bylo 'property', jest 'name' (X 2026).
            # Bez tego oferty wciagniete spoza programu mialy nazwy statow puste, a Ladder
            # - bo warunek nizej nie trafial - zapisywal sie jako True zamiast "Ladder".
            nazwa = p.get("name") or p.get("property") or ""
            if p["type"] == "number":
                v = p.get("number")
            elif p["type"] == "string":
                v = p.get("string")
            elif nazwa == "Ladder":
                v = "Ladder" if p.get("bool") else "Non Ladder"
            else:
                v = True if p.get("bool") else None
            if v is not None:
                listing.append({"property_id": p["property_id"], "value": v, "property": nazwa})
        lst = {"source": "", "imported": True, "ocr_name": item.get("name", "?"), "warnings": [], "unmatched": [],
               "properties": [], "item_id": str(item.get("id")), "slug": item.get("slug"),
               "name": item.get("name"), "type": item.get("type"), "listing": listing, "needs_review": False,
               "posted": {"listing_id": lid, "price": price_label(l.get("prices")),
                          "time": (l.get("updated_at") or "")[:16].replace("T", " ")}}
        (folder / f"traderie_{lid}.listing.json").write_text(json.dumps(lst, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
        added.append(lst["name"])
    return added


def sync(folder: Path):
    """Sprzedane + import ofert spoza skryptu + stan aktywnych ofert.
    Zwraca (nowo sprzedane [nazwy], stan {id: {...}}, zaimportowane [nazwy])."""
    active = own_listings(completed=False)
    imported = import_listings(folder, active)
    posted = []
    for f in folder.glob("*.listing.json"):
        lst = json.loads(f.read_text(encoding="utf-8"))
        lid = (lst.get("posted") or {}).get("listing_id")
        if lid and not lst.get("sold"):
            posted.append((f, lst, str(lid)))
    marked = []
    missing = [x for x in posted if x[2] not in active]
    if missing:   # zakonczone sprawdzamy tylko, gdy ktorejs oferty nie ma wsrod aktywnych
        done_ids = listing_ids(completed=True)
        for f, lst, lid in missing:
            if lid in done_ids:
                lst["sold"] = time.strftime("%Y-%m-%d %H:%M")
                lst["sold_via"] = "traderie"
                f.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
                marked.append(lst.get("name", f.name))
    return marked, listing_status(active), imported
