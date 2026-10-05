"""Stronicowanie listy: podzial na strony, wybor 10/20/50 i zapamietanie wyboru."""
import asyncio
import json

from nicegui.testing import User

import i18n


async def test_strony_i_zapamietany_rozmiar(user: User):
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)
    # numery stron: pierwsza, ostatnia i okolice biezacej; 0 = przerwa '...'
    assert W.page_numbers(1, 3) == [1, 2, 3]
    assert W.page_numbers(1, 9) == [1, 2, 0, 9]
    assert W.page_numbers(5, 9) == [1, 0, 4, 5, 6, 0, 9]
    assert W.page_numbers(9, 9) == [1, 0, 8, 9]
    W.S.show_all = True                      # wzorzec ma wiecej niz 10 przedmiotow dopiero ze sprzedanymi
    W.set_page_size(10)
    await asyncio.sleep(0.6)

    widoczne = [i for i in W.S.order if W.visible(W.S.items[i], i)]
    assert len(widoczne) > 10, "wzorzec powinien miec wiecej niz 10 przedmiotow"
    assert json.loads(i18n.SETTINGS.read_text(encoding="utf-8"))["page_size"] == 10
    await user.should_see("Pokaz po:")

    # nazwa, ktora wystepuje raz i wypada dopiero na druga strone
    nazwy = [W.S.items[i]["lst"].get("name") or W.S.items[i]["lst"].get("ocr_name", "?") for i in widoczne]
    z_drugiej = next(n for n in nazwy[10:] if nazwy.count(n) == 1)
    print("druga strona zaczyna sie od:", nazwy[10], "| szukana nazwa:", z_drugiej)
    await user.should_not_see(z_drugiej)

    W.set_page(2)
    await asyncio.sleep(0.6)
    await user.should_see(z_drugiej)

    # wiekszy rozmiar strony - wszystko miesci sie na jednej, numeracja znika
    W.set_page_size(50)
    await asyncio.sleep(0.6)
    assert W.S.page == 1
    await user.should_see(z_drugiej)
    await user.should_see(nazwy[0])
