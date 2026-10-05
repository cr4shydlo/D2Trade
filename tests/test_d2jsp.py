"""Post d2jsp: ceny w runach / w FG oraz przelicznik kursow z Traderie."""
import json

import i18n
import traderie_price as tpr
import d2jsp_post as d2j


def ustaw(runy=True, fg=True, kurs=0):
    i18n.save_setting("d2jsp_runes", runy)
    i18n.save_setting("d2jsp_fg", fg)
    i18n.save_setting("d2jsp_fg_per_ist", kurs)


def test_przelicznik_fg(monkeypatch):
    """Kurs 'ile FG za Ist' przelicza pozostale waluty po kursach zapamietanych z Traderie."""
    tpr.RUNE_VALUES.clear()
    tpr.RUNE_VALUES.update({"Ist Rune": 1, "Mal Rune": 0.5, "Vex Rune": 2.5})
    monkeypatch.setattr(d2j, "FG_FILE", d2j.Path("nie_ma_takiego_pliku.json"))

    ustaw(runy=True, fg=True, kurs=0)
    assert d2j.fg_table() == {}, "bez kursu nie liczymy FG"

    ustaw(runy=True, fg=True, kurs=60)
    tabela = d2j.fg_table()
    print("kursy FG:", tabela)
    assert tabela == {"Ist Rune": 60, "Mal Rune": 30, "Vex Rune": 150}

    # cztery kombinacje przelacznikow
    ustaw(runy=True, fg=True, kurs=60)
    assert d2j.price_part("ist+mal", d2j.fg_table()) == "ist + mal (~90 fg)"
    ustaw(runy=False, fg=True, kurs=60)
    assert d2j.price_part("ist+mal", d2j.fg_table()) == "90 fg"
    ustaw(runy=True, fg=False, kurs=60)
    assert d2j.price_part("ist+mal", d2j.fg_table()) == "ist + mal"
    ustaw(runy=False, fg=False, kurs=60)
    assert d2j.price_part("ist+mal", d2j.fg_table()) == ""
    # FG wlaczone, ale bez kursu - zostaje to, co wybrano poza nim
    ustaw(runy=True, fg=True, kurs=0)
    assert d2j.price_part("ist+mal", d2j.fg_table()) == "ist + mal"
    ustaw(runy=False, fg=True, kurs=0)
    assert d2j.price_part("ist+mal", d2j.fg_table()) == ""
    ustaw(runy=True, fg=True, kurs=0)


def test_zaokraglanie_do_polowki_fg():
    """Zaokraglamy w dol do pelnej polowki FG - lepiej podac mniej niz zawyzyc."""
    assert [d2j.fg_round(v) for v in (89.7, 90.0, 90.2, 90.5, 90.9)] == [89.5, 90.0, 90.0, 90.5, 90.5]

    tpr.RUNE_VALUES.clear()
    tpr.RUNE_VALUES.update({"Ist Rune": 1, "Mal Rune": 0.46})     # 1.46 x 61 = 89.06
    ustaw(runy=False, fg=True, kurs=61)
    cena = d2j.price_part("ist+mal", d2j.fg_table())
    print("ist+mal przy kursie 61:", cena)
    assert cena == "89 fg"
    ustaw(runy=True, fg=True, kurs=0)


def test_kursy_przezywaja_restart(monkeypatch):
    """Kursy z wyceny zapisuja sie na dysk, wiec przelicznik dziala takze zaraz po starcie."""
    tpr.RUNE_VALUES.clear()
    tpr.RUNE_VALUES.update({"Ist Rune": 1, "Gul Rune": 1.25})
    tpr.save_runes()
    assert json.loads(tpr.RUNES_CACHE.read_text(encoding="utf-8"))["Gul Rune"] == 1.25

    tpr.RUNE_VALUES.clear()                 # jak po ponownym uruchomieniu programu
    wczytane = tpr.load_runes()
    print("wczytane kursy:", wczytane)
    assert wczytane["Gul Rune"] == 1.25
