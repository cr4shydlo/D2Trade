"""Kolejnosc listy (sortowanie, grupy po rodzaju) i usuwanie hurtem.

Dwie rzeczy, ktore latwo zepsuc przy zmianach w liscie:
  - tryb usuwania ma WLASNE zaznaczenia; gdyby korzystal z tych do wystawienia, czerwony przycisk
    pokazywalby "usun N" zaraz po starcie, bo kazdy gotowy przedmiot z cena zaznacza sie sam,
  - usuniecie hurtem nie moze zabrac przedmiotu wystawionego na Traderie - zostalaby oferta,
    o ktorej program juz nic nie wie.
"""
import asyncio
import json

from nicegui.testing import User

import i18n
import traderie_sync as ts


async def otworz(user: User):
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)
    return W


def widoczne(W):
    return W.posortuj([i for i in W.S.order if W.visible(W.S.items[i], i)])


async def test_sortowanie(user: User):
    W = await otworz(user)
    W.S.show_all = True

    # najnowsze: nazwa pliku to data zrzutu, wiec kolejnosc jest odwrotna niz S.order
    W.set_sort("newest")
    assert widoczne(W) == [i for i in reversed(W.S.order) if W.visible(W.S.items[i], i)]

    # rodzaj: grupy ida wedlug KIND_ORDER, a w srodku grupy nadal od najnowszego
    W.set_sort("kind")
    kolejnosc = [W.KIND_ORDER.index(W.rodzaj_of(W.S.items[i])) for i in widoczne(W)]
    print("grupy po rodzaju:", [W.rodzaj_of(W.S.items[i]) for i in widoczne(W)])
    assert kolejnosc == sorted(kolejnosc), "grupy rozjechaly sie wzgledem KIND_ORDER"

    # nazwa: alfabetycznie, bez wzgledu na wielkosc liter
    W.set_sort("name")
    nazwy = [(W.S.items[i]["lst"].get("name") or "").lower() for i in widoczne(W)]
    assert nazwy == sorted(nazwy)

    # cena: od najdrozszej, bez ceny na koncu
    W.set_sort("price")
    import traderie_price as tpr
    import d2jsp_post
    wartosci = [d2jsp_post.price_value(W.S.items[i]["price"], tpr.load_runes()) for i in widoczne(W)]
    bez_ceny = [v is None for v in wartosci]
    print("ceny w Ist:", wartosci)
    assert bez_ceny == sorted(bez_ceny), "przedmioty bez ceny powinny byc na koncu"
    z_cena = [v for v in wartosci if v is not None]
    assert z_cena == sorted(z_cena, reverse=True)

    # stan: najpierw to, co czeka na decyzje
    W.set_sort("status")
    stany = [W.STATUS_ORDER.index(W.eff_status(W.S.items[i])) for i in widoczne(W)]
    assert stany == sorted(stany)

    # wybor zapisuje sie na nastepne uruchomienie
    assert json.loads(i18n.SETTINGS.read_text(encoding="utf-8"))["sort"] == "status"


async def test_naglowki_grup_widac_w_oknie(user: User):
    W = await otworz(user)
    W.set_sort("kind")
    await asyncio.sleep(0.6)
    rodzaje = {W.rodzaj_of(W.S.items[i]) for i in widoczne(W)}
    print("rodzaje na liscie:", rodzaje)
    assert rodzaje, "wzorzec powinien miec jakies przedmioty"
    for r in rodzaje:
        await user.should_see(r.upper())


async def test_tryb_usuwania_ma_wlasne_zaznaczenia(user: User):
    W = await otworz(user)
    # gotowy przedmiot z cena zaznacza sie sam (tak dziala load_items) - i wlasnie dlatego
    # tryb usuwania nie moze dziedziczyc tych zaznaczen
    gotowy = next(i for i in W.S.order if W.S.items[i]["status"] == "ready")
    await W.set_price(gotowy, "ist")
    W.load_items()
    assert W.S.items[gotowy]["selected"], "gotowy przedmiot z cena powinien byc zaznaczony"
    await user.should_see("Zaznacz do usuniecia")
    W.delete_mode(True)
    assert W.S.to_delete == set() and not W.do_usuniecia()
    await asyncio.sleep(0.5)
    await user.should_see("Usun zaznaczone (0)")          # pasek przelaczyl sie w tryb usuwania
    await user.should_not_see("Zaznacz do usuniecia")
    W.delete_mode(False)
    assert W.S.items[gotowy]["selected"], "wyjscie z trybu zgubilo zaznaczenie do wystawienia"


async def test_usuwanie_hurtem(user: User):
    W = await otworz(user)
    gotowe = [i for i in W.S.order if W.S.items[i]["status"] == "ready"][:2]
    pliki = [W.S.items[i]["file"] for i in gotowe]
    assert len(gotowe) == 2, "wzorzec powinien miec co najmniej dwa gotowe przedmioty"

    W.delete_mode(True)
    for iid in gotowe:
        W.toggle_delete(iid)
    assert len(W.do_usuniecia()) == 2
    W.toggle_delete(gotowe[0])                      # drugie klikniecie odznacza
    W.toggle_delete(gotowe[0])
    assert len(W.do_usuniecia()) == 2

    zadanie = asyncio.create_task(W.delete_selected())
    await asyncio.sleep(0.4)
    user.find("Tak").click()
    await zadanie

    print("usuniete:", [p.name for p in pliki])
    assert all(i not in W.S.items for i in gotowe)
    kosz = W.FOLDER / ts.TRASH
    assert all((kosz / p.name).exists() and not p.exists() for p in pliki), \
        "pliki maja trafic do kosza, a nie zniknac z dysku"
    assert not W.S.delete_mode and not W.S.to_delete, "po usunieciu tryb powinien sie zamknac"


async def test_usuwanie_hurtem_nie_rusza_wystawionych(user: User):
    W = await otworz(user)
    wystawione = [i for i in W.S.order if W.S.items[i]["status"] == "posted"]
    assert wystawione, "wzorzec powinien miec wystawiona oferte"
    W.S.show_all = True                             # dopiero wtedy wystawione widac w "Przedmioty"
    W.delete_mode(True)
    W.S.to_delete = set(wystawione)                 # jakby ktos zaznaczyl je mimo braku kwadracika
    # bez tego sprawdzenia test przechodzilby takze wtedy, gdyby wystawione byly po prostu
    # niewidoczne - a chodzi o to, ze widac je i mimo to usuwanie ich nie rusza
    assert all(W.visible(W.S.items[i], i) and i in W.S.to_delete for i in wystawione)
    assert W.do_usuniecia() == []
    await W.delete_selected()                       # bez okna potwierdzenia - nie ma czego usuwac
    assert all(i in W.S.items for i in wystawione)
