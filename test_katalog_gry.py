"""Katalog nazw z plikow gry: mniej zapytan do Traderie przy szybkiej wycenie."""
import game_db
import quick_price
import traderie_map as tm


def test_katalog_wczytany():
    assert game_db.dostepny(), "brak game_items.json - katalog powinien byc w repo"
    assert len(game_db.indeks()) > 1000


def test_rozpoznaje_nazwy_z_gry():
    assert game_db.znajdz("Harlequin Crest")["kind"] == "unique"
    assert game_db.znajdz("Grand Charm")["kind"] == "base"
    assert game_db.znajdz("Spirit")["kind"] == "runeword"


def test_nazwa_bez_przedimka():
    """Gra nazywa to 'The Stone of Jordan', a wpisuje sie 'stone of jordan'."""
    wpis = game_db.znajdz("stone of jordan")
    assert wpis and wpis["name"] == "The Stone of Jordan"


def test_najdluzszy_poczatek_zapytania():
    n, wpis = game_db.najdluzsza_nazwa("harlequin crest def 136".split(), maks=3)
    assert (n, wpis["name"]) == (2, "Harlequin Crest")


def test_nieznana_nazwa_nie_zgaduje():
    """Przezwiska ('vipermagi') nie sa nazwami z gry - maja spasc do starej sciezki."""
    assert game_db.znajdz("vipermagi") is None
    assert game_db.najdluzsza_nazwa(["vipermagi", "def"])[1] is None


def test_mniej_zapytan_o_nazwe(monkeypatch):
    """'harlequin crest def 136': bez katalogu pytamy o 'harlequin crest def', potem
    'harlequin crest'. Z katalogiem - od razu o wlasciwa nazwe."""
    pytania = []
    oryginal = tm.get_item

    def licz(nazwa, *a, **kw):
        pytania.append(nazwa)
        return oryginal(nazwa, *a, **kw)

    monkeypatch.setattr(tm, "get_item", licz)
    quick_price.quick_price("harlequin crest def 136")
    assert len(pytania) == 1, "katalog powinien wskazac nazwe bez prob na slepo: %s" % pytania
