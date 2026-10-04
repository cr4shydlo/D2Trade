"""Cache wynikow price-check: mniej zapytan do Traderie przy tej samej wycenie."""
import json
import time

import traderie_map as tm
import traderie_price as tpr


ODPOWIEDZ = {"percentiles": {"50": 1.0}, "trades": 7}


def licznik(odpowiedz=ODPOWIEDZ, blad=None):
    """Atrapa http_json liczaca wywolania."""
    stan = {"n": 0}

    def fake(url, timeout=30):
        stan["n"] += 1
        if blad:
            raise blad
        return odpowiedz

    return stan, fake


def test_drugie_pytanie_idzie_z_cache():
    stan, tm.http_json = licznik()
    a = tpr.price_check("123", "&prop_1Min=5")
    b = tpr.price_check("123", "&prop_1Min=5")
    assert a == b == ODPOWIEDZ
    assert stan["n"] == 1, "drugie wywolanie powinno pochodzic z cache"


def test_inne_filtry_to_inne_pytanie():
    stan, tm.http_json = licznik()
    tpr.price_check("123", "&prop_1Min=5")
    tpr.price_check("123", "&prop_1Min=9")
    assert stan["n"] == 2, "inny rzut to inne pytanie, cache nie moze go podmienic"


def test_force_pomija_cache():
    stan, tm.http_json = licznik()
    tpr.price_check("123", "")
    tpr.price_check("123", "", force=True)
    assert stan["n"] == 2


def test_przeterminowany_wpis_odpytuje_ponownie():
    stan, tm.http_json = licznik()
    tpr.price_check("123", "")
    dane = json.loads(tpr.PRICE_CACHE.read_text(encoding="utf-8"))
    for wpis in dane.values():                       # cofamy czas poza TTL
        wpis["t"] = time.time() - tpr.PRICE_TTL - 1
    tpr.PRICE_CACHE.write_text(json.dumps(dane), encoding="utf-8")
    tpr.price_check("123", "")
    assert stan["n"] == 2


def test_blad_sieci_oddaje_poprzedni_wynik():
    stan, tm.http_json = licznik()
    tpr.price_check("123", "")
    stan2, tm.http_json = licznik(blad=OSError("zerwane polaczenie"))
    dane = json.loads(tpr.PRICE_CACHE.read_text(encoding="utf-8"))
    for wpis in dane.values():
        wpis["t"] = time.time() - tpr.PRICE_TTL - 1  # wymusza probe pobrania
    tpr.PRICE_CACHE.write_text(json.dumps(dane), encoding="utf-8")
    assert tpr.price_check("123", "") == ODPOWIEDZ, "stary wynik jest lepszy niz brak ceny"
    assert stan2["n"] == 1


def test_pusta_odpowiedz_nie_trafia_do_cache():
    stan, tm.http_json = licznik(odpowiedz={"percentiles": None})
    assert tpr.price_check("123", "") is None
    assert tpr.price_check("123", "") is None
    assert stan["n"] == 2, "brak transakcji moze byc chwilowy - nie zapamietujemy go"


def test_uszkodzony_cache_nie_blokuje_wyceny():
    tpr.PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tpr.PRICE_CACHE.write_text("{to nie jest json", encoding="utf-8")
    stan, tm.http_json = licznik()
    assert tpr.price_check("123", "") == ODPOWIEDZ
    assert stan["n"] == 1
