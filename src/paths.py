"""
paths.py - gdzie leza pliki programu, a gdzie dane robocze.

PROGRAM = katalog ze skryptami: src/ (lang/, affixes_data.json) - zawsze obok .py.
KORZEN  = katalog projektu, czyli ten z plikami .bat.
DATA    = dane robocze: KORZEN/data (screenshots/, cache/, secrets/, settings.json...).

Dane leza osobno od kodu, zeby po sklonowaniu repozytorium nie mieszaly sie z plikami
programu i zeby caly dorobek pracy dalo sie skopiowac jednym katalogiem. Zmienna
srodowiskowa D2_DANE przenosi je gdzie indziej - dzieki temu testy pracuja na kopii
i nie moga skasowac prawdziwych ofert, cen ani ustawien. Zadna sciezka w programie
nie jest bezwzgledna, wiec katalog projektu mozna przenosic.
"""
import os
import sys
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent
KORZEN = PROGRAM.parent
DATA = Path(os.environ.get("D2_DANE") or (KORZEN / "data")).resolve()
SECRETS = DATA / "secrets"      # token Traderie i klucz API - jedno miejsce, caly katalog w .gitignore
# nazwy katalogow sa po angielsku (jak cache/, logs/, lang/); stare polskie nazwy przenosimy przy starcie
OLD_DIRS = {"screeny": "screenshots", "kopie": "backups", "sekrety": "secrets"}
OLD_SECRETS = ("traderie_auth.txt", "api_OVH.txt")
# Dane lezaly kiedys luzem w katalogu projektu, obok kodu. Przy starcie przenosimy je
# do data/ - inaczej po aktualizacji program zobaczylby pusta liste i wygladaloby to
# tak, jakby dorobek pracy przepadl.
PRZENIES_DO_DATA = ("screenshots", "cache", "logs", "backups", "secrets", "game_data",
                    "settings.json", "posted.json", "prices.json", "token_usage.csv",
                    "notifications_seen.json", "d2jsp_threads.json", "d2jsp_fg.json",
                    "unid_map.json")


def secret(name: str) -> Path:
    """Sciezka do pliku z sekretem. Nazwa bezwzgledna zostaje bez zmian."""
    p = Path(name)
    return p if p.is_absolute() else SECRETS / p.name


def use_data_dir():
    """Przestawia katalog biezacy na DATA (wywolywane raz, przy starcie okna/konsoli)."""
    _utrwal_argv0()
    collect_data()
    DATA.mkdir(parents=True, exist_ok=True)
    os.chdir(DATA)
    migrate_layout()
    return DATA


def _utrwal_argv0():
    """Zamienia sys.argv[0] na sciezke bezwzgledna, zanim zmienimy katalog biezacy.

    Uruchamiany z pliku .bat program dostaje sciezke wzgledna ('src\\d2_web.py'). Po chdir
    taka sciezka wskazuje w inne miejsce, a biblioteki, ktore licza z niej swoje polozenie,
    wywalaja sie przy starcie - pywebview robi tak przy samym imporcie NiceGUI
    ('Path ...\\data\\src does not exist'). Okno w ogole sie nie otwieralo.
    """
    if sys.argv and sys.argv[0]:
        try:
            sys.argv[0] = str(Path(sys.argv[0]).resolve())
        except OSError:
            pass


def collect_data():
    """Przenosi dane lezace jeszcze w katalogu projektu do data/.

    Dziala tylko przy domyslnym polozeniu danych: gdy ktos wskazal D2_DANE, to on
    decyduje, gdzie one sa, i nie ma czego przenosic.
    """
    if os.environ.get("D2_DANE") or not KORZEN.is_dir():
        return
    stare = [KORZEN / n for n in PRZENIES_DO_DATA]
    if not any(p.exists() for p in stare):
        return
    DATA.mkdir(parents=True, exist_ok=True)
    for p in stare:
        cel = DATA / p.name
        if p.exists() and not cel.exists():
            _move(p, cel)


def migrate_layout():
    """Przenosi dane z poprzedniego ukladu: polskie nazwy katalogow i sekrety lezace luzem.

    Katalogi i pliki sa przenoszone, nie czytane - program nie zaglada do tresci sekretow.
    """
    for stara, nowa in OLD_DIRS.items():
        a, b = DATA / stara, DATA / nowa
        if a.is_dir() and not b.exists():
            _move(a, b)
    stary_kosz, nowy_kosz = DATA / "screenshots" / "_usuniete", DATA / "screenshots" / "_trash"
    if stary_kosz.is_dir() and not nowy_kosz.exists():
        _move(stary_kosz, nowy_kosz)
    SECRETS.mkdir(parents=True, exist_ok=True)
    for name in OLD_SECRETS:
        stary = DATA / name
        if stary.exists() and not (SECRETS / name).exists():
            _move(stary, SECRETS / name)


def _move(a: Path, b: Path):
    try:
        a.replace(b)
    except OSError as e:
        print(f"!!! nie udalo sie przeniesc {a.name} -> {b.name}: {e}")


# ---- kopia zapasowa i czyszczenie danych ----
# Czyszczenie kasuje dorobek pracy, wiec zawsze poprzedza je kopia. Sekrety sa poza jednym
# i drugim: wyczyszczenie ich nie dotyka, wiec nie ma czego z nich odtwarzac, a kopia nie jest
# miejscem na token i klucz API.
WIPE_DIRS = ("screenshots",)                       # z podkatalogami (_crops, _trash)
WIPE_FILES = ("posted.json", "prices.json")        # rejestr wystawionych i ostatnie ceny
KEEP = ("settings.json", "secrets", "cache", "logs", "backups", "lang", "game_data",
        "d2jsp_threads.json", "d2jsp_fg.json", "token_usage.csv", "notifications_seen.json")


def backup_zip(prefix: str = "dane") -> Path:
    """Pakuje dane robocze do backups/<prefix>_RRRRMMDD_GGMM.zip. Zwraca sciezke do archiwum.

    Bez secrets/ (patrz wyzej), bez backups/ (zeby kopia nie pakowala samej siebie), bez cache/,
    ktory program i tak pobierze ponownie z Traderie, i bez game_data/ - te dane odtwarza
    game_extract.py z plikow gry, a waza kilkanascie megabajtow.
    """
    import zipfile
    from datetime import datetime

    kosz = DATA / "backups"
    kosz.mkdir(parents=True, exist_ok=True)
    plik = kosz / f"{prefix}_{datetime.now():%Y%m%d_%H%M}.zip"
    pomin = {"secrets", "backups", "cache", "game_data", "__pycache__", ".venv"}
    with zipfile.ZipFile(plik, "w", zipfile.ZIP_DEFLATED) as z:
        for p in DATA.rglob("*"):
            if not p.is_file() or any(cz in pomin for cz in p.relative_to(DATA).parts):
                continue
            if p.suffix in (".py", ".bat", ".md"):     # kod jest w repo, nie w kopii danych
                continue
            z.write(p, p.relative_to(DATA))
    return plik


def wipe_data() -> dict:
    """Kasuje dorobek pracy: screenshots/ (z podkatalogami), posted.json, prices.json.

    NIE rusza ustawien, sekretow, cache, logow ani kopii - patrz KEEP. Zwraca licznik usunietego.
    Wywolywac wylacznie po backup_zip().
    """
    import shutil

    ile = {"plikow": 0, "katalogow": 0}
    for nazwa in WIPE_DIRS:
        kat = DATA / nazwa
        if not kat.is_dir():
            continue
        ile["plikow"] += sum(1 for p in kat.rglob("*") if p.is_file())
        shutil.rmtree(kat, ignore_errors=True)
        kat.mkdir(parents=True, exist_ok=True)         # program oczekuje, ze katalog istnieje
        ile["katalogow"] += 1
    for nazwa in WIPE_FILES:
        p = DATA / nazwa
        if p.exists():
            p.unlink()
            ile["plikow"] += 1
    return ile
