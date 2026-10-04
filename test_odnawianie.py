"""Odnawianie ofert (pojedynczo i wszystkie po kolei) oraz pole 'gdzie lezy przedmiot'.

Najwazniejszy przypadek: Traderie przyjmuje zadanie, ale oferty NIE odnawia. Program musi to
wykryc (po stanie ofert pobranym z serwera) i powiedziec wprost, a nie zapisac 'odnowiono'.
"""
import asyncio
import json

from nicegui.testing import User

import traderie_post as tp
import traderie_sync as ts


def aktywna(lid, nazwa, godzin):
    """Wiersz oferty z Traderie 'sprzed N godzin' - do ustawienia stanu 'do odnowienia'."""
    from datetime import datetime, timedelta, timezone
    kiedy = (datetime.now(timezone.utc) - timedelta(hours=godzin)).isoformat().replace("+00:00", "Z")
    return lid, {"id": lid, "updated_at": kiedy, "active": True, "total_offers": 0,
                 "item": {"id": "1", "name": nazwa, "slug": "x"}, "properties": [], "prices": []}


def podstaw_sync(monkeypatch, wiek: dict):
    """Atrapa traderie_sync.sync: {id oferty: wiek w godzinach} -> stan jak z serwera."""
    def fake(folder):
        return [], ts.listing_status(dict(aktywna(lid, "x", h) for lid, h in wiek.items())), []
    monkeypatch.setattr("d2_web.traderie_sync.sync", fake)


async def test_odnawianie_udane(user: User, monkeypatch):
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)
    wystawione = [i for i in W.S.order if W.S.items[i]["status"] == "posted"]
    assert len(wystawione) >= 2, "wzorzec powinien miec co najmniej dwie wystawione oferty"
    ids = [str(W.S.items[i]["lst"]["posted"]["listing_id"]) for i in wystawione]

    stare = {ids[0]: ts.RELIST_HOURS + 2, ids[1]: ts.RELIST_HOURS + 5}
    podstaw_sync(monkeypatch, stare)
    await W.task(W.do_sync, True)
    gotowe = W.relist_ready()
    print("gotowe do odnowienia:", len(gotowe))
    assert len(gotowe) == 2

    wyslane = []
    monkeypatch.setattr(tp, "refresh_listing", lambda lid, auth: (wyslane.append(lid), (True, "ok"))[1])
    monkeypatch.setattr(tp, "REFRESH_DELAY", (1, 1))
    # po odnowieniu serwer pokazuje swieze oferty - dopiero to jest potwierdzeniem
    podstaw_sync(monkeypatch, {ids[0]: 0.1, ids[1]: 0.1})

    await W.task(W.relist_one, gotowe[0][0])
    print("wyslane ID:", wyslane)
    assert wyslane == [gotowe[0][1]]
    assert W.S.items[gotowe[0][0]]["lst"]["posted"]["refreshed"]
    assert not W.relist_ready()

    podstaw_sync(monkeypatch, stare)
    await W.task(W.do_sync, True)
    wyslane.clear()
    await W.task(W.do_relist_all)
    print("'odnow wszystkie' wyslalo:", wyslane)
    assert set(wyslane) == set(ids[:2])


async def test_odnawianie_tylko_zaznaczonych(user: User, monkeypatch):
    """Zaznaczenie w widoku wystawionych zawęza odnawianie do wybranych ofert."""
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)
    wystawione = [i for i in W.S.order if W.S.items[i]["status"] == "posted"][:3]
    ids = [str(W.S.items[i]["lst"]["posted"]["listing_id"]) for i in wystawione]
    podstaw_sync(monkeypatch, {lid: ts.RELIST_HOURS + 2 for lid in ids})
    await W.task(W.do_sync, True)
    assert len(W.relist_ready()) == len(ids) >= 2

    # nic nie zaznaczone -> plan to wszystkie gotowe
    assert len(W.relist_plan()) == len(ids)
    # zaznaczamy jedna oferte (jak klikniecie checkboxa na karcie)
    W.toggle_check(wystawione[1])
    print("zaznaczonych:", sum(1 for i in wystawione if W.S.items[i]["selected"]))
    assert [l for _, l in W.relist_plan()] == [ids[1]]

    wyslane = []
    monkeypatch.setattr(tp, "refresh_listing", lambda lid, auth: (wyslane.append(lid), (True, "ok"))[1])
    monkeypatch.setattr(tp, "REFRESH_DELAY", (1, 1))
    podstaw_sync(monkeypatch, {ids[1]: 0.1, **{l: ts.RELIST_HOURS + 2 for l in ids if l != ids[1]}})
    await W.task(W.do_relist_all)
    print("wyslano tylko:", wyslane)
    assert wyslane == [ids[1]]
    assert not W.S.items[wystawione[1]]["selected"]      # odnowione odznacza sie samo

    # "Zaznacz gotowe" / "Odznacz"
    W.check_relist(True)
    assert len(W.relist_plan()) == len(W.relist_ready())
    W.check_relist(False)
    assert not any(W.S.items[i]["selected"] for i in wystawione)


async def test_traderie_przyjelo_ale_nie_odnowilo(user: User, monkeypatch, capsys):
    """Serwer odpowiada OK, a licznik oferty sie nie zmienia - to NIE jest sukces."""
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)
    iid = next(i for i in W.S.order if W.S.items[i]["status"] == "posted")
    lid = str(W.S.items[iid]["lst"]["posted"]["listing_id"])

    podstaw_sync(monkeypatch, {lid: ts.RELIST_HOURS + 3})     # stan bez zmian takze PO odnowieniu
    await W.task(W.do_sync, True)
    monkeypatch.setattr(tp, "refresh_listing", lambda l, auth: (True, "ok"))
    await W.task(W.relist_one, iid)

    print("nadal do odnowienia:", W.S.listing_state[lid]["relist"])
    print("znacznik refreshed:", (W.S.items[iid]["lst"].get("posted") or {}).get("refreshed"))
    assert W.S.listing_state[lid]["relist"]                   # oferta zostaje na liscie do odnowienia
    assert "refreshed" not in W.S.items[iid]["lst"]["posted"]  # i bez znacznika "odnowiono"
    assert "nadal nie jest odnowiona" in capsys.readouterr().out


async def test_blad_powiadomienia_nie_przerywa_odnawiania(user: User, monkeypatch, capsys):
    """Po przebudowie widoku ui.notify rzuca RuntimeError - to nie moze wywalic zadania."""
    import d2_web as W
    from nicegui import ui
    await user.open("/")
    await asyncio.sleep(1.5)
    iid = next(i for i in W.S.order if W.S.items[i]["status"] == "posted")
    lid = str(W.S.items[iid]["lst"]["posted"]["listing_id"])
    podstaw_sync(monkeypatch, {lid: ts.RELIST_HOURS + 3})
    await W.task(W.do_sync, True)
    monkeypatch.setattr(tp, "refresh_listing", lambda l, auth: (True, "ok"))
    podstaw_sync(monkeypatch, {lid: 0.1})

    def wybuch(*a, **k):
        raise RuntimeError("The parent element this slot belongs to has been deleted.")
    monkeypatch.setattr(ui, "notify", wybuch)

    await W.task(W.relist_one, iid)      # bez wyjatku
    print("odnowiono mimo braku powiadomienia:", (W.S.items[iid]["lst"]["posted"]).get("refreshed"))
    assert W.S.items[iid]["lst"]["posted"]["refreshed"]
    assert "Traceback" not in capsys.readouterr().out


def test_zadanie_odnowienia_idzie_putem(monkeypatch):
    """Metoda musi byc PUT - przy POST Traderie zwraca 404 (tak jak przy nieznanej sciezce)."""
    import urllib.request
    zapytania = []

    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b'{"success":true,"version":"1.3.0"}'

    def fake(req, timeout=30):
        zapytania.append((req.get_method(), req.full_url, json.loads(req.data)))
        return R()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ok, msg = tp.refresh_listing("1002527658713", {"Authorization": "Bearer x"})
    print("wyslano:", zapytania[0], "->", ok, msg)
    metoda, url, body = zapytania[0]
    assert ok and metoda == "PUT"
    assert url.endswith("/listings/refresh") and body == {"listing": "1002527658713"}


def test_odpowiedz_bez_potwierdzenia_to_blad(monkeypatch):
    """refresh_listing nie moze zglaszac sukcesu, gdy serwer niczego nie potwierdzil."""
    class R:
        status = 200

        def __init__(self, b):
            self.b = b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return self.b
    import urllib.request
    odp = {"tresc": b"{}"}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: R(odp["tresc"]))
    ok, msg = tp.refresh_listing("1", {})
    print("pusta odpowiedz ->", ok, msg)
    assert not ok and "odpowiedz" in msg

    odp["tresc"] = b'{"success": true}'
    print("success:true ->", tp.refresh_listing("1", {}))
    assert tp.refresh_listing("1", {})[0]

    odp["tresc"] = b'{"error": "Too soon"}'
    ok, msg = tp.refresh_listing("1", {})
    print("blad z Traderie ->", ok, msg)
    assert not ok and "Too soon" in msg


async def test_gdzie_lezy_i_lista_do_wyjecia(user: User):
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)

    iid = next(i for i in W.S.order if W.S.items[i]["status"] == "posted")
    W.set_where(iid, char="Mularz", stash="Skrzynia wspolna 3")
    print("plakietka:", W.where_label(W.S.items[iid]["lst"]))
    assert W.where_label(W.S.items[iid]["lst"]) == "Mularz · Skrzynia wspolna 3"
    zapis = json.loads(W.S.items[iid]["file"].read_text(encoding="utf-8"))
    assert zapis["where"] == {"char": "Mularz", "stash": "Skrzynia wspolna 3"}
    assert W.chars_known() == ["Mularz"]

    W.S.filter_char = "Mularz"
    widoczne = [i for i in W.S.order if W.visible(W.S.items[i], i)]
    print("widocznych przy filtrze:", len(widoczne))
    assert iid in widoczne or widoczne == []     # w widoku 'items' wystawione sa ukryte
    W.S.filter_char = ""

    assert W.pickup_text() == ""                 # lista powstaje dopiero dla sprzedanych
    W.S.items[iid]["lst"]["sold"] = "2026-10-01 20:00"
    tekst = W.pickup_text()
    print("co wyjac:\n" + tekst)
    assert "Mularz / Skrzynia wspolna 3:" in tekst and W.S.items[iid]["lst"]["name"] in tekst
    W.set_where(iid, char="", stash="")
    assert "where" not in W.S.items[iid]["lst"]


async def test_wejscie_w_wystawione_sprawdza_oferty(user: User, monkeypatch):
    """Przelaczenie na 'Wystawione' samo pobiera stan ofert, ale nie czesciej niz co SYNC_GAP."""
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)

    wywolania = []

    def fake(folder):
        wywolania.append(1)
        return [], {}, []
    monkeypatch.setattr("d2_web.traderie_sync.sync", fake)

    W.S.last_sync = 0                       # jakby program dopiero wstal
    W.switch_view("listed")
    await asyncio.sleep(0.8)
    print("pobran po wejsciu:", len(wywolania))
    assert len(wywolania) == 1

    W.switch_view("items")                  # powrot i ponowne wejscie - za wczesnie na kolejne pytanie
    W.switch_view("listed")
    await asyncio.sleep(0.8)
    assert len(wywolania) == 1

    W.S.last_sync -= W.SYNC_GAP + 1         # po przerwie pyta znowu
    W.switch_view("listed")
    await asyncio.sleep(0.8)
    print("pobran po przerwie:", len(wywolania))
    assert len(wywolania) == 2


async def test_samoczynne_sprawdzanie_nie_blokuje_okna(user: User, monkeypatch, capsys):
    """Zerwane polaczenie przy wejsciu w 'Wystawione': przyciski zostaja czynne, w logu jedna linia.

    Wczesniej szlo to przez task(), wiec S.busy wyszarzalo m.in. "Odczytaj screeny" na czas
    pobierania, a blad konczyl sie sladem wyjatku w logu.
    """
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)

    def pada(folder):
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr("d2_web.traderie_sync.sync", pada)

    capsys.readouterr()                            # log idzie przez print - czyscimy, co bylo wczesniej
    W.S.last_sync = 0
    W.switch_view("listed")
    await asyncio.sleep(0.8)

    nowe = capsys.readouterr().out
    print("busy po bledzie:", W.S.busy, "| slad wyjatku w logu:", "Traceback" in nowe)
    assert W.S.busy is False                       # okno nie jest zablokowane
    assert "Traceback" not in nowe                 # cicho: jedna linia, nie slad wyjatku
    assert "Traderie" in nowe and "timed out" in nowe
