"""
Czy program w ogole sie uruchamia - tak, jak robi to plik .bat.

Po co osobny test: reszta testow importuje `d2_web` przez wtyczke NiceGUI, a to **nie
jest** to samo, co `python src\\d2_web.py`. Przy takim uruchomieniu `sys.argv[0]` jest
sciezka wzgledna, a program zmienia katalog biezacy na `data/` - i biblioteki, ktore
licza polozenie z `argv[0]`, przestaja trafiac. Tak wlasnie okno przestalo wstawac po
przeniesieniu kodu do `src/` (5 X 2026), a 96 testow tego nie zauwazylo, bo zaden nie
uruchamial programu jako programu.

Test odpala prawdziwy proces, czeka az serwer odpowie, i go zabija. Zeby nie otwierac
okna i nie wchodzic na zajety port, podaje `D2_BEZ_OKNA` i wlasny `D2_PORT`.
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

KORZEN = __import__("pathlib").Path(__file__).resolve().parent.parent
PORT = 8799                 # inny niz domyslny 8765, zeby nie gryzc sie z wlasnym oknem
START_TIMEOUT = 90          # pierwszy start NiceGUI potrafi chwile potrwac


def czyste_srodowisko() -> dict:
    """Srodowisko bez sladow pytest. NiceGUI widzi zmienne NICEGUI_* i przelacza sie w tryb
    testowy, a wtedy szuka portu, ktorego nie ma - proces ma wygladac na zwykly start."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("NICEGUI") and not k.startswith("PYTEST")}


def czekaj_na_serwer(proc, adres, limit):
    """(ok, powod). Konczy, gdy serwer odpowie albo gdy proces padnie."""
    koniec = time.time() + limit
    while time.time() < koniec:
        if proc.poll() is not None:
            return False, "proces zakonczyl sie z kodem %s" % proc.returncode
        try:
            with urllib.request.urlopen(adres, timeout=2) as r:
                if r.status == 200:
                    return True, ""
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False, "serwer nie odpowiedzial w %d s" % limit


@pytest.mark.parametrize("skrypt", ["src/d2_web.py"])
def test_okno_wstaje_uruchomione_jak_z_bat(skrypt, tmp_path):
    srodowisko = {
        **czyste_srodowisko(),
        "D2_DANE": str(tmp_path),      # swieze dane: test nie dotyka prawdziwych ofert
        "D2_PORT": str(PORT),
        "D2_BEZ_OKNA": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    # sciezka WZGLEDNA i katalog roboczy w korzeniu - dokladnie tak, jak w pliku .bat
    proc = subprocess.Popen([sys.executable, skrypt.replace("/", os.sep)],
                            cwd=str(KORZEN), env=srodowisko,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ok, powod = czekaj_na_serwer(proc, "http://127.0.0.1:%d/" % PORT, START_TIMEOUT)
    proc.kill()
    wyjscie = proc.communicate()[0] or ""
    assert ok, "%s nie wstal: %s\n--- wyjscie programu ---\n%s" % (skrypt, powod, wyjscie[-3000:])


def test_wyciag_z_gry_uruchamia_sie_jak_z_bat(tmp_path):
    """Drugi plik .bat. Bez katalogu gry ma powiedziec, co zrobic, a nie wywalic sie."""
    srodowisko = {**os.environ, "D2_DANE": str(tmp_path), "PYTHONIOENCODING": "utf-8"}
    w = subprocess.run([sys.executable, os.path.join("src", "game_extract.py"), str(tmp_path / "nie-ma-gry")],
                       cwd=str(KORZEN), env=srodowisko, capture_output=True, text=True, timeout=120)
    assert w.returncode == 2, w.stdout + w.stderr
    assert "nie ma takiego katalogu" in (w.stdout + w.stderr)
    assert "Traceback" not in (w.stdout + w.stderr), "blad ma byc komunikatem, nie sladem wyjatku"
