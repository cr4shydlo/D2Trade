"""Opis slowny jakosci rzutu w panelu (wariant B: 'wartosc / maksimum' + slowo)."""
import asyncio

from nicegui.testing import User

import rare_eval


def test_progi_etykiet():
    assert rare_eval.quality_label(1.0) == "maksymalny rzut"
    assert rare_eval.quality_label(0.9) == "prawie maks"
    assert rare_eval.quality_label(0.64) == "wysoki"
    assert rare_eval.quality_label(0.42) == "sredni"
    assert rare_eval.quality_label(0.3) == "niski"
    assert rare_eval.quality_label(0.05) == "prawie min"
    assert rare_eval.quality_label(0.0) == "minimalny rzut"
    assert rare_eval.quality_label(None) is None


def test_prawie_maks_powyzej_progu_mocnego():
    """Mocny stat (STRONG) to jeszcze nie swietny rzut - etykieta ma to rozrozniac."""
    assert rare_eval.quality_label(rare_eval.STRONG) != "prawie maks"
    assert rare_eval.MID_ROLL < 0.85


def test_etykiety_sa_przetlumaczone():
    import i18n
    i18n.load("en")
    try:
        assert i18n.tr("prawie maks") == "near max"
        assert i18n.tr("maksymalny rzut") == "max roll"
    finally:
        i18n.load("pl")


async def test_panel_pokazuje_opis_slowny(user: User):
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(2.0)
    iid = "item_20261001_174310_483.listing.json"
    W.select(iid)
    await asyncio.sleep(1.2)
    await user.should_see("Staty na tle maksimum dla tego slotu")
    # kazdy stat z policzona jakoscia dostaje jedno ze slow ze skali
    rolls = rare_eval.rolls(W.S.items[iid]["lst"], W.S.defs.get("Jared's Stone"))
    assert rolls, "panel bez statow - test nie sprawdzilby niczego"
    opisy = {rare_eval.quality_label(r[5]) for r in rolls}
    assert opisy and None not in opisy
    for opis in opisy:
        await user.should_see(opis)


async def test_skala_kolorow(user: User):
    """Pelna skala: zielony -> dwa szare -> zolty -> oliwkowy. Czerwien zostaje dla bledow.

    Test jest asynchroniczny i otwiera strone, bo d2_web wolno dotykac tylko w kontekscie
    fixtury `user`: import tego modulu w zwyklym tescie gubi rejestracje strony i kolejne
    testy dostaja 404.
    """
    await user.open("/")
    import d2_web as W
    import traderie_price as tpr
    pasek = lambda p: W.kolor_rzutu(p)[0]
    assert pasek(1.0) == W.OK
    assert pasek(0.9) == W.OK
    assert pasek(0.64) == W.MUTED
    assert pasek(0.42) == W.FAINT
    assert pasek(0.30) == W.WARN
    assert pasek(0.10) == W.WEAK
    assert pasek(0.0) == W.WEAK
    # kolor bledu nie moze oznaczac slabego rzutu
    assert W.BAD not in {pasek(p / 20) for p in range(21)}
    # progi koloru i slowa musza isc z tego samego zrodla
    assert pasek(tpr.HIGH_ROLL) == W.OK
    assert pasek(rare_eval.MID_ROLL) == W.MUTED
    assert pasek(rare_eval.WEAK_ROLL) == W.WARN


async def test_oba_motywy_maja_nowy_kolor(user: User):
    await user.open("/")
    import d2_web as W
    for nazwa, paleta in W.PALETY.items():
        assert "weak" in paleta, "brak koloru najslabszego rzutu w motywie %s" % nazwa
    assert W.PALETY["dark"]["weak"] != W.PALETY["light"]["weak"],         "ciemny odcien na jasnym tle robi sie czarna kreska - potrzebny osobny"
