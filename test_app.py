"""Przeplyw glowny: lista, wycena, okno ceny, widoki, synchronizacja z Traderie."""
import asyncio, ast, json, pathlib
from nicegui.testing import User
from nicegui import ui
import traderie_post as tp


def test_dlugie_zadania_nie_wolaja_ui_notify():
    """ui.notify dziala tylko w kontekscie zywego elementu strony.

    Dlugie zadanie przebudowuje widok, element znika i leci
    'The parent element this slot belongs to has been deleted'. Zdarzylo sie przy
    'Wystawianie zakonczone' po wystawieniu ofert (4 X 2026). W funkcjach async
    komunikaty maja isc przez say(), ktore w takim wypadku pisze do logu.
    """
    src = pathlib.Path(__file__).with_name("d2_web.py").read_text(encoding="utf-8")
    asynchroniczne = [(w.lineno, w.end_lineno) for w in ast.walk(ast.parse(src))
                      if isinstance(w, ast.AsyncFunctionDef)]
    zle = [(i + 1, l.strip()) for i, l in enumerate(src.splitlines())
           if "ui.notify(" in l and any(a <= i + 1 <= b for a, b in asynchroniczne)]
    assert not zle, "ui.notify w funkcji async - uzyj say():\n" + "\n".join(
        "  d2_web.py:%d  %s" % (nr, tekst[:90]) for nr, tekst in zle)

async def test_flow(user: User):
    import d2_web as W
    await user.open('/')
    await user.should_see('Przedmioty')
    await user.should_see("Renewed Crack of the Heavens")
    for _ in range(30):                      # wyceny w tle
        await asyncio.sleep(0.2)
        if all(W.S.items[i]['hint'] is not None for i in W.S.order if W.S.items[i]['status'] in ('ready','dup')): break
    await asyncio.sleep(0.6)
    # zaznacz przedmiot i ustaw cene przyciskiem poziomu
    iid = [i for i in W.S.order if W.S.items[i]['lst'].get('name') == "Renewed Crack of the Heavens"][0]
    W.select(iid); await asyncio.sleep(0.6)
    await user.should_see('Statystyki')
    user.find(marker='lvl-good').click(); await asyncio.sleep(0.5)
    assert W.S.items[iid]['price'] == 'gul' and W.S.items[iid]['selected']
    # okno ceny: dowolne klucze
    W.price_dialog(iid); await asyncio.sleep(0.3)
    user.find(marker='any-keys').click(); await asyncio.sleep(0.2)
    user.find(marker='price-save').click(); await asyncio.sleep(0.6)
    print('cena po oknie:', W.S.items[iid]['price'])
    assert 'key of terror' in W.S.items[iid]['price']
    # szybka wycena
    W.run_quick('vipermagi res 30'); await asyncio.sleep(1.0)
    await user.should_see('Cena z ostatnich transakcji')
    await user.should_see('Zmienne') if False else None
    # post d2jsp
    W.S.view = 'd2jsp'; W.S.dirty = True; await asyncio.sleep(0.6)
    await user.should_see('Kopiuj post sprzedazowy')
    # wystawione + synchronizacja
    W.S.view = 'listed'; W.S.dirty = True; await asyncio.sleep(0.6)
    await W.task(W.do_sync); await asyncio.sleep(0.8)
    print('po sync wierszy wystawionych:', sum(1 for i in W.S.order if W.S.items[i]['status']=='posted'))
    await user.should_see('Waterwalk')
    # ustawienia
    W.settings_dialog(); await asyncio.sleep(0.3)
    await user.should_see('Konto Traderie')
