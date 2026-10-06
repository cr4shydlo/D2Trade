"""Akcje na przedmiotach: wystawianie, oznaczanie sprzedazy, usuwanie z listy."""
import asyncio, json
from nicegui.testing import User
import traderie_post as tp

async def test_actions(user: User):
    import d2_web as W
    tp.DELAY = (1, 1)
    sent, sold_calls = [], []
    tp.post = lambda payload, auth: (sent.append(payload['item']), (200, json.dumps({"success": True, "listing": "777"})))[1]
    tp.mark_sold = lambda lid, auth: (sold_calls.append(lid), (True, 'ok'))[1]
    await user.open('/')
    await asyncio.sleep(1.5)
    ready = [i for i in W.S.order if W.S.items[i]['status'] == 'ready']
    for i in ready[:2]:
        await W.set_price(i, 'ist')
    await asyncio.sleep(0.5)
    # wystawianie: okno potwierdzenia -> Tak
    expected = [i for i in W.S.order if W.S.items[i]['selected'] and W.S.items[i]['status'] in ('ready','dup')]
    t = asyncio.create_task(W.start_post()); await asyncio.sleep(0.5)
    user.find('Tak').click()
    await t
    for _ in range(40):
        await asyncio.sleep(0.2)
        if not W.S.busy: break
    print('wyslano:', len(sent), '| statusy:', [W.S.items[i]['status'] for i in ready[:2]])
    assert len(sent) == len(expected) and all(W.S.items[i]['status'] == 'posted' for i in expected)
    # sprzedany + oznaczenie na Traderie
    iid = ready[0]
    t = asyncio.create_task(W.toggle_sold(iid)); await asyncio.sleep(0.4)
    user.find('Tak').click(); await t
    print('sold:', W.S.items[iid]['lst'].get('sold') is not None, '| mark_sold dla:', sold_calls)
    assert sold_calls == ['777']
    # usuwanie z listy (tylko z listy)
    other = [i for i in W.S.order if W.S.items[i]['status'] == 'ready'][0]
    name = W.S.items[other]['lst']['name']
    t = asyncio.create_task(W.delete_item(other)); await asyncio.sleep(0.4)
    user.find('Tak').click(); await t
    print('usuniety z listy:', name, other not in W.S.items)
    assert other not in W.S.items
    # okno wycinka otwiera sie dla przedmiotu ze screenem
    with_png = [i for i in W.S.order if W.S.items[i]['status'] in ('ready', 'review') and
                list(W.FOLDER.glob(W.stem_of(W.S.items[i]) + '.png'))]
    print('przedmioty ze screenem:', len(with_png))


async def test_sprawdzone_odblokowuje_wystawienie(user: User):
    """Przedmiot 'do sprawdzenia' (np. craft) da sie odblokowac, zamiast tylko usunac z listy."""
    import json
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)

    iid = next(i for i in W.S.order if W.S.items[i]["status"] in ("ready", "dup"))
    W.S.items[iid]["lst"]["needs_review"] = True
    W.save_lst(W.S.items[iid])
    W.load_items()
    await asyncio.sleep(0.3)
    assert W.S.items[iid]["status"] == "review"

    W.mark_reviewed(iid)
    await asyncio.sleep(0.3)
    zapis = json.loads(W.S.items[iid]["file"].read_text(encoding="utf-8"))
    print("status po odblokowaniu:", W.S.items[iid]["status"], "| w pliku reviewed:", zapis.get("reviewed"))
    assert W.S.items[iid]["status"] in ("ready", "dup")
    assert zapis["needs_review"] is False and zapis["reviewed"]


async def test_kopertka_pokazuje_wiadomosci(user: User, monkeypatch):
    """Nowe wiadomosci z Traderie trafiaja do licznika przy kopertce i do okna z lista."""
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.0)
    monkeypatch.setattr("d2_web.traderie_notify.fetch_new",
                        lambda: [("2026-10-02 11:00", "oferta na Shako"), ("2026-10-02 11:05", "wiadomosc od gracza")])
    monkeypatch.setattr("d2_web.traderie_sync.sync", lambda folder: ([], {}, []))
    W.S.notify_on, W.S.notify_new, W.S.messages = True, 0, []

    await W.notify_tick()
    await asyncio.sleep(0.5)
    print("nieprzeczytane:", W.S.notify_new, "| w pamieci:", len(W.S.messages))
    assert W.S.notify_new == 2 and len(W.S.messages) == 2
    await user.should_see("mail")                       # kopertka w naglowku

    W.messages_dialog()
    await asyncio.sleep(0.3)
    await user.should_see("oferta na Shako")
    assert W.S.notify_new == 0                          # otwarcie = przeczytane


async def test_fg_przy_cenach_w_oknie(user: User):
    """Dopisek FG przy cenie: pojawia sie przy wpisanym kursie, znika po wylaczeniu podgladu."""
    import i18n
    import traderie_price as tpr
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.0)
    tpr.RUNE_VALUES.clear()
    tpr.RUNE_VALUES.update({"Ist Rune": 1, "Mal Rune": 0.46})

    i18n.save_setting("d2jsp_fg_per_ist", 60)
    i18n.save_setting("fg_in_app", True)
    W._FG["when"] = 0
    print("z kursem:", W.fg_text("ist+mal"))
    assert W.fg_text("ist+mal") == "~87.5 fg"        # 1.46 x 60 = 87.6, w dol do polowki
    assert W.fg_text("offer") == ""

    i18n.save_setting("fg_in_app", False)            # wylaczony podglad w oknie
    W._FG["when"] = 0
    assert W.fg_text("ist+mal") == ""

    i18n.save_setting("fg_in_app", True)
    i18n.save_setting("d2jsp_fg_per_ist", 0)         # bez kursu nie ma czego pokazywac
    W._FG["when"] = 0
    assert W.fg_text("ist+mal") == ""


async def test_odliczanie_nie_przebudowuje_listy(user: User, monkeypatch):
    """Podczas przerwy miedzy ofertami lista ma stac w miejscu.

    Kazda sekunda odliczania ustawiala S.dirty, wiec okno przebudowywalo sie w calosci -
    ikony i nazwy migaly przez cale wystawianie (zgloszone 6 X 2026). Pasek postepu ma
    wlasny uchwyt i przerysowuje sie sam; reszta widoku nie ma powodu znikac.
    """
    import d2_web as W
    monkeypatch.setattr(tp, "DELAY", (6, 6))
    monkeypatch.setattr(tp, "post", lambda payload, auth: (200, json.dumps({"success": True, "listing": "777"})))
    await user.open('/')
    await asyncio.sleep(1.5)

    ready = [i for i in W.S.order if W.S.items[i]['status'] == 'ready'][:2]
    assert len(ready) == 2, "wzorzec powinien miec dwa gotowe przedmioty"
    for i in ready:
        await W.set_price(i, 'ist')
    await asyncio.sleep(0.5)

    rysowan = {"n": 0}
    karta = W.item_card
    monkeypatch.setattr(W, "item_card", lambda iid: (rysowan.__setitem__("n", rysowan["n"] + 1), karta(iid))[1])

    zadanie = asyncio.create_task(W.start_post())
    await asyncio.sleep(0.5)
    user.find('Tak').click()

    # czekamy, az program wejdzie w odliczanie przerwy przed druga oferta
    for _ in range(120):
        await asyncio.sleep(0.1)
        if W.S.progress and W.S.progress[0].endswith(" s"):
            break
    assert W.S.progress and W.S.progress[0].endswith(" s"), "nie doczekalem sie odliczania"

    # pierwsza oferta poszla przed chwila i slusznie zazadala przebudowy - dajemy jej dojsc,
    # zeby pomiar dotyczyl juz samego odliczania
    await asyncio.sleep(1.0)
    przed, tekst_przed = rysowan["n"], W.S.progress[0]
    await user.should_see("Wystawianie")        # pasek sam sie rysuje, mimo ze lista stoi
    await asyncio.sleep(2.0)
    tekst_po = W.S.progress[0]
    print("odliczanie:", tekst_przed, "->", tekst_po, "| przerysowanych kart:", rysowan["n"] - przed)
    # bez tego sprawdzenia test przechodzilby takze wtedy, gdyby odliczanie w ogole nie ruszylo
    assert tekst_przed != tekst_po, "pasek postepu stoi - test nic by nie sprawdzil"
    assert rysowan["n"] == przed, "lista przebudowala sie w trakcie odliczania"

    # ...a licznik faktycznie widzi przebudowe - inaczej zero wyzej nic by nie znaczylo
    W.S.dirty = True
    await asyncio.sleep(0.8)
    print("po wymuszonej przebudowie:", rysowan["n"] - przed)
    assert rysowan["n"] > przed, "licznik nie wykrywa przebudowy - test bylby slepy"

    await zadanie
    for _ in range(40):
        await asyncio.sleep(0.2)
        if not W.S.busy:
            break
    assert all(W.S.items[i]['status'] == 'posted' for i in ready)
