"""
game_casc.py - czytanie plikow Diablo II: Resurrected z dysku uzytkownika.

Dwa zrodla, to samo API:
  Casc    - archiwum CASC w katalogu z zainstalowana gra (wymaga pakietu "casc")
  Katalog - juz wypakowane pliki (np. przez CascView), czyli zwykly katalog z data/

Nazwy plikow podajemy w jednej postaci: "data/global/excel/armor.txt". Casc tlumaczy
to na swoj format ("data:data\\global\\excel\\armor.txt"), Katalog na sciezke na dysku.
Dzieki temu game_extract.py nie wie, skad czyta - i da sie go uruchomic bez CascLib,
jesli ktos ma pliki wypakowane innym narzedziem.

Nic tu nie zapisuje do gry ani jej nie uruchamia: wylacznie odczyt plikow.
"""
import io
import os
import re
import struct
from pathlib import Path

# naglowek ikony D2R (.sprite): 40 bajtow, potem surowe RGBA8888, jedna klatka.
# Sprawdzone na wszystkich ikonach ekwipunku z D2R 3.3.93847.
SPRITE_MAGIC = b"SpA1"
SPRITE_HEAD = 40

CASC_BRAK = (
    "Czytanie archiwum gry wymaga pakietu 'casc' (wrapper CascLib):\n"
    "    py -3.11 -m pip install casc\n"
    "Pakiet ma gotowe kolo tylko dla Windows x64 + Python 3.11. Jesli nie da sie go\n"
    "zainstalowac, wypakuj katalog 'data' dowolnym narzedziem do CASC (np. CascView)\n"
    "i wskaz ten katalog zamiast katalogu z gra."
)


class BrakZrodla(Exception):
    """Wskazana sciezka nie jest ani gra, ani katalogiem z wypakowanym 'data'."""


# ---------------- zrodla ----------------
class Katalog:
    """Wypakowane pliki gry: <korzen>/data/global/excel/armor.txt itd."""

    etykieta = "wypakowane pliki"

    def __init__(self, korzen):
        self.korzen = Path(korzen)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def lista(self, katalog: str, rek: bool = False) -> list:
        kat = self.korzen / katalog
        if not kat.is_dir():
            return []
        pliki = kat.rglob("*") if rek else kat.iterdir()
        return sorted(f"{katalog}/{p.relative_to(kat).as_posix()}" for p in pliki if p.is_file())

    def czytaj(self, nazwa: str) -> bytes:
        return (self.korzen / nazwa).read_bytes()

    def ma(self, nazwa: str) -> bool:
        return (self.korzen / nazwa).is_file()


class Casc:
    """Archiwum CASC gry. Pakiet _casc ma nieoczywiste sygnatury - sa schowane tutaj:
    find_first_file oddaje (uchwyt, wpis), open_file (ok, uchwyt), read_file (uchwyt, dane, ile).
    Przekazanie pary do read_file konczy sie mylacym 'Parameter must be a file reference'."""

    etykieta = "archiwum CASC"

    def __init__(self, gra):
        self.gra = str(gra)
        self.h = None
        self._spis = None

    def __enter__(self):
        try:
            import _casc
        except ImportError:
            raise BrakZrodla(CASC_BRAK) from None
        self._casc = _casc
        self.h = _casc.open(self.gra)
        return self

    def __exit__(self, *_):
        if self.h is not None:
            self._casc.close(self.h)
            self.h = None
        return False

    def _wszystko(self) -> list:
        """Spis nazw w archiwum. Czytany raz - przejscie listy to kilka sekund."""
        if self._spis is None:
            uchwyt, wpis = self._casc.find_first_file(self.h, "*")
            nazwy = []
            while wpis:
                nazwy.append(wpis["filename"])
                try:
                    wpis = self._casc.find_next_file(uchwyt)[1]
                except Exception:
                    break
            try:
                # po wyczerpaniu listy CascLib sam zamyka uchwyt szukania
                self._casc.find_close(uchwyt)
            except Exception:
                pass
            self._spis = nazwy
        return self._spis

    def lista(self, katalog: str, rek: bool = False) -> list:
        ogon = r"\\.+$" if rek else r"\\[^\\]+$"
        wzor = re.compile(r"^data:" + re.escape(katalog.replace("/", "\\")) + ogon, re.I)
        return sorted(_logiczna(n) for n in self._wszystko() if wzor.match(n))

    def czytaj(self, nazwa: str) -> bytes:
        pelna = "data:" + nazwa.replace("/", "\\")
        ok, f = self._casc.open_file(self.h, pelna)
        if not ok:
            raise IOError("nie udalo sie otworzyc w archiwum gry: %s" % nazwa)
        try:
            return self._casc.read_file(f)[1]
        finally:
            self._casc.close_file(f)

    def ma(self, nazwa: str) -> bool:
        return ("data:" + nazwa.replace("/", "\\")).lower() in {n.lower() for n in self._wszystko()}


def _logiczna(nazwa_casc: str) -> str:
    return nazwa_casc.split(":", 1)[-1].replace("\\", "/")


PROBNY = "data/global/excel/armor.txt"


def otworz(sciezka):
    """Zrodlo danych gry dla wskazanej sciezki (jeszcze nie otwarte - uzyj w 'with').

    Najpierw sprawdzamy wypakowane pliki, bo to nie wymaga zadnej biblioteki.
    Katalog z gra rozpoznajemy po 'Data' - tam CascLib szuka indeksow.
    """
    p = Path(sciezka)
    if not p.is_dir():
        raise BrakZrodla("nie ma takiego katalogu: %s" % p)
    for korzen in (p, p / "out" / "raw"):       # drugie: katalog z wypakowanymi danymi
        if (korzen / PROBNY).is_file():
            return Katalog(korzen)
    if (p / "Data").is_dir() or (p / "data").is_dir():
        return Casc(p)
    raise BrakZrodla(
        "w %s nie ma ani katalogu 'Data' (zainstalowana gra), ani wypakowanego "
        "'data/global/excel/armor.txt'" % p)


# ---------------- tabele i ikony ----------------
def tabela(dane: bytes) -> list:
    """Tabela gry (.txt rozdzielany tabulatorami) -> lista slownikow. Pierwszy wiersz to naglowek."""
    wiersze = dane.decode("utf-8-sig", "replace").split("\n")
    naglowek = wiersze[0].rstrip("\r").split("\t")
    out = []
    for w in wiersze[1:]:
        w = w.rstrip("\r")
        if not w.strip():
            continue
        pola = w.split("\t")
        pola += [""] * (len(naglowek) - len(pola))
        out.append(dict(zip(naglowek, pola)))
    return out


def sprite_na_png(dane: bytes, przytnij: bool = True) -> bytes:
    """Ikona .sprite -> PNG. Rzuca ValueError, gdy plik nie jest surowym RGBA."""
    from PIL import Image

    if dane[:4] != SPRITE_MAGIC:
        raise ValueError("nie jest sprite (%r)" % dane[:4])
    szer, wys = struct.unpack_from("<II", dane, 8)
    rozmiar = struct.unpack_from("<I", dane, 32)[0]
    if rozmiar != szer * wys * 4 or len(dane) < SPRITE_HEAD + rozmiar:
        raise ValueError("%dx%d, %d bajtow danych - nie RGBA8888" % (szer, wys, rozmiar))
    img = Image.frombytes("RGBA", (szer, wys), dane[SPRITE_HEAD:SPRITE_HEAD + rozmiar])
    if przytnij:
        # ikony maja szeroki przezroczysty margines; bez przyciecia kazdy obrazek
        # w oknie jest wielkosci najwiekszego przedmiotu, a nie samego rysunku
        ramka = img.getbbox()
        if ramka:
            img = img.crop(ramka)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def slug(tekst: str) -> str:
    """Nazwa przedmiotu -> klucz pliku. Apostrof prosty i typograficzny wystepuja oba."""
    t = (tekst or "").lower().replace("'", "").replace(chr(0x2019), "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def liczba(tekst, domyslna=None):
    try:
        return int(str(tekst).strip())
    except (TypeError, ValueError):
        return domyslna


def czy_gra(sciezka) -> bool:
    """Czy pod ta sciezka da sie czytac dane gry (bez otwierania archiwum)."""
    if not sciezka:
        return False
    try:
        otworz(sciezka)
        return True
    except BrakZrodla:
        return False


def zgadnij_gre():
    """Typowe miejsca instalacji D2R - podpowiedz, gdy uzytkownik nie poda sciezki."""
    kandydaci = [
        r"C:\Program Files (x86)\Diablo II Resurrected",
        r"C:\Program Files\Diablo II Resurrected",
        r"C:\GRY\Diablo II Resurrected",
    ]
    for dysk in "CDEFG":
        kandydaci.append(r"%s:\Games\Diablo II Resurrected" % dysk)
        kandydaci.append(r"%s:\Diablo II Resurrected" % dysk)
    for k in kandydaci:
        if os.path.isdir(k):
            return k
    return None
