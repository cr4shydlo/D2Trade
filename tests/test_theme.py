"""Przelaczanie motywu: jasny / ciemny."""
import asyncio

from nicegui.testing import User


async def test_palety_maja_te_same_klucze(user: User):
    """Brak koloru w jednej palecie = w tym motywie element zostaje bez tla albo bez tekstu.

    Fikstura `user` jest tu po to, zeby import d2_web nie zepsul rejestracji strony
    pozostalym testom (synchroniczny import poza fikstura konczy sie 404 dalej).
    """
    import d2_web as W
    dark, light = set(W.PALETY["dark"]), set(W.PALETY["light"])
    print("tylko w ciemnej:", sorted(dark - light), "| tylko w jasnej:", sorted(light - dark))
    assert dark == light
    assert W.THEME_DEFAULT in W.PALETY


async def test_stale_wskazuja_na_zmienne_css(user: User):
    """Widoki wklejaja kolory w style(...), wiec musza to byc nazwy zmiennych, nie wartosci.

    Gdyby ktoras stala wrocila do hexa, ten element zostalby w jednym kolorze w obu motywach.
    """
    import d2_web as W
    for nazwa in ("BG", "PANEL", "PANEL2", "PANEL3", "LINE", "LINE2", "INK", "MUTED", "FAINT",
                  "OK", "WARN", "BAD", "INFO", "ACT", "ACCENT", "ACCENT_FG", "THUMB"):
        wartosc = getattr(W, nazwa)
        assert wartosc.startswith("var(--"), f"{nazwa} = {wartosc}"
    assert all(v.startswith("var(--rar-") for v in W.RAR.values())
    # obie palety musza pokryc kazda uzyta zmienna
    uzyte = {v[6:-1] for v in
             [getattr(W, n) for n in ("BG", "PANEL", "PANEL2", "PANEL3", "LINE", "LINE2", "INK",
                                      "MUTED", "FAINT", "OK", "WARN", "BAD", "INFO", "ACT",
                                      "ACCENT", "ACCENT_FG", "THUMB")] + list(W.RAR.values())}
    brak = uzyte - set(W.PALETY["dark"])
    print("zmiennych w uzyciu:", len(uzyte), "| bez wartosci w palecie:", sorted(brak))
    assert not brak


async def test_wybor_motywu_zapisuje_sie(user: User):
    """Wybor zostaje w settings.json, wiec przezywa zamkniecie okna."""
    import i18n
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.0)

    W.set_motyw("light")
    print("po zmianie:", i18n.settings().get("theme"), "| motyw():", W.motyw())
    assert i18n.settings().get("theme") == "light" and W.motyw() == "light"

    W.set_motyw("dark")
    assert W.motyw() == "dark"

    i18n.save_setting("theme", "cokolwiek")        # smiec w pliku nie moze wywrocic okna
    assert W.motyw() == W.THEME_DEFAULT
