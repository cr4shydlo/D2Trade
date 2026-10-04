"""
d2_web.py - nowe okno aplikacji (NiceGUI): zrzuty -> odczyt -> ceny -> wystawianie, wycena, d2jsp.

Wymaga:  py -3.11 -m pip install nicegui pywebview
Uruchomienie: dwuklik na "D2 Trade.bat" albo:  pyw -3.11 d2_web.py
(Bez pywebview okno otworzy sie w przegladarce.)
"""
import os
import re
import sys
import json
import time
import html
import io
import contextlib
import queue
import random
import asyncio
import traceback
import webbrowser
from pathlib import Path
from datetime import datetime

import paths
paths.use_data_dir()   # cache, auth, screenshots - obok skryptu (albo tam, gdzie wskazuje D2_DANE)

try:
    from nicegui import app, ui, run
except ImportError:                       # przy pyw nie ma konsoli - pokaz okienko z instrukcja
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _r = _tk.Tk()
    _r.withdraw()
    _mb.showerror("D2 Trade", "Brakuje biblioteki NiceGUI. W konsoli wpisz:\n\npy -3.11 -m pip install nicegui pywebview")
    sys.exit(1)

import i18n
i18n.load()
import traderie_map as tm
import traderie_price as tpr
import traderie_post as tp
import traderie_sync
import traderie_notify
import d2jsp_post
import quick_price
import app_config
import rare_eval
import llm
import game_casc
import game_extract
import game_source
import game_db

app_config.apply()
t = i18n.tr

FOLDER = Path("screenshots")
FOLDER.mkdir(exist_ok=True)
IMG_DIR = Path("cache") / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)
NOTIFY_EVERY = 5 * 60
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"d2_{datetime.now():%Y%m%d}.log"

# ---------------- wyglad ----------------
# Jedyne nasycone kolory w oknie to kolory rzadkosci przedmiotow (takie jak w grze) oraz trzy barwy
# znaczeniowe: OK / uwaga / blad. Reszta jest neutralna, zeby wzrok szedl na tresc, a nie na interfejs.
# Promienie male (3 px kontrolki, 5 px panele), bez cieni i podnoszenia kart - hierarchie niosa linie.
FONT = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
MONO = "'IBM Plex Mono', Consolas, monospace"      # ceny, staty, liczby - rowna szerokosc cyfr
# Kolory zyja jako zmienne CSS, a stale ponizej trzymaja ich nazwy, nie wartosci. Dzieki temu
# kazde style(f"color:{MUTED}") w widokach dziala w obu motywach bez zmian, a przelaczenie motywu
# to podmiana jednego atrybutu na <html> - bez przebudowy okna. Wartosci: PALETY nizej.
BG, PANEL, PANEL2, PANEL3 = "var(--bg)", "var(--panel)", "var(--panel2)", "var(--panel3)"
LINE, LINE2 = "var(--line)", "var(--line2)"
INK, MUTED, FAINT = "var(--ink)", "var(--muted)", "var(--faint)"
OK, WARN, BAD, INFO, ACT = "var(--ok)", "var(--warn)", "var(--bad)", "var(--info)", "var(--act)"
# Najslabszy rzut ma wlasny odcien, bo wszystkie gotowe barwy sa juz zajete znaczeniem:
# czerwien to blad, INFO to rzadkosc magic, ACT to crafted i "do odnowienia".
# Rdzawy braz jest od nich wyraznie ciemniejszy i mniej nasycony.
WEAK = "var(--weak)"
ACCENT, ACCENT_FG = "var(--accent)", "var(--accent-fg)"   # akcja glowna: kontrast, nie kolor marki
THUMB = "var(--thumb)"
RAR = {k: f"var(--rar-{k})" for k in ("unique", "set", "runeword", "rare", "magic", "crafted", "baza")}
# Ramka wycinka lezy na zrzucie z gry, nie na tle okna: atrybut SVG nie rozumie var(), a i tak ma
# wygladac tak samo w obu motywach.
CROP_BOX, CROP_SEL = "#c56a5e", "#5f9e76"
PALETY = {
    "dark": {   # okno stoi obok pelnoekranowej gry, a kolory rzadkosci sa robione pod ciemne tlo
        "bg": "#15171b", "panel": "#1b1e23", "panel2": "#21252b", "panel3": "#262b32",
        "line": "#2c313a", "line2": "#3b424d",
        "ink": "#dde1e8", "muted": "#98a1ae", "faint": "#6b7482",
        "ok": "#5f9e76", "warn": "#c7a04f", "bad": "#c56a5e", "info": "#6f93cf", "act": "#c08043",
        "weak": "#9a6a4a",
        "accent": "#e6eaf1", "accent-fg": "#15171b", "thumb": "#23272d",
        "rar-unique": "#c5a059", "rar-set": "#5a9e5e", "rar-runeword": "#9589c4",
        "rar-rare": "#cdbb5c", "rar-magic": "#6f93cf", "rar-crafted": "#c08043",
        "rar-baza": "#8b93a1",
    },
    "light": {  # tlo to chlodny papier, nie biel - przy bieli hierarchia niesiona liniami znika;
                # kolory rzadkosci przyciemnione, bo growe zloto i zolc sa na jasnym nieczytelne
        "bg": "#e9ebef", "panel": "#f7f8fa", "panel2": "#ffffff", "panel3": "#e2e6ec",
        "line": "#d2d7df", "line2": "#b4bcc8",
        "ink": "#1b1e24", "muted": "#59616d", "faint": "#848c99",
        "ok": "#3d7a53", "warn": "#8a6718", "bad": "#a44336", "info": "#3a63a6", "act": "#96581b",
        "weak": "#7d5236",
        "accent": "#272b33", "accent-fg": "#f5f7fa", "thumb": "#e6e9ee",
        "rar-unique": "#846321", "rar-set": "#2c6a33", "rar-runeword": "#584f93",
        "rar-rare": "#746512", "rar-magic": "#3a63a6", "rar-crafted": "#96581b",
        "rar-baza": "#59616d",
    },
}
THEME_DEFAULT = "dark"
KIND = {k: (k, c) for k, c in RAR.items()}      # rodzaj przedmiotu -> (etykieta, kolor jak w grze)


def kolor_rzutu(pct: float):
    """Jakosc rzutu (0..1) -> (kolor paska, kolor slowa).

    Skala jednym ciagiem: zielony przy maksimum, dwa stopnie szarosci w srodku,
    zolty nisko, rdzawy przy samym dnie. Progi pochodza z rare_eval, zeby kolor
    nie rozjechal sie z opisem slownym. W srodku skali slowo zostaje neutralne -
    przy czterech barwach naraz panel robil sie jarmarkiem.
    """
    if pct >= tpr.HIGH_ROLL:
        return OK, OK
    if pct >= rare_eval.MID_ROLL:
        return MUTED, MUTED
    if pct >= rare_eval.LOW_ROLL:
        return FAINT, MUTED
    if pct >= rare_eval.WEAK_ROLL:
        return WARN, WARN
    return WEAK, WEAK
STATUS = {  # klucz -> (tekst, kolor kropki)
    "ready": ("gotowy", OK), "review": ("do sprawdzenia", WARN),
    "posted": ("wystawiony", INFO), "relist": ("do odnowienia", ACT),
    "dup": ("juz wystawiony?", WARN), "sold": ("sprzedany", FAINT),
    "skipped": ("pominiety", FAINT), "sending": ("wysylanie...", WARN),
    "error": ("blad", BAD),
}
LEVELS = (("floor", "tanio"), ("typical", "typowo"), ("good", "dobrze"), ("high", "drogo"))
STASH = ["Ekwipunek", "Skrzynia osobista", "Skrzynia wspolna 1", "Skrzynia wspolna 2", "Skrzynia wspolna 3",
         "Skrzynia wspolna 4", "Skrzynia wspolna 5"]   # gdzie lezy przedmiot - do odbioru po sprzedazy
PAGE_SIZES = (10, 20, 50)        # ile pozycji na stronie listy; wybor zapisuje sie w settings.json
PAGE_DEFAULT = 20
SYNC_GAP = 120                   # s - jak czesto najwyzej samo sprawdzac oferty po wejsciu w "Wystawione"
MAX_MESSAGES = 50                # ile ostatnich wiadomosci z Traderie trzymamy w oknie
TRADERIE_WWW = "https://traderie.com/notifications"
BB_COLORS = {"deepskyblue": "#79aee8", "crimson": "#d4736a", "chartreuse": "#6fb36f", "gold": "#c9a85f"}

def motyw() -> str:
    """'dark' albo 'light' - wybor zapisany w settings.json."""
    wybor = i18n.settings().get("theme", THEME_DEFAULT)
    return wybor if wybor in PALETY else THEME_DEFAULT


def set_motyw(nazwa: str):
    """Zapisuje wybor i przestawia okno od razu - sam atrybut na <html>, bez przebudowy widoku."""
    if nazwa not in PALETY:
        return
    i18n.save_setting("theme", nazwa)
    if S.dark is not None:
        S.dark.value = nazwa == "dark"          # Quasar: menu, tabele, powiadomienia
    try:
        ui.run_javascript(f'document.documentElement.dataset.theme = "{nazwa}";')
    except RuntimeError:        # brak zywego kontekstu strony - wybor i tak jest zapisany
        log(t(f"Motyw zapisany ({nazwa}) - bedzie widoczny po ponownym otwarciu okna."))


def _zmienne_css() -> str:
    """Obie palety jako zmienne CSS - przelacznik podmienia tylko atrybut data-theme na <html>."""
    return "\n".join(f':root[data-theme="{nazwa}"] {{ '
                     + " ".join(f"--{k}:{v};" for k, v in paleta.items()) + " }"
                     for nazwa, paleta in PALETY.items())


HEAD = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;450;500;600&display=swap" rel="stylesheet">
<style>
{_zmienne_css()}
body {{ background:{BG}; font-family:{FONT}; color:{INK}; font-weight:450; }}
.nicegui-content {{ padding:0; }}
.mono {{ font-family:{MONO}; font-variant-numeric:tabular-nums; }}
::-webkit-scrollbar {{ width:10px; height:10px; }}
::-webkit-scrollbar-thumb {{ background:{LINE2}; border-radius:5px; border:3px solid {BG}; }}
::-webkit-scrollbar-track {{ background:{BG}; }}

/* --- kontrolki Quasara: male promienie, nasze tla --- */
.q-btn {{ text-transform:none; font-family:{FONT}; font-weight:500; border-radius:3px; }}
.q-btn.rounded, .q-btn--rounded {{ border-radius:3px !important; }}
/* NiceGUI maluje kazdy przycisk kolorem 'primary' (niebieski Quasara). Gasimy to raz, a wyglad
   przyciskom nadaja juz nasze klasy ponizej. Selektory sa dwuczlonowe, zeby wygrac z .bg-primary. */
.q-btn.bg-primary {{ background:transparent !important; }}
.q-btn.text-primary, .q-btn.text-white {{ color:inherit !important; }}
.q-card {{ background:{PANEL}; border:1px solid {LINE2}; border-radius:5px; box-shadow:none; color:{INK}; }}
.q-field__control {{ border-radius:3px !important; background:{PANEL2}; }}
.q-field--outlined .q-field__control:before {{ border:1px solid {LINE}; }}
.q-field--outlined .q-field__control:hover:before {{ border-color:{LINE2}; }}
.q-field--outlined .q-field__control:after {{ border-width:1px; color:{MUTED}; }}
/* Quasar nadaje tabindex kontenerom (okno dialogowe, obszary przewijane), a przegladarka rysuje
   na nich wlasna obwodke focusa - poza obrysem elementu, wiec nachodzila na sasiadow: klikniecie
   w pole wyszukiwania w oknie ceny obrysowywalo czarna ramka cala karte. Pola tekstowe maja
   wlasne podswietlenie (.q-field__control:after), a przyciski swoje, wiec nic nie tracimy. */
div:focus, div:focus-visible {{ outline:none; }}
.q-field--focused .q-field__control:after {{ border-color:{MUTED}; }}
.q-field__native, .q-field__input, .q-field__prefix, .q-field__suffix {{ color:{INK}; }}
.q-field__label {{ color:{FAINT}; }}
.q-menu, .q-table, .q-table__bottom, .q-expansion-item__content {{ background:{PANEL}; color:{INK}; }}
.q-table th {{ color:{MUTED}; font-weight:500; }}
.q-table td, .q-table th {{ border-color:{LINE} !important; }}
.q-checkbox__inner--truthy, .q-checkbox__inner--indet {{ color:{MUTED} !important; }}
.q-toggle__inner--truthy {{ color:{OK} !important; }}
.q-notification {{ border-radius:3px; font-family:{FONT}; }}
.q-notification.bg-positive {{ background:{OK} !important; }}
.q-notification.bg-negative {{ background:{BAD} !important; }}
.q-notification.bg-warning {{ background:{WARN} !important; color:{BG} !important; }}
.q-notification.bg-info {{ background:{INFO} !important; color:{BG} !important; }}
.q-spinner {{ color:{MUTED}; }}

/* --- elementy wlasne ---
   Nazwy zaczynaja sie od 'd2', bo Quasar ma wlasne .row / .column / .list i zwykla nazwa
   przemalowalaby kazdy ui.row() w oknie (tak powstala kreska nad kazdym rzedem). */
.card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:5px; }}
.d2list {{ background:{PANEL}; border:1px solid {LINE}; border-radius:5px; overflow:hidden; }}
.d2row {{ border-top:1px solid {LINE}; position:relative; }}
.d2list > .d2row:first-child {{ border-top:0; }}
.d2row:hover {{ background:{PANEL2}; }}
.d2row.sel {{ background:{PANEL3}; }}
.d2row.sel:after {{ content:""; position:absolute; inset:0; border:1px solid {LINE2}; pointer-events:none; }}
.rar {{ width:3px; align-self:stretch; background:{RAR['baza']}; }}
.pill {{ font-size:11.5px; font-weight:400; padding:0 5px; border-radius:2px;
         background:{PANEL2}; border:1px solid {LINE}; color:{MUTED}; }}
.d2row.sel .pill {{ background:{PANEL}; }}
.tag {{ font-size:10.5px; font-weight:500; padding:1px 5px; border-radius:2px; border:1px solid currentColor; }}
.badge {{ font-size:12px; font-weight:400; color:{MUTED}; }}
.badge.strong {{ color:{INK}; }}
.dot {{ width:6px; height:6px; border-radius:1px; flex-shrink:0; }}
.q-btn.navbtn {{ border-radius:3px; height:32px; font-weight:450; color:{MUTED} !important;
                 justify-content:flex-start; }}
.q-btn.navbtn:hover {{ background:{PANEL2} !important; color:{INK} !important; }}
.q-btn.navbtn.on {{ background:{PANEL3} !important; color:{INK} !important; box-shadow:inset 2px 0 0 {MUTED}; }}
.q-btn.primary {{ background:{ACCENT} !important; color:{ACCENT_FG} !important;
                  border:1px solid {ACCENT}; font-weight:500; }}
.q-btn.primary:hover {{ filter:brightness(1.08); }}
.q-btn.ghost {{ background:{PANEL} !important; border:1px solid {LINE}; color:{MUTED} !important; }}
.q-btn.ghost:hover {{ background:{PANEL2} !important; border-color:{LINE2}; color:{INK} !important; }}
.lvl, .q-btn.lvl {{ border-radius:3px; border:1px solid {LINE}; background:{PANEL2} !important; color:{INK} !important; }}
.lvl:hover, .q-btn.lvl:hover {{ border-color:{LINE2}; }}
.lvl.on, .q-btn.lvl.on {{ background:{PANEL3} !important; border-color:{LINE2}; box-shadow:inset 0 -2px 0 {MUTED}; }}
.q-btn.price {{ border:1px solid {LINE}; border-radius:3px; background:transparent !important;
                color:{INK} !important; font-weight:450; }}
.q-btn.price:hover {{ border-color:{LINE2}; background:{PANEL2} !important; }}
.thumb {{ background:{THUMB}; border:1px solid {LINE}; border-radius:2px;
          display:flex; align-items:center; justify-content:center; }}
.bar {{ height:4px; border-radius:1px; background:{PANEL3}; overflow:hidden; }}
.bar > div {{ height:4px; border-radius:1px; background:{FAINT}; }}
.sec {{ font-size:11px; font-weight:450; color:{FAINT}; }}
.desc b {{ font-weight:500; }}
</style>
"""


def item_image(item: dict):
    """Obrazek przedmiotu: z CDN Traderie albo z ikon wyciagnietych z gry. Zawsze przez cache na dysku."""
    url = (item or {}).get("img")
    if not url:
        return None
    path = IMG_DIR / ((item.get("slug") or "item") + Path(url).suffix)
    if path.exists():
        return path
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    if not str(url).lower().startswith(("http://", "https://")):
        # ikona z plikow gry (game_extract.py) - kopiujemy do cache, bo okno wystawia
        # obrazki z jednego katalogu (/cache/img) i nie ma dostepu do innych sciezek
        try:
            path.write_bytes(Path(url).read_bytes())
        except OSError:
            return None
        return path
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": tm.UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            path.write_bytes(r.read())
    except Exception:
        return None
    return path


TAG_ORDER = ["Item Type", "Tier", "Weapon Type", "Body Location", "Class"]   # kategorie tagow warte pokazania
TAG_SKIP = {"Skills"}   # 'Skills' to lista drzewek, ktore MOGA sie wylosowac na tej bazie - mylace


def tags_of(item: dict, limit: int = 4) -> list:
    """Tagi przedmiotu w sensownej kolejnosci: typ, poziom bazy, rodzaj broni..."""
    tags = [t for t in (item or {}).get("tags") or [] if t.get("tag") and t.get("category") not in TAG_SKIP]
    tags.sort(key=lambda t: TAG_ORDER.index(t["category"]) if t.get("category") in TAG_ORDER else len(TAG_ORDER))
    out = []
    for t in tags:
        if t["tag"] not in out:
            out.append(t["tag"])
    return out[:limit]


def bbcode_html(desc: str) -> str:
    """Opis z Traderie ('**[color=DeepSkyBlue]+1-3[/color]** ...') -> HTML z kolorami."""
    out = []
    for line in (desc or "").splitlines():
        if line.lstrip().startswith("|"):
            continue
        s = html.escape(line.rstrip())
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\[color=([^\]]+)\]", lambda m: f'<span style="color:{BB_COLORS.get(m.group(1).lower(), m.group(1))}">', s)
        s = s.replace("[/color]", "</span>")
        out.append(s)
    text = "<br>".join(out)
    text = re.sub(r"(<br>){3,}", "<br><br>", text)
    return re.sub(r"^(<br>)+|(<br>)+$", "", text)     # usun puste linie z poczatku i konca (cale znaczniki)


# ---------------- stan aplikacji (jedno okno, jeden uzytkownik) ----------------
class State:
    def __init__(self):
        self.items, self.order = {}, []
        self.selected = None
        self.view = "items"          # items | listed | quick | d2jsp
        self.show_all = False
        self.filter_char = ""      # pokaz tylko przedmioty z tej postaci ("" = wszystkie)
        self.page = 1                # strona listy
        self.page_size = next((n for n in PAGE_SIZES if n == i18n.settings().get("page_size")), PAGE_DEFAULT)
        self.listing_state = {}      # id oferty -> {'relist','hours_left','offers','hidden'}
        self.last_sync = 0.0         # kiedy ostatnio pobrano stan ofert (time.monotonic)
        self.session_sold = set()
        self.busy = False
        self.stop = False
        self.progress = None         # (tekst, 0..1) podczas wystawiania
        self.capture_on = False
        self.notify_on = bool(i18n.settings().get("notify", True))   # domyslnie wlaczone
        self.notify_new = 0          # ile nieprzeczytanych (plakietka przy kopertce)
        self.messages = []           # [(kiedy, tresc)] - ostatnie wiadomosci z Traderie
        self.dirty = True            # odswiez widok
        self.defs, self.imgs = {}, {}
        self.gen = 0
        self.logq = queue.Queue()
        self.loglines = []
        self.quick = None
        self.host = None             # staly kontener na okna dialogowe (nie jest przebudowywany)
        self.editing = False         # uzytkownik pisze w polu - nie przebudowuj widoku
        self.dark = None             # uchwyt ui.dark_mode() - przelacznik motywu go przestawia

    def item_def(self, name):
        if name and name not in self.defs:
            self.defs[name] = tm.get_item(name)
        return self.defs.get(name)


S = State()


class LogWriter(io.TextIOBase):
    """print() z modulow -> log w oknie (+ konsola, jesli jest). Pelne zachowanie strumienia tekstowego,
    bo serwer (uvicorn) i biblioteki pytaja o isatty(), encoding, fileno() itd."""
    def __init__(self, original):
        super().__init__()
        self.original = original        # przy pyw: None (brak konsoli)

    @property
    def encoding(self):
        return getattr(self.original, "encoding", None) or "utf-8"

    @property
    def errors(self):
        return "replace"

    def writable(self):
        return True

    def isatty(self):
        return False

    def fileno(self):
        if self.original is None:
            raise io.UnsupportedOperation("fileno")
        return self.original.fileno()

    def write(self, s):
        if s:
            S.logq.put(t(s))
            S.loglines.append(t(s))
            del S.loglines[:-3000]
            try:                                      # log tez do pliku - mozna go przeslac w razie problemow
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(s)
            except Exception:
                pass
            if self.original is not None:
                try:
                    self.original.write(s)
                except Exception:
                    pass
        return len(s) if s else 0

    def flush(self):
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass


sys.stdout, sys.stderr = LogWriter(sys.__stdout__), LogWriter(sys.__stderr__)


def log(msg: str):
    print(msg if msg.endswith("\n") else msg + "\n")


# ---------------- dane ----------------
def load_items():
    registry = tp.load_registry(FOLDER)
    prices = json.loads(tp.PRICES_FILE.read_text(encoding="utf-8")) if tp.PRICES_FILE.exists() else {}
    items, order = {}, []
    for f in sorted(FOLDER.glob("*.listing.json")):
        lst = json.loads(f.read_text(encoding="utf-8"))
        if lst.get("sold"):
            st = "sold"
        elif lst.get("posted"):
            st = "posted"
        elif lst.get("skipped"):
            st = "skipped"
        elif lst.get("needs_review") or "listing" not in lst:
            st = "review"
        elif tp.fingerprint(lst) in registry:
            st = "dup"
        else:
            st = "ready"
        price = (lst.get("posted") or {}).get("price") or lst.get("planned_price") or ""
        old = S.items.get(f.name, {})
        items[f.name] = {"file": f, "lst": lst, "status": st, "price": price,
                         "hint": old.get("hint") if old.get("lst", {}).get("listing") == lst.get("listing") else None,
                         "selected": st == "ready" and bool(price),
                         "dup": registry.get(tp.fingerprint(lst)) if st == "dup" else None,
                         "last": prices.get(lst.get("slug"))}
        order.append(f.name)
    S.items, S.order = items, order
    if S.selected not in S.items:
        S.selected = next((i for i in order if visible(items[i])), None)
    S.gen += 1
    S.dirty = True


def state_of(it):
    if it["status"] != "posted":
        return None
    return S.listing_state.get(str((it["lst"].get("posted") or {}).get("listing_id")))


def eff_status(it):
    st = state_of(it)
    return "relist" if st and st["relist"] else it["status"]


def visible(it, iid=None):
    st = it["status"]
    if S.filter_char and (it["lst"].get("where") or {}).get("char", "") != S.filter_char:
        return False
    if S.view == "listed":
        return st == "posted"
    if S.show_all:
        return True
    return st in ("ready", "review", "dup", "sending", "error") or (st == "sold" and iid in S.session_sold)


def stem_of(it):
    src = Path(it["lst"].get("source", ""))
    return Path(src.name).stem if src.name else it["file"].name.replace(".listing.json", "")


def save_lst(it):
    it["file"].write_text(json.dumps(it["lst"], ensure_ascii=False, indent=2), encoding="utf-8")


def counts():
    c = {}
    for it in S.items.values():
        k = eff_status(it)
        c[k] = c.get(k, 0) + 1
    return c


def img_url(name):
    p = S.imgs.get(name)
    return f"/cache/img/{p.name}" if p else None


# ---------------- zadania w tle ----------------
async def prefetch_and_hints():
    gen = S.gen
    sem = asyncio.Semaphore(2)

    async def one(iid):
        it = S.items.get(iid)
        if not it:
            return
        name = it["lst"].get("name")
        async with sem:
            item = await run.io_bound(S.item_def, name) if name else None
            if item and name not in S.imgs:
                S.imgs[name] = await run.io_bound(item_image, item)
            if it["status"] in ("ready", "dup") and it["hint"] is None and item:
                try:
                    it["hint"] = await run.io_bound(tpr.suggest, it["lst"], item)
                except Exception as e:
                    it["hint"] = {"text": f"(wycena nie powiodla sie: {e})", "price": "", "levels": {}}
        if gen == S.gen:
            S.dirty = True
    await asyncio.gather(*(one(i) for i in list(S.order)))


async def task(coro_fn, *args):
    """Jedno dlugie zadanie naraz (odczyt, wystawianie, synchronizacja)."""
    if S.busy:
        say(t("Poczekaj - trwa poprzednie zadanie."), "warning")
        return
    S.busy, S.stop = True, False
    S.dirty = True
    try:
        await coro_fn(*args)
    except tm.SessionExpired as e:
        say(str(e), "negative", timeout=10000)
    except Exception:
        log(traceback.format_exc())
        say(t("Cos poszlo nie tak - szczegoly w logu na dole."), "negative")
    finally:
        S.busy, S.progress = False, None
        S.dirty = True


async def do_read(redo: bool):
    import d2_ocr
    log(t("Odczyt screenow (gra musi byc zamknieta - model potrzebuje karty graficznej)") if llm.is_local()
        else t(f"Odczyt screenow w chmurze ({llm.model()}) - gre mozesz zostawic wlaczona"))
    res = await run.io_bound(d2_ocr.run, FOLDER, False, redo, False)
    if res is not None and res < 0:
        say(t("Model nie miesci sie na karcie graficznej - zamknij gre i sprobuj ponownie."), "negative")
        return
    await run.io_bound(d2_ocr.unload_model)
    log(t("Dopasowanie do Traderie"))
    await run.io_bound(tm.run, FOLDER, False)
    load_items()
    asyncio.create_task(prefetch_and_hints())


async def do_sync(quiet=False):
    S.last_sync = time.monotonic()
    sold, state, imported = await run.io_bound(traderie_sync.sync, FOLDER)
    S.listing_state = state
    if imported:
        log(t(f"Zaimportowano z Traderie: {', '.join(imported)}"))
    if sold:
        S.session_sold |= {i for i, it in S.items.items() if it["lst"].get("name") in sold}
        log(t(f"Sprzedane na Traderie: {', '.join(sold)}  - skopiuj post d2jsp ponownie, zeby je z niego usunac"))
        say(t(f"Sprzedane na Traderie: {', '.join(sold)}"))
    if imported or sold:
        load_items()
        asyncio.create_task(prefetch_and_hints())
    if not quiet:
        ready = sum(1 for v in state.values() if v["relist"])
        offers = sum(v["offers"] for v in state.values())
        log(t(f"aktywnych ofert: {len(state)}, gotowych do odnowienia: {ready}, ofert kupna: {offers}"))
    S.dirty = True


async def background_sync():
    """Samoczynne sprawdzenie ofert - w tle, bez blokowania okna.

    Nie idzie przez task(), bo task() ustawia S.busy i wyszarza wszystkie przyciski na czas
    pobierania (30 s na zadanie, a sync() robi ich kilka) - a tego sprawdzenia uzytkownik nie
    zlecal. Z tego samego powodu zerwane polaczenie konczy sie jedna linia w logu, nie sladem
    wyjatku. Przycisk "Sprawdz oferty" nadal idzie przez task(): tam blokada i glosny blad sa
    na miejscu, bo czekamy na wynik.
    """
    try:
        await do_sync()
    except tm.SessionExpired as e:
        say(str(e), "negative", timeout=10000)
    except Exception as e:
        log(t(f"(sprawdzanie ofert: Traderie nie odpowiada - sprobuje pozniej: {e})"))
    finally:
        S.dirty = True


async def notify_tick():
    if not S.notify_on or S.busy:
        return
    try:
        new = await run.io_bound(traderie_notify.fetch_new)
        if new:
            S.notify_new += len(new)
            S.messages = (new + S.messages)[:MAX_MESSAGES]    # najnowsze na gorze
            for when, text in new:
                log(f"[Traderie {when}] {text}")
            say(t(f"Traderie: {len(new)} nowych wiadomosci - kliknij kopertke u gory"), "info")
            S.dirty = True
        await do_sync(quiet=True)
    except Exception as e:
        msg = str(e)
        log(t(f"({t('sprawdzanie ofert')}: Traderie chwilowo niedostepne - sprobuje przy nastepnym sprawdzeniu)")
            if any(c in msg for c in ("502", "503", "504")) else f"(Traderie: {msg})")


async def do_post(plan):
    auth = tm.load_auth()
    registry = tp.load_registry(FOLDER)
    prices = json.loads(tp.PRICES_FILE.read_text(encoding="utf-8")) if tp.PRICES_FILE.exists() else {}
    for n, (iid, it, price, make_offer) in enumerate(plan, 1):
        if n > 1:
            wait = random.randint(*tp.DELAY)
            for left in range(wait, 0, -1):
                if S.stop:
                    log(t("Zatrzymano - reszta zostaje z zapamietanymi cenami."))
                    return
                S.progress = (f"{t('Wystawianie')} {n - 1} / {len(plan)} · {left} s", (n - 1) / len(plan))
                S.dirty = True
                await asyncio.sleep(1)
        lst, f = it["lst"], it["file"]
        item = await run.io_bound(tm.get_item, lst["name"])
        it["status"] = "sending"
        S.progress = (f"{t('Wystawianie')} {n} / {len(plan)} · {lst['name']}", (n - 1) / len(plan))
        S.dirty = True
        status, body = await run.io_bound(tp.post, tp.build_payload(lst, item, price, make_offer), auth)
        try:
            resp = json.loads(body)
        except json.JSONDecodeError:
            resp = {}
        if not resp.get("success") or not resp.get("listing"):
            it["status"] = "error"
            msg = tp.SESSION_EXPIRED if tp.is_expired(body) else body[:300]
            say(t(f"{lst['name']}: nieoczekiwana odpowiedz Traderie:") + " " + msg, "negative", timeout=10000)
            return
        lst["posted"] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "price": it["price"], "listing_id": resp["listing"]}
        lst.pop("planned_price", None)
        save_lst(it)
        registry[tp.fingerprint(lst)] = {"name": lst["name"], **lst["posted"], "source": f.name,
                                         "stats": tp.describe(lst, item)[1]}
        tp.save_registry(registry)
        prices[lst["slug"]] = it["price"]
        tp.PRICES_FILE.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
        it["status"], it["selected"] = "posted", False
        log(t(f"[{n}/{len(plan)}] {lst['name']}: wystawiono za {it['price']}"))
        S.dirty = True
    log(t("Wystawianie zakonczone."))
    say(t("Wystawianie zakonczone."))


# ---------------- akcje ----------------
async def set_price(iid, val: str) -> bool:
    it = S.items[iid]
    val = (val or "").strip().lower()
    if val:
        try:
            await run.io_bound(tp.parse_price, val)
        except ValueError as e:
            say(t(f"{it['lst'].get('name')}: niepoprawna cena '{val}' ({e})"), "negative")
            return False
    it["price"], it["selected"] = val, bool(val)
    if val:
        it["lst"]["planned_price"] = val
    else:
        it["lst"].pop("planned_price", None)
    save_lst(it)
    S.dirty = True
    return True


def toggle_check(iid):
    it = S.items[iid]
    if it["status"] == "posted":        # w widoku wystawionych zaznaczenie wybiera oferty do odnowienia
        it["selected"] = not it["selected"]
        S.dirty = True
        return
    if not it["selected"] and not it["price"]:
        hint = (it["hint"] or {}).get("price")
        if hint:
            asyncio.create_task(set_price(iid, hint))
            return
        ui.notify(t("Najpierw ustaw cene."), type="warning")
        S.dirty = True
        return
    it["selected"] = not it["selected"]
    S.dirty = True


def fill_hints():
    n = 0
    for iid in S.order:
        it = S.items[iid]
        if it["status"] == "ready" and not it["price"] and (it["hint"] or {}).get("price"):
            asyncio.create_task(set_price(iid, it["hint"]["price"]))
            n += 1
    ui.notify(t(f"Ustawiono podpowiedz dla {n} przedmiotow (duplikatow nie ruszam)."))


def mark_reviewed(iid):
    """'Do sprawdzenia' -> gotowy do wystawienia.

    Ostrzezenia (np. 'crafted pojdzie jako rare') zostaja widoczne w panelu - znikaja tylko
    z drogi, bo po obejrzeniu przedmiotu to czlowiek decyduje, czy go wystawic.
    """
    it = S.items[iid]
    it["lst"]["needs_review"] = False
    it["lst"]["reviewed"] = time.strftime("%Y-%m-%d %H:%M")
    save_lst(it)
    log(t(f"Sprawdzone: {it['lst'].get('name') or it['lst'].get('ocr_name', '?')} - mozna wystawic"))
    load_items()


async def toggle_sold(iid):
    it = S.items[iid]
    lst = it["lst"]
    if lst.get("sold"):
        lst.pop("sold")
        lst.pop("sold_via", None)
        save_lst(it)
        S.session_sold.discard(iid)
        load_items()
        return
    lid = (lst.get("posted") or {}).get("listing_id")
    also = await confirm(t("Sprzedany"), t(f"{lst.get('name')} jest wystawiony na Traderie.") + "\n" +
                         t("Oznaczyc go tam tez jako sprzedany (zeby nikt go nie kupil drugi raz)?")) if lid else False
    lst["sold"] = time.strftime("%Y-%m-%d %H:%M")
    save_lst(it)
    S.session_sold.add(iid)
    log(t(f"Oznaczono jako sprzedany: {lst.get('name', '')}  (skopiuj post d2jsp ponownie)"))
    if also:
        ok, msg = await run.io_bound(tp.mark_sold, lid, tm.load_auth())
        say(t(f"Traderie: oferta {lst.get('name')} oznaczona jako sprzedana") if ok
            else t(f"Nie udalo sie oznaczyc na Traderie: {msg}"), "positive" if ok else "negative")
    load_items()


async def toggle_hidden(iid):
    it = S.items[iid]
    lid = str((it["lst"].get("posted") or {}).get("listing_id") or "")
    st = S.listing_state.get(lid)
    visible_now = bool(st and st["hidden"])
    ok, msg = await run.io_bound(tp.set_visible, lid, visible_now, tm.load_auth())
    if not ok:
        say(msg, "negative")
        return
    S.listing_state[lid] = {**(st or {"relist": False, "hours_left": 0, "offers": 0}), "hidden": not visible_now}
    say(t(f"Przywrocono na Traderie: {it['lst'].get('name')}") if visible_now
        else t(f"Ukryto na Traderie: {it['lst'].get('name')}"))
    S.dirty = True


def say(msg, kind="positive", timeout=None):
    """Komunikat w okienku. ui.notify dziala tylko w kontekscie zywego elementu strony, a dlugie
    zadanie przebudowuje widok (S.dirty) i element, ktory je uruchomil, znika. Wtedy zostaje log."""
    try:
        ui.notify(msg, type=kind, **({"timeout": timeout} if timeout else {}))
    except RuntimeError:          # 'The parent element this slot belongs to has been deleted'
        log(f"({msg})")


def relist_ready():
    """[(iid, id oferty)] - wystawione oferty, ktore Traderie pozwala juz odnowic."""
    out = []
    for iid in S.order:
        it = S.items[iid]
        st = state_of(it)
        if st and st["relist"] and not it["lst"].get("sold"):
            out.append((iid, str((it["lst"].get("posted") or {}).get("listing_id"))))
    return out


def relist_plan():
    """Co odnowic: zaznaczone oferty, a gdy nic nie jest zaznaczone - wszystkie gotowe."""
    gotowe = relist_ready()
    return [(i, l) for i, l in gotowe if S.items[i]["selected"]] or gotowe


def check_relist(value: bool):
    """Zaznacza albo odznacza wszystkie oferty gotowe do odnowienia."""
    for iid, _ in relist_ready():
        S.items[iid]["selected"] = value
    S.dirty = True


async def verify_relist(plan):
    """Sprawdza na Traderie, czy odnowienie naprawde zadzialalo.

    Nie wierzymy samej odpowiedzi z /listings/refresh: zdarza sie, ze nie zglasza bledu, a licznik
    oferty zostaje bez zmian. Dlatego pobieramy stan ofert i patrzymy, czy oferta nadal jest
    'do odnowienia'. Lepiej powiedziec 'nie udalo sie' niz skasowac znacznik i udawac, ze gotowe.
    """
    await do_sync(quiet=True)
    udane, nieudane = [], []
    for iid, lid in plan:
        it = S.items.get(iid)
        nazwa = (it["lst"].get("name", "?") if it else lid)
        if (S.listing_state.get(lid) or {}).get("relist"):
            nieudane.append(nazwa)
        else:
            udane.append(nazwa)
            if it:
                it["lst"].setdefault("posted", {})["refreshed"] = time.strftime("%Y-%m-%d %H:%M")
                it["selected"] = False      # odnowione znika z zaznaczenia, zeby nie poszlo drugi raz
                save_lst(it)
    if udane:
        log(t(f"Odnowiono na Traderie: {', '.join(udane)}"))
        say(t(f"Odnowiono na Traderie: {', '.join(udane)}"))
    if nieudane:
        log(t(f"Traderie przyjelo zadanie, ale oferta nadal nie jest odnowiona: {', '.join(nieudane)}"))
        say(t(f"Traderie nie odnowilo: {', '.join(nieudane)} - odnow je na stronie"), "negative")
    S.dirty = True
    return not nieudane


async def relist_one(iid):
    """Odnawia jedna oferte - na Traderie wraca na gore listy."""
    it = S.items[iid]
    lid = str((it["lst"].get("posted") or {}).get("listing_id") or "")
    if not lid:
        return
    nazwa = it["lst"].get("name", "?")
    ok, msg = await run.io_bound(tp.refresh_listing, lid, tm.load_auth())
    if not ok:
        log(f"! {nazwa} ({lid}): {msg}")
        say(t("Nie udalo sie odnowic oferty: ") + msg, "negative")
        return
    await verify_relist([(iid, lid)])


async def do_relist_all():
    """Odnawia po kolei zaznaczone oferty (albo wszystkie gotowe, gdy nic nie zaznaczono),
    z losowa przerwa miedzy nimi - nie zasypujemy Traderie."""
    plan = relist_plan()
    if not plan:
        say(t("Nie ma ofert gotowych do odnowienia."), "info")
        return
    auth = tm.load_auth()
    zrobione = []
    for n, (iid, lid) in enumerate(plan, 1):
        if n > 1:
            wait = random.randint(*tp.REFRESH_DELAY)
            for left in range(wait, 0, -1):
                if S.stop:
                    log(t(f"Zatrzymano - wyslano {len(zrobione)} z {len(plan)}."))
                    break
                S.progress = (f"{t('Odnawianie')} {n - 1} / {len(plan)} · {left} s", (n - 1) / len(plan))
                S.dirty = True
                await asyncio.sleep(1)
            if S.stop:
                break
        nazwa = S.items[iid]["lst"].get("name", "?")
        S.progress = (f"{t('Odnawianie')} {n} / {len(plan)} · {nazwa}", (n - 1) / len(plan))
        S.dirty = True
        ok, msg = await run.io_bound(tp.refresh_listing, lid, auth)
        if not ok:
            log(f"! {nazwa} ({lid}): {msg}")
            say(t("Nie udalo sie odnowic oferty: ") + msg, "negative")
            break
        zrobione.append((iid, lid))
        log(t(f"[{n}/{len(plan)}] {nazwa}: wyslano odnowienie"))
    if zrobione:
        await verify_relist(zrobione)


def set_where(iid, char=None, stash=None):
    """Zapisuje, na ktorej postaci i w ktorym miejscu lezy przedmiot (potrzebne przy odbiorze po sprzedazy)."""
    it = S.items[iid]
    w = dict(it["lst"].get("where") or {})
    if char is not None:
        w["char"] = (char or "").strip()
    if stash is not None:
        w["stash"] = stash or ""
    w = {k: v for k, v in w.items() if v}
    if w:
        it["lst"]["where"] = w
    else:
        it["lst"].pop("where", None)
    save_lst(it)
    S.dirty = True


def where_label(lst) -> str:
    """'Nazwa postaci · Skrzynia wspolna 2' albo pusty tekst."""
    w = lst.get("where") or {}
    return " · ".join(p for p in (w.get("char", ""), t(w.get("stash", ""))) if p)


def chars_known():
    """Nazwy postaci wpisane przy przedmiotach - do filtra w widoku listy."""
    return sorted({(it["lst"].get("where") or {}).get("char", "") for it in S.items.values()} - {""})


def pickup_text() -> str:
    """Co wyjac: sprzedane przedmioty pogrupowane po postaci i miejscu."""
    groups = {}
    for iid in S.order:
        lst = S.items[iid]["lst"]
        if not lst.get("sold"):
            continue
        w = lst.get("where") or {}
        key = (w.get("char") or t("(postac niewpisana)"), t(w.get("stash", "")) or t("(miejsce niewpisane)"))
        price = (lst.get("posted") or {}).get("price", "")
        groups.setdefault(key, []).append(f"  - {lst.get('name', '?')}" + (f"  ({price})" if price else ""))
    if not groups:
        return ""
    out = []
    for (char, stash), rows in sorted(groups.items()):
        out.append(f"{char} / {stash}:")
        out += sorted(rows)
        out.append("")
    return "\n".join(out).strip()


def messages_dialog():
    """Wiadomosci z Traderie zebrane w tle. Z okna mozna przejsc na strone Traderie."""
    S.notify_new = 0                      # otwarcie = przeczytane; plakietka znika
    S.dirty = True
    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("width: 560px; max-width: 95vw"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label(t("Wiadomosci z Traderie")).style("font-size:15px; font-weight:600").classes("flex-grow")
            ui.button(t("Otworz na Traderie"), on_click=lambda: webbrowser.open(TRADERIE_WWW)) \
                .props("unelevated no-caps dense").classes("ghost px-3")
        if not S.messages:
            ui.label(t("Na razie nic nie przyszlo. Program sprawdza wiadomosci co 5 minut, "
                       "gdy przelacznik w pasku bocznym jest wlaczony.")).style(f"font-size:12.5px; color:{MUTED}")
        else:
            with ui.column().classes("w-full gap-0").style("max-height:50vh; overflow:auto"):
                for i, (when, text) in enumerate(S.messages):
                    with ui.column().classes("w-full gap-0 py-2") \
                            .style(f"border-top:1px solid {LINE}" if i else ""):
                        ui.label(when or "-").classes("mono").style(f"font-size:11px; color:{FAINT}")
                        ui.label(text).style("font-size:12.5px")
        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            if S.messages:
                ui.button(t("Wyczysc liste"), on_click=lambda: (S.messages.clear(), d.close(),
                                                                setattr(S, "dirty", True))) \
                    .props("unelevated no-caps dense").classes("ghost px-3")
            ui.button(t("Zamknij"), on_click=d.close).props("unelevated no-caps dense").classes("ghost px-3")
    d.on("hide", lambda: d.delete())
    d.open()


def pickup_dialog():
    """Okno 'Co wyjac': lista sprzedanych przedmiotow wedlug postaci i skrzyni, do skopiowania."""
    text = pickup_text()
    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("min-width: 520px"):
        ui.label(t("Co wyjac (sprzedane)")).style("font-size:15px; font-weight:600")
        if not text:
            ui.label(t("Nic nie czeka na odbior - albo przy sprzedanych nie ma wpisanej postaci.")) \
                .style(f"color:{MUTED}")
            ui.label(t("Wpisz postac i skrzynie w panelu przedmiotu (GDZIE LEZY) - po sprzedazy "
                       "zbierze sie tu lista do wyjecia.")).style(f"font-size:13px; color:{MUTED}")
        else:
            ui.label(t("Zaloguj sie na te postacie i wyjmij przedmioty:")).style(f"font-size:13px; color:{MUTED}")
            ui.label(text).style("white-space: pre-line; font-family: ui-monospace, monospace; font-size:13px")
        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            if text:
                ui.button(t("Kopiuj"), on_click=lambda: (ui.clipboard.write(text),
                                                         ui.notify(t("Skopiowano liste."))))\
                    .props("unelevated no-caps dense")
            ui.button(t("Zamknij"), on_click=d.close).props("flat no-caps")
    d.open()


async def remove_listing(iid):
    it = S.items[iid]
    lst = it["lst"]
    lid = (lst.get("posted") or {}).get("listing_id")
    if not lid or not await confirm(t("Usun z Traderie"), t(f"Usunac oferte {lst.get('name')} z Traderie?") + "\n" +
                                    t("Przedmiot wroci na liste jako gotowy do wystawienia.")):
        return
    ok, msg = await run.io_bound(tp.remove_listing, lid, tm.load_auth())
    if not ok:
        say(t(f"Nie udalo sie usunac oferty: {msg}"), "negative")
        return
    tp.unregister(lst)
    lst["removed"] = {"time": time.strftime("%Y-%m-%d %H:%M"), **lst.pop("posted")}
    save_lst(it)
    log(t(f"Usunieto z Traderie: {lst.get('name')}"))
    load_items()


async def delete_item(iid):
    it = S.items[iid]
    lst = it["lst"]
    lid = (lst.get("posted") or {}).get("listing_id") if it["status"] == "posted" else None
    if lid:
        choice = await choose(t("Usun z listy"), t(f"{lst.get('name')} jest wystawiony na Traderie."),
                              [("both", t("Usun z listy i zdejmij z Traderie")), ("list", t("Tylko z listy")),
                               ("cancel", t("Anuluj"))])
        if choice in (None, "cancel"):
            return
        if choice == "both":
            ok, msg = await run.io_bound(tp.remove_listing, lid, tm.load_auth())
            if not ok:
                say(t(f"Nie udalo sie zdjac oferty z Traderie: {msg}"), "negative")
                return
            tp.unregister(lst)
            lst["removed"] = {"time": time.strftime("%Y-%m-%d %H:%M"), **lst.pop("posted")}
            save_lst(it)
    elif not await confirm(t("Usun z listy"), t(f"Usunac {lst.get('name') or lst.get('ocr_name')} z listy?")):
        return
    trash = FOLDER / traderie_sync.TRASH
    trash.mkdir(exist_ok=True)
    stem = stem_of(it)
    files = [it["file"]] + [p for p in FOLDER.glob(stem + ".*") if p != it["file"]]
    files += list((FOLDER / "_crops").glob(stem + ".*"))
    for p in files:
        if p.exists():
            p.replace(trash / p.name)
    log(t(f"Usunieto z listy: {lst.get('name') or lst.get('ocr_name')}"))
    S.selected = None
    load_items()


WIPE_WORD = "USUWAM"      # trzeba przepisac recznie - zapora przed klikniecem z rozpedu


def wipe_scope() -> tuple:
    """(ile przedmiotow lokalnie, [(iid, id oferty)] zywych ofert na Traderie)."""
    oferty = [(i, (S.items[i]["lst"].get("posted") or {}).get("listing_id"))
              for i in S.order if S.items[i]["status"] in ("posted", "relist")]
    return len(S.items), [(i, lid) for i, lid in oferty if lid]


async def wipe_everything(z_traderie: bool):
    """Czyszczenie wszystkiego: kopia -> zdjecie ofert z Traderie -> skasowanie danych lokalnych.

    Kolejnosc nie jest przypadkowa. Kopia idzie pierwsza, bo reszty nie da sie cofnac. Oferty
    zdejmujemy przed kasowaniem lokalnym: gdyby ktoras sie nie dala, przerywamy i zostawiamy dane
    w spokoju - inaczej na Traderie wisialyby oferty, o ktorych program juz nic nie wie.
    Ustawienia, sekrety i cache zostaja (paths.KEEP).
    """
    kopia = await run.io_bound(paths.backup_zip, "przed_czyszczeniem")
    log(t(f"Kopia przed czyszczeniem: {kopia.name}"))
    _, oferty = wipe_scope()
    if z_traderie and oferty:
        auth = tm.load_auth()
        for n, (iid, lid) in enumerate(oferty, 1):
            if n > 1:
                wait = random.randint(*tp.REFRESH_DELAY)
                for left in range(wait, 0, -1):
                    if S.stop:
                        break
                    S.progress = (f"{t('Zdejmowanie ofert')} {n - 1} / {len(oferty)} · {left} s",
                                  (n - 1) / len(oferty))
                    S.dirty = True
                    await asyncio.sleep(1)
            if S.stop:
                say(t(f"Zatrzymano - zdjeto {n - 1} z {len(oferty)}. Nic nie zostalo skasowane."), "warning")
                return
            nazwa = S.items[iid]["lst"].get("name", "?")
            S.progress = (f"{t('Zdejmowanie ofert')} {n} / {len(oferty)} · {nazwa}", (n - 1) / len(oferty))
            S.dirty = True
            ok, msg = await run.io_bound(tp.remove_listing, lid, auth)
            if not ok:
                log(f"! {nazwa} ({lid}): {msg}")
                say(t(f"Nie udalo sie zdjac oferty z Traderie ({nazwa}) - przerywam, dane zostaja: {msg}"),
                    "negative", timeout=12000)
                return
            log(t(f"[{n}/{len(oferty)}] zdjeto z Traderie: {nazwa}"))
    ile = await run.io_bound(paths.wipe_data)
    S.selected, S.page = None, 1
    load_items()
    log(t(f"Wyczyszczono dane: usunietych plikow {ile['plikow']}. Kopia: {kopia.name}"))
    say(t(f"Dane wyczyszczone. Kopia zostala w backups/{kopia.name}"), "positive", timeout=12000)


def wipe_dialog():
    """Okno czyszczenia: pokazuje zakres, wymaga przepisania slowa, kopia robi sie sama."""
    ile, oferty = wipe_scope()
    with S.host, ui.dialog() as d, ui.card().classes("p-5 gap-2").style("width: 560px; max-width: 95vw"):
        ui.label(t("Wyczysc wszystkie dane")).style(f"font-size:15px; font-weight:600; color:{BAD}")
        ui.label(t(f"Zostanie usunietych {ile} przedmiotow (screeny, odczyty, dopasowania), "
                   "rejestr wystawionych i zapamietane ceny.")).style("white-space:pre-line")
        ui.label(t("Zostaja: ustawienia, token i klucz API, cache przedmiotow, logi i kopie."))\
            .style(f"font-size:12px; color:{MUTED}")
        zdejmij = ui.checkbox(t(f"Zdejmij tez {len(oferty)} ofert z Traderie"), value=bool(oferty)) \
            .props("dense size=xs")
        if not oferty:
            zdejmij.set_visibility(False)
        else:
            ui.label(t("Zdejmowanie idzie po kolei, z przerwami - przy wielu ofertach potrwa.")) \
                .style(f"font-size:12px; color:{MUTED}")
        ui.label(t(f"Kopia zapisze sie sama w backups/ przed usunieciem. Zeby potwierdzic, "
                   f"przepisz slowo: {WIPE_WORD}")).style("white-space:pre-line; padding-top:6px")
        pole = ui.input(placeholder=WIPE_WORD).props("outlined dense").classes("w-full")
        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            ui.button(t("Anuluj"), on_click=d.close).props("unelevated no-caps dense").classes("primary px-3")
            usun = ui.button(t("Usun bezpowrotnie"),
                             on_click=lambda: (d.close(), asyncio.create_task(
                                 task(wipe_everything, bool(zdejmij.value))))) \
                .props("unelevated no-caps dense").classes("ghost px-3") \
                .style(f"color:{BAD}; border-color:{BAD}")
            usun.set_enabled(False)      # odblokowuje dopiero przepisane slowo
            pole.on_value_change(lambda e: usun.set_enabled((e.value or "").strip() == WIPE_WORD))
    d.on("hide", lambda: d.delete())
    d.open()


async def start_post():
    wybrane = [(iid, S.items[iid]) for iid in S.order
               if S.items[iid]["selected"] and S.items[iid]["status"] in ("ready", "dup")]
    if not wybrane:
        say(t("Nic nie jest zaznaczone. Ustaw ceny przedmiotom, ktore chcesz wystawic."), "warning")
        return
    if not tm.load_auth():
        say(t(f"Brak lub niepoprawny plik {tm.AUTH_FILE}."), "negative")
        return
    # Przedmiot rozpoznany z plikow gry ma wlasne numery wlasciwosci - oferta byla by bledna.
    # Sprawdzamy to przed cenami: inaczej uzytkownik uslyszalby o zlej cenie, a prawdziwa
    # przeszkoda jest inna. Bez tego build_payload przerywal w polowie wystawiania.
    lokalne = [it["lst"]["name"] for _, it in wybrane if it["lst"].get("local")]
    if lokalne:
        say(t("Rozpoznane bez Traderie (odczytaj screeny ponownie, zeby wystawic): ")
            + ", ".join(lokalne[:5]), "negative", timeout=10000)
        return
    plan = []
    for iid, it in wybrane:
        try:
            price, make_offer = await run.io_bound(tp.parse_price, it["price"])
        except ValueError as e:
            say(f"{it['lst']['name']}: {e}", "negative")
            return
        plan.append((iid, it, price, make_offer))
    mins = round((len(plan) - 1) * sum(tp.DELAY) / 2 / 60) or 1
    body = "\n".join(f"{it['lst']['name']}  -  {it['price']}" for _, it, _, _ in plan[:25])
    if await confirm(t("Wystawic?"), t(f"{len(plan)} przedmiotow, potrwa ok. {mins} min:") + "\n\n" + body):
        await task(do_post, plan)


# ---------------- okienka ----------------
async def confirm(title, text) -> bool:
    return await choose(title, text, [("yes", t("Tak")), ("no", t("Nie"))]) == "yes"


async def choose(title, text, options):
    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("min-width: 420px"):
        ui.label(title).style("font-size:15px; font-weight:600")
        ui.label(text).style(f"white-space: pre-line; color:{MUTED}")
        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            for i, (key, label) in enumerate(options):
                b = ui.button(label, on_click=lambda k=key: d.submit(k)).props("unelevated no-caps dense")
                if i == 0:
                    b.classes("primary")
                else:
                    b.classes("ghost")
    result = await d
    d.delete()                       # zamkniete okno nie zostaje na stronie
    return result


def price_dialog(iid):
    it = S.items[iid]
    cur = it["price"] or (it["hint"] or {}).get("price", "")
    groups = parse_groups(cur)
    st = {"active": len(groups) - 1, "offer": cur.strip().lower() == "offer"}

    def text():
        if st["offer"]:
            return "offer"
        return " | ".join("+".join(f"{q} {n}" if q > 1 else n for q, n in g) for g in groups if g)

    def add(name, qty=None):
        qty = int(qty or qty_in.value or 1)
        st["offer"] = False
        key = tpr.short(name)
        g = groups[st["active"]]
        for i, (q, n) in enumerate(g):
            if n == key:
                g[i] = (q + qty, n)
                break
        else:
            g.append((qty, key))
        asyncio.create_task(run.io_bound(tm.get_item, name))
        body.refresh()

    def any_keys():
        qty = int(qty_in.value or 1)
        if groups == [[]]:
            groups.clear()
        for k in ("Key of Terror", "Key of Hate", "Key of Destruction"):
            groups.append([(qty, tpr.short(k))])
        st["active"], st["offer"] = len(groups) - 1, False
        body.refresh()

    async def search(e=None):
        q = (e.args if e is not None and isinstance(getattr(e, "args", None), str) else (search_in.value or "")).strip()
        results.clear()
        if len(q) < 2:
            return
        names = await run.io_bound(tp.search_items, q, 20)
        if (search_in.value or q).strip() != q:
            return
        results.clear()
        with results:
            for n in names or [t("(nic nie znaleziono)")]:
                ui.button(n, on_click=lambda n=n: add(n)).props("flat no-caps dense").classes("w-full justify-start") \
                    .style(f"color:{INK}; border-radius:3px")

    async def save():
        if await set_price(iid, text()):
            d.close()

    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("width: 640px; max-width: 95vw"):
        ui.label(t(f"Cena: {it['lst'].get('name', '?')}")).style("font-size:15px; font-weight:600")
        ui.label(t("Szukaj przedmiotu (np. terror, ist, essence, perfect)")).classes("sec")
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            search_in = ui.input(placeholder="terror").props("outlined dense").classes("flex-grow") \
                .on("update:model-value", search, throttle=0.4)
            qty_in = ui.number(t("ilosc:"), value=1, min=1, max=999, format="%d").props("outlined dense").style("width: 100px")
        results = ui.column().classes("w-full gap-0").style("max-height: 160px; overflow:auto")
        ui.label(t("Szybko")).classes("sec pt-2")
        with ui.row().classes("gap-1"):
            for r in ("Lem", "Pul", "Um", "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber", "Jah", "Cham", "Zod"):
                ui.button(r, on_click=lambda r=r: add(r + " Rune")).props("unelevated no-caps dense").classes("ghost px-3")
        with ui.row().classes("gap-1"):
            for k in ("Perfect Amethyst", "Key of Terror", "Key of Hate", "Key of Destruction"):
                ui.button(k, on_click=lambda k=k: add(k)).props("unelevated no-caps dense").classes("ghost px-3")
            ui.button(t("Dowolne klucze"), on_click=any_keys).props("unelevated no-caps dense").mark("any-keys") \
                .classes("ghost px-3").style(f"color:{WARN}; border-color:{WARN}")
        ui.label(t("Cena (opcje ALBO - kupujacy wybiera jedna)")).classes("sec pt-2")

        @ui.refreshable
        def body():
            for gi, g in enumerate(groups):
                if gi:
                    ui.label(t("albo")).classes("sec")
                on = gi == st["active"]
                with ui.row().classes("w-full items-center gap-2 p-2 cursor-pointer").style(
                        f"border-radius:3px; background:{PANEL3 if on else PANEL2}; "
                        f"border:1px solid {LINE2 if on else LINE}").on("click", lambda gi=gi: (st.update(active=gi), body.refresh())):
                    if not g:
                        ui.label(t("(pusta - dodaj przedmiot)")).style(f"color:{MUTED}")
                    for ii, (q, n) in enumerate(g):
                        with ui.row().classes("items-center gap-0"):
                            ui.label(f"{q} × {' '.join(w if w in ('of', 'the') else w.capitalize() for w in n.split())}").classes("mono")
                            ui.button(icon="close", on_click=lambda gi=gi, ii=ii: remove(gi, ii)).props("flat round dense size=sm") \
                                .style(f"color:{BAD}")
            preview = text()
            ui.label(t(f"Zapisze jako: {preview}") if preview else t("Zapisze jako: (bez ceny - przedmiot nie bedzie wystawiony)")) \
                .classes("mono").style(f"color:{WARN}")

        def remove(gi, ii):
            del groups[gi][ii]
            if not groups[gi] and len(groups) > 1:
                del groups[gi]
                st["active"] = min(st["active"], len(groups) - 1)
            body.refresh()

        def new_group():
            if groups[-1]:
                groups.append([])
            st["active"] = len(groups) - 1
            body.refresh()

        body()
        with ui.row().classes("gap-2 items-center"):
            ui.button(t("+ Dodaj opcje ALBO"), on_click=new_group).props("unelevated no-caps dense").classes("ghost")
            ui.button(t("Wyczysc"), on_click=lambda: (groups.clear(), groups.append([]), st.update(active=0, offer=False),
                                                      body.refresh())).props("unelevated no-caps dense").classes("ghost")
            ui.checkbox(t("Bez ceny - czekam na oferty"), value=st["offer"],
                        on_change=lambda e: (st.update(offer=e.value), body.refresh()))
        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            ui.button(t("Anuluj"), on_click=d.close).props("unelevated no-caps dense").classes("ghost")
            ui.button(t("Zapisz"), on_click=save).props("unelevated no-caps dense").classes("primary").mark("price-save")
    d.on("hide", lambda: d.delete())
    d.open()


def parse_groups(text):
    text = (text or "").strip().lower()
    if not text or text == "offer":
        return [[]]
    groups = []
    for alt in text.split("|"):
        g = []
        for part in alt.split("+"):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"(\d+)\s+(.+)", part)
            g.append((int(m.group(1)), m.group(2)) if m else (1, part))
        groups.append(g)
    return groups or [[]]


def settings_dialog():
    cur = app_config.current()
    vals = {k: cur[k] for k in ("seller_id", "token", "platform", "mode", "ladder", "game_version")}
    vals.update({k: cur[k] for k in app_config.LLM_FIELDS})
    vals["llm_key"] = cur.get("llm_key", "")      # sekret: z pliku, nie z settings.json
    vals["d2jsp_runes"] = d2jsp_post.show_runes()
    vals["d2jsp_fg"] = d2jsp_post.show_fg()
    vals["d2jsp_fg_per_ist"] = d2jsp_post.fg_per_ist()
    vals["fg_in_app"] = fg_in_app()
    # katalog gry: zapamietany, a przy pierwszym uruchomieniu zgadniety z typowych miejsc
    vals["game_dir"] = i18n.settings().get("game_dir") or (game_casc.zgadnij_gre() or "")

    def fg_hint():
        """Podglad: jak bedzie wygladac cena w poscie przy obecnych ustawieniach."""
        kurs = float(vals["d2jsp_fg_per_ist"] or 0)
        fg_dziala = vals["d2jsp_fg"] and kurs > 0
        if not vals["d2jsp_runes"] and not fg_dziala:
            fg_msg.set_text(t("post bedzie bez cen - wlacz runy albo FG z kursem"))
            return
        if not fg_dziala:
            fg_msg.set_text(t("ceny tylko w runach") if not vals["d2jsp_fg"]
                            else t("FG wlaczone, ale bez kursu - w poscie beda runy"))
            return
        ist, mal = (tpr.load_runes() or {}).get("Ist Rune"), (tpr.load_runes() or {}).get("Mal Rune")
        wzor = (f"ist + mal (~{d2jsp_post.fg_round((1 + mal / ist) * kurs):g} fg)" if vals["d2jsp_runes"]
                else f"{d2jsp_post.fg_round((1 + mal / ist) * kurs):g} fg") if ist and mal else ""
        fg_msg.set_text(t(f"przyklad: {wzor}") if wzor else
                        t(f"ist = {kurs:g} fg - kursy innych walut poznam przy najblizszej wycenie"))

    def describe(e=None):
        tok = app_config.normalize_token(vals["token"])
        if not tok:
            info.set_text(t("brak tokenu - wystawianie i sprawdzanie ofert nie beda dzialac"))
            info.style(f"color:{BAD}")
            return
        problem = app_config.token_problem(tok)
        if problem:
            info.set_text(t(problem))
            info.style(f"color:{BAD}")
            return
        ti = app_config.token_info(tok)
        parts = []
        if ti.get("expires"):
            left = (ti["expires"] - datetime.now()).total_seconds() / 86400
            parts.append(f"wazny do {ti['expires']:%Y-%m-%d %H:%M}" +
                         (" (WYGASL)" if left < 0 else f" (jeszcze {left:.0f} dni)" if left >= 1 else " (wygasa dzis)"))
        if ti.get("user_id"):
            parts.append(f"ID w tokenie: {ti['user_id']}")
            if not (seller.value or "").strip():
                seller.value = ti["user_id"]
        info.set_text(t("token OK" + (" - " + ", ".join(parts) if parts else "")))
        info.style(f"color:{BAD}" if "WYGASL" in " ".join(parts) else f"color:{OK}")

    async def load_models():
        """Lista modeli z endpointu - z cennikiem i dlugoscia kontekstu."""
        msg.set_text(t("sprawdzam..."))
        with tmp_llm():
            try:
                got = await run.io_bound(llm.models)
            except Exception as e:
                msg.set_text(t(f"Nie udalo sie pobrac listy modeli: {e}"))
                msg.style(f"color:{BAD}")
                return
        mdl.options = [m.get("id") for m in got if m.get("id")]
        mdl.update()
        cur_m = next((m for m in got if m.get("id") == vals[model_key()]), None)
        if cur_m:
            p = cur_m.get("pricing") or {}
            ctx = f"{cur_m['context_length']:,}".replace(",", " ") if cur_m.get("context_length") else "?"
            cena = (f", cena: {p.get('prompt')}/{p.get('completion')} {p.get('currency_unit', '')} za token"
                    if p.get("prompt") else "")
            msg.set_text(t(f"Modeli: {len(got)} | {vals[model_key()]}: kontekst {ctx}{cena}"))
        else:
            msg.set_text(t(f"Pobrano modeli: {len(got)}"))
        msg.style(f"color:{OK}")

    @contextlib.contextmanager
    def tmp_llm():
        """Na czas testu podstawia ustawienia z okna, potem przywraca poprzednie.

        Klucz API idzie obok ustawien (llm.override_key), zeby dalo sie sprawdzic swiezo wklejony
        klucz, zanim trafi do pliku."""
        prev = {k: llm.cfg(k) for k in app_config.LLM_FIELDS}
        st = i18n.settings()
        st.update({k: vals[k] for k in app_config.LLM_FIELDS})
        i18n.SETTINGS.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        llm.override_key(vals.get("llm_key"))
        try:
            yield
        finally:
            llm.override_key(None)
            st.update(prev)
            i18n.SETTINGS.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    async def test_llm():
        msg.set_text(t("sprawdzam..."))
        with tmp_llm():
            ok, text = await run.io_bound(llm.test_connection)
        msg.set_text(t(text))
        msg.style(f"color:{OK}" if ok else f"color:{BAD}")

    async def test():
        # wynik idzie do 'info' - etykiety w sekcji konta, tuz pod przyciskiem, a nie na dol okna
        tok = app_config.normalize_token(vals["token"])
        if not tok or app_config.token_problem(tok):
            info.set_text(t("Najpierw wklej poprawny token."))
            info.style(f"color:{BAD}")
            return
        info.set_text(t("sprawdzam..."))
        info.style(f"color:{MUTED}")
        old = (traderie_sync.SELLER_ID, dict(tm.load_auth()))
        traderie_sync.SELLER_ID, tm._AUTH = (seller.value or "").strip(), {"Authorization": tok}
        try:
            ok, text = await run.io_bound(app_config.test_connection)
        finally:
            traderie_sync.SELLER_ID, tm._AUTH = old[0], old[1]
        info.set_text(t(text))
        info.style(f"color:{OK}" if ok else f"color:{BAD}")

    def save():
        vals["seller_id"] = (seller.value or "").strip()
        tok = app_config.normalize_token(vals["token"])
        if tok and app_config.token_problem(tok):
            msg.set_text(t("Popraw token: " + app_config.token_problem(tok)))
            return
        # puste ID jest w porzadku: bez konta Traderie program i tak dziala na danych z gry
        if vals["seller_id"] and not vals["seller_id"].isdigit():
            msg.set_text(t("ID konta powinno skladac sie z samych cyfr (z adresu listy ofert: seller=...)."))
            return
        app_config.save(vals)
        i18n.save_setting("d2jsp_runes", bool(vals["d2jsp_runes"]))
        i18n.save_setting("d2jsp_fg", bool(vals["d2jsp_fg"]))
        i18n.save_setting("d2jsp_fg_per_ist", float(vals["d2jsp_fg_per_ist"] or 0))
        i18n.save_setting("fg_in_app", bool(vals["fg_in_app"]))
        _FG["when"] = 0          # przelicznik w oknie ma sie zmienic od razu, nie po 5 s
        if lang.value != i18n.current():
            i18n.save_setting("lang", lang.value)
            ui.notify(t("Zmiana jezyka zadziala po ponownym uruchomieniu programu."), type="info", timeout=8000)
        ui.notify(t("Zapisano ustawienia."), type="positive")
        d.close()

    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("width: 620px; max-width: 95vw"):
        ui.label(t("Ustawienia")).style("font-size:15px; font-weight:600")
        ui.label(t("Konto Traderie")).classes("sec pt-2")
        # ID konta zasloniete tak jak token i klucz API - zeby nie swiecilo na nagraniu ani zrzucie
        seller = ui.input(t("ID konta (seller):"), value=vals["seller_id"], password=True,
                          password_toggle_button=True).props("outlined dense").classes("w-full")
        ui.input(t("Token (naglowek Authorization):"), value=vals["token"], password=True, password_toggle_button=True,
                 on_change=lambda e: (vals.update(token=e.value or ""), describe())).props("outlined dense").classes("w-full")
        ui.label(t("Wklej z DevTools (widok Nieprzetworzone) cala linie Authorization albo sam token.")).style(f"color:{MUTED}; font-size:12px")
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            info = ui.label("").classes("flex-grow").style("font-size:12.5px")
            ui.button(t("Testuj polaczenie"), on_click=test).props("unelevated no-caps dense").classes("ghost px-3")

        ui.label(t("Dane z gry")).classes("sec pt-3")
        ui.label(t("Bez tokenu Traderie program czyta przedmioty wprost z Twojej instalacji gry: "
                   "staty, zakresy i ikony. Wskaz katalog i nacisnij przycisk - potrwa to "
                   "kilkanascie sekund.")).style(f"color:{MUTED}; font-size:12px")
        gra = ui.input(t("Katalog z Diablo II: Resurrected:"), value=vals["game_dir"],
                       on_change=lambda e: vals.update(game_dir=e.value or "")) \
            .props("outlined dense").classes("w-full")
        editable(gra)
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            gra_info = ui.label("").classes("flex-grow").style("font-size:12.5px")
            gra_btn = ui.button("", on_click=lambda: wyciagnij()).props("unelevated no-caps dense") \
                .classes("ghost px-3")
        ui.label(t("Program tylko czyta pliki gry - niczego w niej nie zmienia i nie wysyla ich dalej.")) \
            .style(f"color:{FAINT}; font-size:11.5px")

        def opisz_gre():
            """Stan lokalnej bazy: ile przedmiotow, ile ikon, z kiedy."""
            m = game_source.meta()
            if game_source.dostepne() and m:
                gra_info.set_text(t("baza gotowa: {0} przedmiotow, {1} ikon ({2})").format(
                    m.get("items", 0), m.get("icons", 0), m.get("created", "")))
                gra_info.style(f"color:{OK}")
                gra_btn.set_text(t("Odswiez baze"))
            else:
                gra_info.set_text(t("brak lokalnej bazy"))
                gra_info.style(f"color:{FAINT}")
                gra_btn.set_text(t("Wyciagnij dane z gry"))

        async def wyciagnij():
            sciezka = (vals["game_dir"] or "").strip()
            if not sciezka:
                gra_info.set_text(t("Najpierw podaj katalog z gra."))
                gra_info.style(f"color:{BAD}")
                return
            gra_btn.disable()
            gra_info.set_text(t("czytam pliki gry..."))
            gra_info.style(f"color:{MUTED}")
            try:
                await run.io_bound(game_extract.zbuduj, sciezka, log)
            except Exception as e:
                gra_info.set_text(str(e).splitlines()[0][:160])
                gra_info.style(f"color:{BAD}")
                log(traceback.format_exc())
                return
            finally:
                gra_btn.enable()
            # katalogi czytane leniwie - po przebudowie trzeba je zapomniec
            game_source.odswiez()
            game_db._INDEKS = None
            rare_eval.przeladuj()
            S.defs.clear()
            S.imgs.clear()
            i18n.save_setting("game_dir", sciezka)
            opisz_gre()
            S.dirty = True

        opisz_gre()
        ui.label(t("Domyslne ustawienia ofert")).classes("sec pt-3")
        with ui.grid(columns=2).classes("w-full gap-3"):
            for key, label in (("platform", "Platforma:"), ("mode", "Tryb:"), ("ladder", "Ladder:"), ("game_version", "Wersja gry:")):
                ui.select(app_config.OPTIONS[key], label=t(label), value=vals[key],
                          on_change=lambda e, k=key: vals.update({k: e.value})).props("outlined dense")
        ui.label(t("Model (odczyt screenow)")).classes("sec pt-3")
        def model_key():
            return "llm_model" if vals["llm_provider"] == "ollama" else "llm_model_cloud"

        def switch_provider(value):
            vals["llm_provider"] = value
            cloud.set_visibility(value != "ollama")
            mdl.options = [vals[model_key()]]    # najpierw opcje, potem wartosc - inaczej pole sie czysci
            mdl.value = vals[model_key()]        # kazdy dostawca ma zapamietany swoj model
            mdl.update()

        with ui.row().classes("w-full gap-3 items-center no-wrap"):
            ui.select({"ollama": "Ollama (lokalnie, GPU)", "openai": "Chmura (OVH AI Endpoints)"},
                      label=t("Gdzie liczy model:"), value=vals["llm_provider"],
                      on_change=lambda e: switch_provider(e.value)).props("outlined dense").classes("flex-grow")
            mdl = ui.select([vals[model_key()]], value=vals[model_key()], label=t("Model:"), with_input=True,
                            new_value_mode="add-unique",
                            on_change=lambda e: vals.update({model_key(): e.value or ""})) \
                .props("outlined dense").classes("flex-grow")
            ui.button(icon="refresh", on_click=lambda: load_models()).props("flat round dense").tooltip(t("Pobierz liste modeli"))
        with ui.column().classes("w-full gap-2") as cloud:
            ui.input(t("Adres endpointu:"), value=vals["llm_url"],
                     on_change=lambda e: vals.update(llm_url=e.value or "")).props("outlined dense").classes("w-full")
            # nazwy pliku nie pytamy - klucz wklejony tutaj zapisuje sie w secrets/ pod stala nazwa
            ui.input(t("Klucz API:"), value=vals["llm_key"], password=True, password_toggle_button=True,
                     on_change=lambda e: vals.update(llm_key=e.value or "")).props("outlined dense").classes("w-full")
            gdzie = f"{paths.SECRETS.name}/{vals['llm_key_file']}"   # jedna wstawka: klucz tlumaczenia ma {0}
            ui.label(t(f"Klucz trafia do {gdzie} obok programu, nie do ustawien.")) \
                .style(f"font-size:12px; color:{MUTED}")
        cloud.set_visibility(vals["llm_provider"] != "ollama")
        with ui.row().classes("gap-2 items-center"):
            ui.button(t("Testuj model"), on_click=test_llm).props("unelevated no-caps dense").classes("ghost px-3")
            ui.button(t("Zuzycie tokenow"), on_click=usage_dialog).props("unelevated no-caps dense").classes("ghost px-3")
        ui.label(t("Post d2jsp")).classes("sec pt-3")
        with ui.row().classes("gap-4 items-center"):
            ui.checkbox(t("Ceny w runach"), value=vals["d2jsp_runes"],
                        on_change=lambda e: (vals.update(d2jsp_runes=bool(e.value)), fg_hint())).props("dense size=xs")
            ui.checkbox(t("Ceny w FG"), value=vals["d2jsp_fg"],
                        on_change=lambda e: (vals.update(d2jsp_fg=bool(e.value)), fg_hint())).props("dense size=xs")
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.number(t("Ile FG za 1 Ist:"), value=vals["d2jsp_fg_per_ist"], min=0, max=100000, format="%g",
                      on_change=lambda e: (vals.update(d2jsp_fg_per_ist=e.value or 0), fg_hint())) \
                .props("outlined dense").style("width:170px")
            fg_msg = ui.label("").classes("flex-grow").style(f"font-size:12px; color:{MUTED}")
        ui.label(t("0 = bez FG. Kurs wpisujesz recznie z ofert na d2jsp - nie ma do tego zrodla, "
                   "ktore wolno odpytywac. Reszte walut program przelicza po kursach z Traderie.")) \
            .style(f"font-size:12px; color:{FAINT}")
        ui.checkbox(t("Pokazuj FG takze w oknie, przy cenach przedmiotow"), value=vals["fg_in_app"],
                    on_change=lambda e: vals.update(fg_in_app=bool(e.value))).props("dense size=xs")
        fg_hint()
        ui.label(t("Wyglad")).classes("sec pt-3")
        with ui.row().classes("items-center gap-2"):
            # zmiana dziala od razu, bez "Zapisz": motyw widac natychmiast, wiec wybor ocenia sie okiem
            ui.select({"dark": t("Ciemny"), "light": t("Jasny")}, value=motyw(),
                      on_change=lambda e: set_motyw(e.value)).props("outlined dense").style("width: 220px")
            ui.label(t("zmiana widoczna od razu")).style(f"font-size:12px; color:{FAINT}")
        ui.label(t("Jezyk")).classes("sec pt-3")
        lang = ui.select(i18n.languages(), value=i18n.current()).props("outlined dense").style("width: 220px")
        # Zwiniete i na samym dole: zeby trafic na czyszczenie, trzeba go poszukac, a nie minac
        # przypadkiem przy przewijaniu ustawien.
        with ui.expansion(t("Strefa niebezpieczna")).classes("w-full card").style("margin-top:10px"):
            ui.label(t("Czyszczenie kasuje wszystkie odczytane przedmioty i rejestr wystawionych. "
                       "Tego nie da sie cofnac inaczej niz z kopii.")) \
                .style(f"font-size:12px; color:{MUTED}; white-space:pre-line")
            ui.button(t("Wyczysc wszystkie dane..."), on_click=lambda: (d.close(), wipe_dialog())) \
                .props("unelevated no-caps dense").classes("ghost px-3 mt-2") \
                .style(f"color:{BAD}; border-color:{BAD}")
        msg = ui.label("").style("font-size:12.5px")      # komunikaty modelu i zapisu ustawien
        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            ui.button(t("Anuluj"), on_click=d.close).props("unelevated no-caps dense").classes("ghost px-3")
            ui.button(t("Zapisz"), on_click=save).props("unelevated no-caps dense").classes("primary px-3")
    describe()
    d.on("hide", lambda: d.delete())
    d.open()


def usage_dialog():
    """Nasz licznik tokenow obok tego, co zglasza dostawca (kontrola rozliczen)."""
    data = llm.usage_summary(30)
    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("width: 760px; max-width: 95vw"):
        ui.label(t("Zuzycie tokenow (ostatnie 30 dni)")).style("font-size:15px; font-weight:600")
        if not data:
            ui.label(t("Brak danych - zrob najpierw odczyt screenow.")).style(f"color:{MUTED}")
        else:
            sp = lambda n: f"{n:,}".replace(",", " ")
            rows = [{"model": k, "zapytan": v["zapytan"],
                     "nasze": f'{sp(v["nasze_in"])}+{sp(v["nasze_out"])}',
                     "ich": (f'{sp(v["ich_in"])}+{sp(v["ich_out"])}' if v["ich_in"] else "-"),
                     "roznica": (f'{v["roznica_%"]:+.1f}%' if v["roznica_%"] is not None else "-"),
                     "cache": sp(v["cache"]) if v["cache"] else "-",
                     "rozum": sp(v["rozumowanie"]) if v["rozumowanie"] else "-",
                     "koszt": (f'{v["koszt"]:.4f} {v["waluta"] or ""}'.strip() if v.get("koszt") else "-"),
                     "czas": f'{v["sekundy"] / max(1, v["zapytan"]):.1f} s'} for k, v in data.items()]
            ui.table(columns=[{"name": c, "label": t(l), "field": c, "align": "left"} for c, l in
                              (("model", "Model"), ("zapytan", "Zapytan"), ("nasze", "Nasze (we+wy)"),
                               ("ich", "Dostawca (we+wy)"), ("roznica", "Roznica"), ("cache", "Z cache"),
                               ("rozum", "Rozumowanie"), ("koszt", "Koszt"), ("czas", "Sredni czas"))],
                     rows=rows).props("flat dense").classes("w-full")
            ui.label(t("Nasze liczby to szacunek (tekst ~4 znaki/token, obraz 28x28 px/token dla modeli Qwen-VL). "
                       "Kilkanascie procent roznicy jest normalne; duza i rosnaca roznica warta jest zgloszenia. "
                       "'Rozumowanie' powinno byc zerowe - za nie tez sie placi.")) \
                .style(f"font-size:12px; color:{MUTED}")
        with ui.row().classes("w-full justify-between pt-2"):
            ui.button(t("Otworz plik CSV"), on_click=lambda: os.startfile(llm.USAGE_FILE.resolve())) \
                .props("unelevated no-caps dense").classes("ghost")
            ui.button(t("Zamknij"), on_click=d.close).props("unelevated no-caps dense").classes("ghost")
    d.on("hide", lambda: d.delete())
    d.open()


def crop_dialog(iid):
    it = S.items[iid]
    if it["status"] == "posted":
        ui.notify(t("Ten przedmiot jest juz wystawiony. Jesli oferta jest bledna, usun ja na Traderie i usun pliki "
                    ".json i .listing.json tego screena."), type="warning")
        return
    stem = stem_of(it)
    png = next((p for p in FOLDER.glob(stem + ".*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")), None)
    if not png:
        ui.notify(t(f"Nie znaleziono screena {stem}.png"), type="negative")
        return
    ocr_file = FOLDER / f"{stem}.json"
    box = json.loads(ocr_file.read_text(encoding="utf-8")).get("tooltip_box") if ocr_file.exists() else None
    st = {"start": None, "box": None}

    def rect(b, color, dash=""):
        x1, y1, x2, y2 = b
        return (f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" fill="none" stroke="{color}" '
                f'stroke-width="4" {dash}/>')

    def mouse(e):
        if e.type == "mousedown":
            st["start"] = (e.image_x, e.image_y)
        elif e.type == "mouseup" and st["start"]:
            x1, x2 = sorted((st["start"][0], e.image_x))
            y1, y2 = sorted((st["start"][1], e.image_y))
            if x2 - x1 > 20 and y2 - y1 > 20:
                st["box"] = tuple(int(v) for v in (x1, y1, x2, y2))
                img.content = (rect(box, CROP_BOX, 'stroke-dasharray="10 6"') if box else "") + rect(st["box"], CROP_SEL)
                go.enable()

    async def reread():
        import d2_ocr
        d.close()

        async def job():
            ok = await run.io_bound(d2_ocr.check_gpu)
            if not ok:
                say(t("Model nie miesci sie na karcie graficznej - zamknij gre i sprobuj ponownie."), "negative")
                return
            result = await run.io_bound(d2_ocr.read_tooltip, png, st["box"])
            png.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            res = await run.io_bound(tm.map_item, result)
            (FOLDER / f"{png.stem}.listing.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            log("   " + " | ".join(result["lines"][:4]) + " ...")
            await run.io_bound(d2_ocr.unload_model)
            load_items()
            asyncio.create_task(prefetch_and_hints())
        await task(job)

    with S.host, ui.dialog() as d, ui.card().classes("p-5").style("max-width: 95vw"):
        ui.label(t("Przeciagnij mysza prostokat obejmujacy caly tooltip (z zapasem po bokach). Czerwona ramka = obecny wycinek.")) \
            .style(f"color:{MUTED}")
        img = ui.interactive_image(f"/screenshots/{png.name}", on_mouse=mouse, events=["mousedown", "mouseup"], cross=True,
                                   sanitize=False, content=rect(box, CROP_BOX, 'stroke-dasharray="10 6"') if box else "") \
            .style("max-width: 1100px; max-height: 75vh")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Anuluj"), on_click=d.close).props("unelevated no-caps dense").classes("ghost")
            go = ui.button(t("Odczytaj ponownie"), on_click=reread).props("unelevated no-caps dense").classes("primary")
            go.disable()
    d.on("hide", lambda: d.delete())
    d.open()


# ---------------- widoki ----------------
def auto_sync():
    """Wejscie w 'Wystawione' odswieza stan ofert na Traderie (sprzedane, do odnowienia).

    Nie czesciej niz co SYNC_GAP: przelaczanie widokow tam i z powrotem nie ma zasypywac serwera.
    Czas zapisujemy przed pobraniem, zeby przy zerwanym polaczeniu nie probowac za kazdym klikiem.
    """
    if S.busy or time.monotonic() - S.last_sync < SYNC_GAP:
        return
    asyncio.create_task(background_sync())


def switch_view(view):
    """Przelaczenie widoku z paska bocznego."""
    S.view, S.page = view, 1
    if view in ("items", "listed") and (S.selected not in S.items or not visible(S.items[S.selected], S.selected)):
        S.selected = next((i for i in S.order if visible(S.items[i], i)), None)
    if view == "listed":
        auto_sync()
    S.dirty = True


def nav_button(label, view, count=None, icon=""):
    on = S.view == view
    with ui.button(on_click=lambda: switch_view(view)).props("flat no-caps align=left") \
            .classes("navbtn w-full" + (" on" if on else "")):
        ui.icon(icon).classes("mr-2").style("font-size:16px; opacity:.8")
        ui.label(t(label)).classes("flex-grow text-left").style("font-size:13px")
        if count:
            ui.label(str(count)).classes("mono").style(f"font-size:11px; color:{INK if on else FAINT}")


def sidebar():
    c = counts()
    # sticky + wlasne przewijanie: na pelnym ekranie pasek siega dolu okna, a przy niskim oknie
    # ostatni wiersz (przelacznik powiadomien) da sie doscrollowac zamiast zostac przycietym
    with ui.column().classes("gap-0.5 p-3").style(f"width:216px; flex-shrink:0; background:{PANEL}; "
                                                  f"border-right:1px solid {LINE}; align-self:stretch; "
                                                  "position:sticky; top:0; min-height:100vh; max-height:100vh; "
                                                  "overflow-y:auto; overflow-x:hidden"):
        with ui.row().classes("items-center gap-2 pb-4 px-2 no-wrap"):
            with ui.element("div").style(f"width:26px; height:26px; border-radius:3px; background:{PANEL2}; "
                                         f"border:1px solid {LINE2}; display:flex; align-items:center; justify-content:center"):
                ui.icon("shield").style(f"color:{MUTED}; font-size:15px")
            with ui.column().classes("gap-0"):
                ui.label("D2 Trade").style("font-size:14px; font-weight:600")
                ui.label("Traderie · d2jsp").style(f"font-size:11px; color:{FAINT}")
        todo = sum(c.get(k, 0) for k in ("ready", "review", "dup"))
        nav_button("Przedmioty", "items", todo, "grid_view")
        nav_button("Szybka wycena", "quick", None, "search")
        nav_button("Wystawione", "listed", c.get("posted", 0) + c.get("relist", 0), "format_list_bulleted")
        nav_button("Post d2jsp", "d2jsp", None, "forum")
        with ui.button(on_click=settings_dialog).props("flat no-caps align=left").classes("navbtn w-full"):
            ui.icon("settings").classes("mr-2").style("font-size:16px; opacity:.8")
            ui.label(t("Ustawienia")).classes("flex-grow text-left").style("font-size:13px")
        ui.element("div").classes("flex-grow")
        tok = tm.load_auth().get("Authorization", "")
        ti = app_config.token_info(tok) if tok else {}
        if ti.get("expires"):
            days = (ti["expires"] - datetime.now()).days
            tok_txt, tok_ok = (f"token ważny {days} dni" if days >= 0 else "token wygasł"), days >= 2
        else:
            tok_txt, tok_ok = ("brak tokenu" if not tok else "token zapisany"), bool(tok)
        with ui.column().classes("w-full gap-2 pt-3 px-2").style(f"border-top:1px solid {LINE}; flex-shrink:0"):
            status_card("Traderie", t(tok_txt), OK if tok_ok else ACT)
            # Bez tokenu przedmioty musza sie brac z plikow gry - jak nie ma ani jednego,
            # ani drugiego, program nie rozpozna niczego. Mowimy o tym tam, gdzie widac stan.
            if not tok:
                if game_source.dostepne():
                    status_card(t("Dane z gry"), t("wlaczone"), OK)
                else:
                    status_card(t("Dane z gry"), t("wskaz katalog gry w Ustawieniach"), ACT)
            relist = c.get("relist", 0)
            if relist:
                status_card(t("Do odnowienia"), f"{relist}", ACT)
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.switch(value=S.notify_on, on_change=lambda e: (set_notify(e.value))) \
                    .props("dense color=green size=xs")
                ui.label(t(f"Sprawdzaj wiadomosci w Traderie co {NOTIFY_EVERY // 60} min")) \
                    .style(f"font-size:12px; color:{MUTED}")


def set_notify(value: bool):
    """Przelacznik sprawdzania wiadomosci i sprzedanych - wybor zostaje na nastepne uruchomienie."""
    S.notify_on = bool(value)
    i18n.save_setting("notify", S.notify_on)
    if S.notify_on:
        asyncio.create_task(notify_tick())


def status_card(title, sub, dot):
    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        ui.element("span").classes("dot").style(f"background:{dot}")
        ui.label(f"{title} — {sub}").style(f"font-size:12px; color:{MUTED}")


def header(title):
    c = counts()
    with ui.row().classes("w-full items-center gap-2"):
        ui.label(t(title)).style("font-size:21px; font-weight:600; letter-spacing:-0.01em").classes("flex-grow")
        qi = ui.input(placeholder=t("Szukaj lub wyceń: shako def 140")).props("outlined dense") \
            .style("width: 240px").on("keydown.enter", lambda: run_quick(qi.value))
        editable(qi)
        mail_button()
        with ui.button(on_click=toggle_capture).props("unelevated no-caps dense").classes("ghost px-3"):
            ui.switch(value=S.capture_on).props("dense color=green").style("pointer-events:none")
            ui.label(t("Zrzuty F12")).classes("pl-2")
        ui.button(t("Odczytaj screeny"), on_click=lambda: task(do_read, False)).props("unelevated no-caps dense") \
            .classes("ghost px-3").bind_enabled_from(S, "busy", backward=lambda b: not b)
        n = sum(1 for it in S.items.values() if it["selected"] and it["status"] in ("ready", "dup"))
        if S.busy and S.progress:
            ui.button(t("Stop"), on_click=lambda: setattr(S, "stop", True)).props("unelevated no-caps dense") \
                .classes("ghost px-3").style(f"color:{BAD}; border-color:{BAD}")
        else:
            ui.button(t(f"Wystaw zaznaczone ({n})"), on_click=start_post).props("unelevated no-caps dense") \
                .classes("primary px-3").bind_enabled_from(S, "busy", backward=lambda b: not b)
    # licznik stanow: jeden pasek, kolor tylko tam, gdzie cos wymaga reakcji
    with ui.row().classes("card items-stretch no-wrap gap-0").style("align-self:flex-start"):
        for i, (key, label, col) in enumerate((("ready", "Gotowe", INK), ("review", "Do sprawdzenia", WARN),
                                               ("posted", "Wystawione", INK), ("relist", "Do odnowienia", ACT),
                                               ("sold", "Sprzedane", FAINT))):
            with ui.row().classes("items-baseline gap-2 px-4 py-1 no-wrap") \
                    .style(f"border-left:1px solid {LINE}" if i else ""):
                ui.label(str(c.get(key, 0))).classes("mono").style(f"font-size:17px; color:{col}")
                ui.label(t(label)).style(f"font-size:12px; color:{MUTED}")


_FG = {"when": 0.0, "table": {}, "on": True}   # ustawienia i kursy odswiezane co pare sekund, nie przy kazdej karcie


def fg_in_app() -> bool:
    """Czy pokazywac przelicznik FG przy cenach w oknie (post d2jsp ma wlasny przelacznik)."""
    return bool(i18n.settings().get("fg_in_app", True))


def fg_text(price: str) -> str:
    """'ist+mal' -> '~90 fg' albo pusto. Dopisek przy cenie w runach; wymaga wpisanego kursu
    i wlaczonego podgladu FG w oknie. Liczy to samo, co cena w poscie d2jsp."""
    if not price or price == "offer":
        return ""
    now = time.monotonic()
    if now - _FG["when"] > 5:
        _FG.update(when=now, on=fg_in_app(), table=d2jsp_post.fg_table())
    if not _FG["on"]:
        return ""
    v = d2jsp_post.price_fg(price, _FG["table"])
    return f"~{v:g} fg" if v else ""


def mail_button():
    """Kopertka z liczba nieprzeczytanych wiadomosci z Traderie; klikniecie otwiera ich liste."""
    with ui.button(on_click=messages_dialog).props("unelevated no-caps dense").classes("ghost px-3") \
            .tooltip(t("Wiadomosci z Traderie")):
        ui.icon("mail").style(f"font-size:16px; color:{ACT if S.notify_new else MUTED}")
        if S.notify_new:
            ui.label(str(S.notify_new)).classes("mono pl-2").style(f"font-size:12px; color:{ACT}")


def toggle_capture(e=None):
    try:
        import keyboard
        import d2_capture
    except Exception as ex:
        ui.notify(f"keyboard / d2_capture: {ex}", type="negative")
        return
    if S.capture_on:
        keyboard.remove_hotkey(S._hotkey)
        S.capture_on = False
    else:
        S._hotkey = keyboard.add_hotkey(d2_capture.HOTKEY, d2_capture.capture)
        S.capture_on = True
        log(t(f"Zrzuty wlaczone - w grze najedz na przedmiot i wcisnij {d2_capture.HOTKEY.upper()}."))
    S.dirty = True


def item_card(iid):
    it = S.items[iid]
    lst = it["lst"]
    name = lst.get("name") or lst.get("ocr_name", "?")
    item = S.defs.get(lst.get("name"))
    st_key = eff_status(it)
    label, dot = STATUS.get(st_key, (st_key, FAINT))
    sst = state_of(it)
    if sst and sst["hidden"]:
        label += t(" (ukryty)")
    if sst and sst["offers"]:
        label += t(" | oferty: ") + str(sst["offers"])
    can = it["status"] in ("ready", "dup")
    # w widoku wystawionych zaznaczamy to, co da sie odnowic - checkbox jest tylko przy takich ofertach
    can_check = can or (S.view == "listed" and st_key == "relist")
    faded = "opacity:.6" if it["status"] in ("sold", "skipped") else ""
    with ui.row().classes("d2row w-full items-center gap-3 pr-3 py-2 no-wrap" + (" sel" if S.selected == iid else "")) \
            .on("click", lambda: select(iid)):
        # pasek rzadkosci - kolor jak w grze, zeby rodzaj przedmiotu czytalo sie bez etykiety
        ui.element("div").classes("rar").style(f"background:{RAR.get(lst.get('kind'), RAR['baza'])}")
        with ui.element("div").style("width:22px"):
            if can_check:
                ui.checkbox(value=bool(it["selected"])).props("dense size=xs") \
                    .on("click.stop", lambda: toggle_check(iid))
        with ui.element("div").classes("thumb").style(f"width:38px; height:38px; flex-shrink:0; {faded}"):
            src = f"/screenshots/_crops/{stem_of(it)}.png" if not img_url(lst.get("name")) else img_url(lst.get("name"))
            if img_url(lst.get("name")):
                ui.image(src).style("width:32px; height:32px").props("fit=contain no-spinner")
            else:
                ui.icon("inventory_2").style(f"color:{FAINT}; font-size:20px")
        with ui.column().classes("gap-1 flex-grow").style(f"min-width:0; {faded}"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                shown = f"{lst['rare_name']} · {name}" if lst.get("rare_name") else name
                ui.label(shown + (t("  [z Traderie]") if lst.get("imported") else "")).style("font-size:13.5px; font-weight:500")
                kind = KIND.get(lst.get("kind"))
                if kind:
                    ui.label(kind[0]).classes("tag").style(f"color:{kind[1]}")
                gdzie = where_label(lst)
                if gdzie:
                    ui.label(gdzie).classes("pill")
            with ui.row().classes("gap-1"):
                if it["status"] in ("skipped", "review"):
                    msg = lst.get("skipped") or "; ".join(lst.get("warnings") or ["odczyt niepewny - sprawdz screen"])
                    ui.label(t(msg)).style(f"font-size:11.5px; color:{FAINT}; max-width:520px; "
                                           "white-space:nowrap; overflow:hidden; text-overflow:ellipsis")
                else:
                    stats, flags = d2jsp_post.short_stats(lst, item)
                    for s in (stats + flags)[:5]:
                        ui.label(s).classes("pill mono")
        hint = (it["hint"] or {}).get("price", "")
        price = it["price"] or (f"~ {hint}" if hint and can else ("…" if can and it["hint"] is None else "—"))
        fg = fg_text(it["price"] or hint)
        ui.button(price + (f" ({fg})" if fg else "")).props("unelevated no-caps dense") \
            .classes("price mono").style(f"min-width:92px; font-size:12.5px; white-space:nowrap; {faded}") \
            .on("click.stop", lambda: price_dialog(iid) if can else select(iid))
        with ui.row().classes("items-center gap-2 no-wrap").style(f"width:132px; flex-shrink:0; {faded}"):
            ui.element("span").classes("dot").style(f"background:{dot}")
            ui.label(t(label)).classes("badge" + (" strong" if st_key in ("ready", "relist", "error") else ""))


def select(iid):
    S.selected = iid
    S.dirty = True


def details():
    iid = S.selected
    with ui.column().classes("card gap-4 p-5").style("width: 384px; flex-shrink:0"):
        if not iid or iid not in S.items:
            ui.label(t("Wybierz przedmiot z listy.")).style(f"color:{MUTED}")
            progress_box()
            return
        it = S.items[iid]
        lst = it["lst"]
        item = S.defs.get(lst.get("name"))
        with ui.row().classes("items-center gap-3 no-wrap"):
            with ui.element("div").classes("thumb").style("width:64px; height:64px; flex-shrink:0"):
                if img_url(lst.get("name")):
                    ui.image(img_url(lst.get("name"))).style("width:54px; height:54px").props("fit=contain no-spinner")
            with ui.column().classes("gap-1").style("min-width:0"):
                ui.label(lst.get("name") or lst.get("ocr_name", "?")).style("font-size:16px; font-weight:600")
                if lst.get("rare_name"):
                    ui.label(lst["rare_name"]).style(f"font-size:12px; color:{FAINT}")
                with ui.row().classes("gap-1"):
                    kind = KIND.get(lst.get("kind"))
                    if kind:
                        ui.label(kind[0]).classes("tag").style(f"color:{kind[1]}")
                    for tg in tags_of(item, 4):
                        ui.label(tg).classes("pill")
        # komunikaty
        notes = []
        if it["status"] == "posted":
            p = lst["posted"]
            notes.append(t(f"Wystawiony {p.get('time')} za {p.get('price')}."))
            sst = state_of(it)
            if sst:
                notes.append(t("Gotowy do ODNOWIENIA - kliknij ponizej Odnow oferte.") if sst["relist"]
                             else t(f"Odnowienie mozliwe za ok. {sst['hours_left']:.0f} h."))
                if sst["offers"]:
                    notes.append(t(f"Oferty kupna: {sst['offers']} - sprawdz na Traderie."))
        if it["dup"]:
            d = it["dup"]
            notes += [t(f"Podobny przedmiot wystawiono {d.get('time')} za {d.get('price')}."),
                      t(f"Wtedy: {', '.join(d.get('stats') or []) or '-'}")]
        for w in lst.get("warnings") or []:
            notes.append("! " + t(w))
        if lst.get("skipped"):
            notes.append(t(lst["skipped"]))
        # linie odczytu, dla ktorych Traderie nie ma takiego statu - oferta bedzie bez nich.
        # Bierzemy tylko linie z liczba: bez liczby to zwykle nazwy innych czesci setu z tooltipa.
        zgubione = [u for u in lst.get("unmatched") or [] if any(c.isdigit() for c in u)]
        if zgubione:
            # to tylko informacja - reszta statow idzie do oferty, przedmiot da sie wystawic
            notes.append(t(f"Traderie nie ma takiego statu: {', '.join(zgubione)} - "
                           "oferta pojdzie bez niego, reszta statow bez zmian."))
        for n in notes:
            ui.label(n).style(f"font-size:12.5px; color:{MUTED}")
        # rzut
        if item and lst.get("listing") and lst.get("rarity"):
            rolls, head = rare_eval.rolls(lst, item), t("Staty na tle maksimum dla tego slotu")
        elif item and lst.get("listing"):
            rolls, head = tpr.rolls(lst, item), t("Statystyki")
        else:
            rolls, head = [], ""
        if rolls:
            ma_rzadkosc = bool(lst.get("rarity"))
            with ui.column().classes("w-full gap-2"):
                ui.label(head).classes("sec")
                for _, stat, v, lo, hi, pct in rolls:
                    kolor, kolor_slowa = kolor_rzutu(pct)
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.label(stat).style(f"width:150px; font-size:12px; color:{MUTED}")
                        with ui.element("div").classes("bar flex-grow"):
                            ui.element("div").style(f"width:{max(4, round(pct * 100))}%; background:{kolor}")
                        if ma_rzadkosc:
                            # wartosc i maksimum razem: "18 / 20" czyta sie od razu jako ulamek
                            with ui.row().classes("items-baseline gap-0 no-wrap mono") \
                                    .style("width:76px; justify-content:flex-end; font-size:12px"):
                                ui.label(str(v))
                                ui.label(f" / {hi}").style(f"color:{FAINT}")
                        else:
                            # przy unikatach dolna granica zakresu tez niesie tresc, wiec zostaje
                            ui.label(str(v)).classes("mono").style("width:36px; text-align:right; font-size:12px")
                            ui.label(f"[{lo}-{hi}]").classes("mono") \
                                .style(f"width:62px; text-align:right; font-size:11px; color:{FAINT}")
                        opis = rare_eval.quality_label(pct)
                        ui.label(t(opis) if opis else "").style(
                            f"width:98px; font-size:11px; color:{kolor_slowa}")
        can = it["status"] in ("ready", "dup")
        hint = it["hint"] or {}
        levels = hint.get("levels") or {}
        if levels:
            first = (hint.get("text") or "").strip().splitlines()
            sub = next((l.strip() for l in first if l.strip().startswith(("transakcje", "brak transakcji"))), "")
            ui.label(t("Cena z ostatnich transakcji")).classes("sec")
            if sub:
                ui.label(t(sub)).style(f"font-size:12px; color:{FAINT}")
            with ui.grid(columns=4).classes("w-full gap-2"):
                for key, label in LEVELS:
                    v = levels.get(key)
                    if not v:
                        continue
                    on = it["price"] == v
                    with ui.button(on_click=lambda v=v: set_price(iid, v)).props("flat no-caps").classes("lvl" + (" on" if on else "")) \
                            .mark(f"lvl-{key}") \
                            .bind_enabled_from(S, "busy", backward=lambda b, c=can: c and not b):
                        with ui.column().classes("items-center gap-0"):
                            ui.label(t(label)).style(f"font-size:11px; color:{FAINT}")
                            ui.label(v).classes("mono").style(f"font-size:13px; color:{INK}")
                            fg = fg_text(v)
                            if fg:
                                ui.label(f"({fg})").classes("mono").style(f"font-size:10.5px; color:{INK}")
        elif can and it["hint"] is None:
            ui.label(t("wycena w toku...")).style(f"color:{FAINT}")
        if can:
            with ui.row().classes("w-full gap-2 no-wrap"):
                pin = editable(ui.input(placeholder=t("własna cena"), value=it["price"]).props("outlined dense").classes("flex-grow mono"))
                pin.on("keydown.enter", lambda: (setattr(S, "editing", False), set_price(iid, pin.value))[1])
                pin.on("blur", lambda: set_price(iid, pin.value) if (pin.value or "").strip().lower() != it["price"] else None)
                ui.button(t("Wybierz cenę…"), on_click=lambda: price_dialog(iid)).props("unelevated no-caps dense").classes("ghost px-3")
            if it["last"]:
                ui.label(t(f"Ostatnio wystawiales ten przedmiot za: {it['last']}")).style(f"font-size:12px; color:{FAINT}")
        ui.label(t("Gdzie lezy")).classes("sec")
        with ui.row().classes("w-full gap-2 no-wrap"):
            w = lst.get("where") or {}
            cin = editable(ui.input(placeholder=t("nazwa postaci"), value=w.get("char", ""))
                           .props("outlined dense").classes("flex-grow"))
            cin.on("keydown.enter", lambda: (setattr(S, "editing", False), set_where(iid, char=cin.value))[1])
            cin.on("blur", lambda: set_where(iid, char=cin.value)
                   if (cin.value or "").strip() != w.get("char", "") else None)
            ui.select([""] + [t(x) for x in STASH], value=t(w.get("stash", "")) if w.get("stash") else "",
                      on_change=lambda e: set_where(iid, stash=next((x for x in STASH if t(x) == e.value), ""))) \
                .props("outlined dense options-dense").style("min-width:160px")
        with ui.row().classes("gap-2"):
            if it["status"] == "review":
                # ostrzezenie bez wyjscia bylo pulapka: po obejrzeniu przedmiotu trzeba moc powiedziec
                # "sprawdzilem, wystawiam" - inaczej zostaje tylko usuniecie z listy
                ui.button(t("Sprawdzone - mozna wystawic"), on_click=lambda: mark_reviewed(iid)) \
                    .props("unelevated no-caps dense").classes("ghost px-3").style(f"color:{OK}; border-color:{OK}")
            if it["status"] in ("posted", "ready", "dup", "sold"):
                ui.button(t("Cofnij: nie sprzedany") if lst.get("sold") else t("Oznacz jako sprzedany"),
                          on_click=lambda: toggle_sold(iid)).props("unelevated no-caps dense").classes("ghost px-3")
            if it["status"] == "posted":
                sst = state_of(it)
                if sst and sst["relist"]:
                    ui.button(t("Odnow oferte"), on_click=lambda: task(relist_one, iid)) \
                        .props("unelevated no-caps dense").classes("ghost px-3").style(f"color:{ACT}; border-color:{ACT}") \
                        .bind_enabled_from(S, "busy", backward=lambda b: not b)
                ui.button(t("Pokaz na Traderie") if sst and sst["hidden"] else t("Ukryj na Traderie"),
                          on_click=lambda: toggle_hidden(iid)).props("unelevated no-caps dense").classes("ghost px-3")
                ui.button(t("Usun oferte z Traderie"), on_click=lambda: remove_listing(iid)).props("unelevated no-caps dense") \
                    .classes("ghost px-3").style(f"color:{BAD}")
            if it["status"] not in ("posted",) and not lst.get("imported"):
                ui.button(t("Zly odczyt? Popraw wycinek"), on_click=lambda: crop_dialog(iid)) \
                    .props("unelevated no-caps dense").classes("ghost px-3")
            ui.button(t("Usun z listy"), on_click=lambda: delete_item(iid)).props("unelevated no-caps dense") \
                .classes("ghost px-3").style(f"color:{BAD}")
        crop = FOLDER / "_crops" / f"{stem_of(it)}.png"
        if crop.exists():
            with ui.expansion(t("Odczytany tooltip")).classes("w-full").style(f"border:1px solid {LINE}; border-radius:3px"):
                ui.image(f"/screenshots/_crops/{crop.name}?v={int(crop.stat().st_mtime)}").classes("w-full")
        progress_box()


def progress_box():
    if S.progress:
        text, frac = S.progress
        with ui.column().classes("w-full gap-2 p-3").style(f"border:1px solid {LINE}; border-radius:3px; background:{PANEL2}"):
            ui.label(text).style("font-size:12.5px")
            with ui.element("div").classes("bar w-full"):
                ui.element("div").style(f"width:{round(frac * 100)}%; background:{OK}")


def set_page(n):
    S.page = max(1, int(n))
    S.dirty = True


def set_page_size(n):
    """Ile pozycji na stronie. Wybor zostaje na nastepne uruchomienie (settings.json)."""
    S.page_size, S.page = int(n), 1
    i18n.save_setting("page_size", int(n))
    S.dirty = True


def page_numbers(cur, pages):
    """Numery stron do pokazania: pierwsza, ostatnia i okolice biezacej; 0 = przerwa '...'."""
    keep = {1, pages, cur - 1, cur, cur + 1}
    out = []
    for n in range(1, pages + 1):
        if n in keep:
            out.append(n)
        elif out and out[-1]:
            out.append(0)
    return out


def pager(total, pages):
    """Pasek pod lista: ile na stronie, numery stron, ktore pozycje widac."""
    with ui.row().classes("w-full items-center gap-2 pt-1"):
        ui.label(t("Pokaz po:")).classes("sec")
        for n in PAGE_SIZES:
            ui.button(str(n), on_click=lambda n=n: set_page_size(n)).props("unelevated no-caps dense") \
                .classes(("lvl on" if n == S.page_size else "ghost") + " px-3 mono")
        ui.element("div").classes("flex-grow")
        if pages > 1:
            ui.button("‹", on_click=lambda: set_page(S.page - 1)).props("unelevated no-caps dense") \
                .classes("ghost px-3").set_enabled(S.page > 1)
            for n in page_numbers(S.page, pages):
                if not n:
                    ui.label("…").style(f"color:{FAINT}")
                else:
                    ui.button(str(n), on_click=lambda n=n: set_page(n)).props("unelevated no-caps dense") \
                        .classes(("lvl on" if n == S.page else "ghost") + " px-3 mono")
            ui.button("›", on_click=lambda: set_page(S.page + 1)).props("unelevated no-caps dense") \
                .classes("ghost px-3").set_enabled(S.page < pages)
        first = (S.page - 1) * S.page_size + 1
        # slowo "Pozycje" nie jest ozdoba: tekst jest kluczem tlumaczenia, a klucz z samych wstawek
        # ("{0}-{1} z {2}") pasowalby do kazdego zdania z myslnikiem i slowem "z"
        ui.label(t(f"Pozycje {first}-{min(total, S.page * S.page_size)} z {total}")).classes("sec mono")


def items_view(title):
    header(title)
    with ui.row().classes("w-full items-center gap-2 pt-1"):
        if S.view == "items":
            ui.button(t("Uzyj podpowiedzi dla wszystkich bez ceny"), on_click=fill_hints).props("unelevated no-caps dense") \
                .classes("ghost px-3")
            ui.button(t("Odczytaj wszystkie od nowa"), on_click=lambda: task(do_read, True)).props("unelevated no-caps dense") \
                .classes("ghost px-3")
            ui.checkbox(t("pokaz tez pominiete i dawniej sprzedane"), value=S.show_all,
                        on_change=lambda e: (setattr(S, "show_all", e.value), setattr(S, "page", 1),
                                             setattr(S, "dirty", True))).props("dense size=xs")
        else:
            ui.button(t("Sprawdz oferty (sprzedane, do odnowienia)"), on_click=lambda: task(do_sync)) \
                .props("unelevated no-caps dense").classes("ghost px-3")
            gotowe = relist_ready()
            if gotowe:
                plan = relist_plan()
                zaznaczone = len(plan) < len(gotowe) or all(S.items[i]["selected"] for i, _ in gotowe)
                ui.button(t(f"Odnow zaznaczone ({len(plan)})") if zaznaczone
                          else t(f"Odnow wszystkie ({len(plan)})"), on_click=lambda: task(do_relist_all)) \
                    .props("unelevated no-caps dense").classes("ghost px-3").style(f"color:{ACT}; border-color:{ACT}") \
                    .bind_enabled_from(S, "busy", backward=lambda b: not b)
                wszystkie = all(S.items[i]["selected"] for i, _ in gotowe)
                ui.button(t("Odznacz") if wszystkie else t(f"Zaznacz gotowe ({len(gotowe)})"),
                          on_click=lambda v=not wszystkie: check_relist(v)) \
                    .props("unelevated no-caps dense").classes("ghost px-3")
        ui.button(t("Co wyjac (sprzedane)"), on_click=pickup_dialog) \
            .props("unelevated no-caps dense").classes("ghost px-3")
        kto = chars_known()
        if kto:
            ui.select([""] + kto, value=S.filter_char, label=t("Postac:"),
                      on_change=lambda e: (setattr(S, "filter_char", e.value or ""), setattr(S, "page", 1),
                                           setattr(S, "dirty", True))) \
                .props("outlined dense options-dense").style("min-width:150px")
    with ui.row().classes("w-full gap-4 items-start no-wrap pt-1"):
        with ui.column().classes("gap-2 flex-grow").style("min-width:0"):
            shown = [i for i in S.order if visible(S.items[i], i)]
            total = len(shown)
            pages = max(1, -(-total // S.page_size))
            S.page = min(max(1, S.page), pages)
            if not shown:
                with ui.column().classes("card w-full items-center p-10 gap-2"):
                    ui.icon("inbox").style(f"font-size:34px; color:{FAINT}")
                    ui.label(t("Brak przedmiotow. Zrob zrzuty w grze (F12) i kliknij 'Odczytaj screeny'.") if S.view == "items"
                             else t("Brak wystawionych ofert. Kliknij 'Sprawdz oferty', zeby pobrac je z Traderie.")) \
                        .style(f"color:{MUTED}")
            else:
                with ui.column().classes("d2list w-full gap-0"):
                    for iid in shown[(S.page - 1) * S.page_size:S.page * S.page_size]:
                        item_card(iid)
            if total > min(PAGE_SIZES):
                pager(total, pages)
        details()


def editable(inp):
    """Pole tekstowe: w trakcie pisania widok sie nie przebudowuje (nie gubi wpisywanego tekstu)."""
    inp.on("focus", lambda: setattr(S, "editing", True))
    inp.on("blur", lambda: setattr(S, "editing", False))
    return inp


def run_quick(q):
    S.editing = False
    q = (q or "").strip()
    if not q:
        return
    S.view = "quick"
    S.quick = {"q": q, "res": None}
    S.dirty = True

    async def job():
        res = await run.io_bound(quick_price.quick_price, q)
        if res.get("item"):
            S.imgs[res["item"]["name"]] = await run.io_bound(item_image, res["item"])
        if S.quick and S.quick["q"] == q:
            S.quick["res"] = res
            S.dirty = True
    asyncio.create_task(job())


def quick_view():
    with ui.row().classes("w-full items-center gap-3"):
        ui.label(t("Szybka wycena")).style("font-size:21px; font-weight:600; letter-spacing:-0.01em").classes("flex-grow")
        mail_button()
    with ui.row().classes("w-full gap-2 no-wrap items-center"):
        qi = ui.input(placeholder="shako def 140  ·  spirit fcr 35  ·  eschuta", value=(S.quick or {}).get("q", "")) \
            .props("outlined dense").classes("flex-grow").on("keydown.enter", lambda: run_quick(qi.value))
        editable(qi)
        ui.button(t("Sprawdz"), on_click=lambda: run_quick(qi.value)).props("unelevated no-caps dense").classes("primary px-4")
    if not S.quick:
        ui.label(t("Wpisz nazwe i opcjonalnie staty, np.:") + "  shako def 136 · spirit fcr 35 mana 110 · arach ed 120") \
            .style(f"color:{MUTED}")
        return
    res = S.quick["res"]
    if res is None:
        with ui.row().classes("items-center gap-3"):
            ui.spinner(size="sm")
            ui.label(t(f"Szybka wycena: {S.quick['q']} ...")).style(f"color:{MUTED}")
        return
    item = res.get("item") or {}
    with ui.row().classes("w-full gap-4 items-start no-wrap"):
        with ui.column().classes("card p-5 gap-3").style("width: 420px; flex-shrink:0"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                with ui.element("div").classes("thumb").style("width:76px; height:94px"):
                    if img_url(item.get("name")):
                        ui.image(img_url(item.get("name"))).style("width:66px; height:84px").props("fit=contain no-spinner")
                with ui.column().classes("gap-2"):
                    ui.label(res["title"]).style("font-size:17px; font-weight:600")
                    with ui.row().classes("gap-1"):
                        for tg in tags_of(item, 5):
                            ui.label(tg).classes("pill")
            if item.get("description"):
                ui.html(bbcode_html(item["description"]), sanitize=False).classes("desc") \
                    .style(f"font-size:13px; line-height:1.6; color:{MUTED}")
        with ui.column().classes("flex-grow gap-3").style("min-width:0"):
            with ui.column().classes("card p-5 gap-3 w-full"):
                ui.label(t("Cena z ostatnich transakcji")).classes("sec")
                with ui.grid(columns=4).classes("w-full gap-2"):
                    for key, label in LEVELS:
                        v = (res.get("levels") or {}).get(key)
                        if v:
                            with ui.column().classes("lvl items-center gap-0 py-2" + (" on" if key == "typical" else "")):
                                ui.label(t(label)).style(f"font-size:11px; color:{FAINT}")
                                ui.label(v).classes("mono").style(f"font-size:14px; color:{INK}")
                                fg = fg_text(v)
                                if fg:
                                    ui.label(f"({fg})").classes("mono").style(f"font-size:11px; color:{INK}")
                for line in res["text"].splitlines():
                    if line.strip() and not line.startswith("Zmienne staty") and not line.startswith("  "):
                        ui.label(t(line.strip())).style(f"font-size:12.5px; color:{MUTED}")
            if res.get("others"):
                with ui.column().classes("card p-5 gap-2 w-full"):
                    ui.label(t("Inne pasujace")).classes("sec")
                    with ui.row().classes("gap-2"):
                        for n in res["others"]:
                            ui.button(n, on_click=lambda n=n: run_quick(n)).props("unelevated no-caps dense").classes("ghost px-3")


def d2jsp_view():
    entries = [(it["lst"], it["price"]) for it in (S.items[i] for i in S.order)
               if it["status"] in ("posted", "ready", "dup") and it["price"] and not it["lst"].get("sold")]
    text = d2jsp_post.build_post(entries) if entries else ""
    with ui.row().classes("w-full items-center gap-2"):
        ui.label(t("Post d2jsp")).style("font-size:21px; font-weight:600; letter-spacing:-0.01em").classes("flex-grow")
        mail_button()
        ui.button(t("Otworz moje watki"), on_click=open_threads).props("unelevated no-caps dense").classes("ghost px-3")
        ui.button(t("Kopiuj post sprzedazowy"), on_click=lambda: (ui.clipboard.write(text),
                                                                  ui.notify(t(f"Post z {len(entries)} przedmiotami jest w schowku."),
                                                                            type="positive"))) \
            .props("unelevated no-caps dense").classes("primary px-3")
    ui.label(t("Wklej go w nowym watku albo edytuj nim pierwszy post istniejacego.")).style(f"color:{MUTED}")
    with ui.column().classes("card p-5 w-full"):
        if text:
            ui.textarea(value=text).props("readonly autogrow borderless").classes("w-full mono") \
                .style("font-size: 12.5px")
        else:
            ui.label(t("Brak przedmiotow z cena (wystawionych albo gotowych).")).style(f"color:{MUTED}")
    with ui.column().classes("card p-5 w-full gap-2"):
        ui.label(t("Watki d2jsp")).classes("sec")
        links = editable(ui.input(t("Linki do Twoich watkow sprzedazowych (oddziel przecinkami):"),
                         value=", ".join(d2jsp_post.threads())).props("outlined dense").classes("w-full"))
        ui.button(t("Zapisz"), on_click=lambda: (d2jsp_post.save_threads(
            [u.strip() for u in (links.value or "").split(",") if u.strip().startswith("http")]),
            ui.notify(t("Zapisano ustawienia."), type="positive"))).props("unelevated no-caps dense").classes("ghost px-3 self-start")


def open_threads():
    urls = d2jsp_post.threads()
    if not urls:
        ui.notify(t("Najpierw zapisz linki do watkow ponizej."), type="warning")
    for u in urls:
        webbrowser.open(u)


# ---------------- strona ----------------
REQUIRED = {
    "i18n": (i18n, ["PROBLEMS", "languages", "tr", "save_setting"]),
    "traderie_map": (tm, ["SessionExpired", "range_parts", "load_auth", "get_item", "map_item", "run"]),
    "traderie_price": (tpr, ["suggest", "rolls", "stat_name", "short", "HIGH_ROLL"]),
    "traderie_post": (tp, ["search_items", "parse_price", "set_visible", "remove_listing", "mark_sold", "describe",
                           "fingerprint", "unregister", "is_expired", "SESSION_EXPIRED"]),
    "traderie_sync": (traderie_sync, ["sync", "TRASH"]),
    "d2jsp_post": (d2jsp_post, ["build_post", "short_stats", "threads", "save_threads"]),
    "quick_price": (quick_price, ["quick_price"]),
    "app_config": (app_config, ["apply", "save", "token_info", "OPTIONS", "current"]),
}
STALE = sorted(f"{n}.py" for n, (m, attrs) in REQUIRED.items() if any(not hasattr(m, a) for a in attrs))

app.add_static_files("/cache/img", str(IMG_DIR))
app.add_static_files("/screenshots", str(FOLDER))


load_items()                      # lista przedmiotow od razu przy starcie
_started = {"done": False}


def first_visit():
    """Przy pierwszym otwarciu okna: komunikaty o plikach jezykowych i wyceny w tle."""
    if _started["done"]:
        return
    _started["done"] = True
    for p in dict.fromkeys(i18n.PROBLEMS):
        log(f"(plik jezykowy pominiety - {p})")
    asyncio.create_task(prefetch_and_hints())



@ui.page("/")
def index():
    wybrany = motyw()
    S.dark = ui.dark_mode(wybrany == "dark")
    ui.add_head_html(HEAD)
    # Wybrana paleta trafia takze na goly :root, zeby okno wstalo juz w swoich kolorach (bez
    # mrugniecia). Blok :root[data-theme=...] z HEAD ma wyzsza specyficznosc, wiec przelacznik
    # wygrywa z ta wartoscia poczatkowa.
    ui.add_head_html("<style>:root { " + " ".join(f"--{k}:{v};" for k, v in PALETY[wybrany].items())
                     + " }</style>")
    if STALE:
        with ui.column().classes("p-10 gap-3"):
            ui.label(t("Stare wersje plikow: ") + ", ".join(STALE)).style(f"font-size:15px; font-weight:600; color:{BAD}")
            ui.label(t("Podmien je na najnowsze (sprawdz, czy przegladarka nie zapisala ich jako 'nazwa (1).py').."))
        return
    S.host = ui.element("div")
    with ui.row().classes("w-full no-wrap gap-0").style("min-height:100vh"):
        side = ui.element("div")
        with ui.column().classes("flex-grow gap-3").style("padding: 18px 22px; min-width:0"):
            main = ui.element("div").classes("w-full")
            with ui.expansion(t("Log")).classes("w-full card"):
                with ui.row().classes("w-full gap-2 pb-2"):
                    ui.button(t("Kopiuj log"), on_click=lambda: (ui.clipboard.write("".join(S.loglines)),
                                                                ui.notify(t("Log skopiowany do schowka."), type="positive"))) \
                        .props("unelevated no-caps dense").classes("ghost px-3")
                    ui.button(t("Otworz folder z logami"), on_click=lambda: os.startfile(LOG_DIR.resolve())) \
                        .props("unelevated no-caps dense").classes("ghost px-3")
                logbox = ui.log(max_lines=500).classes("w-full mono").style(f"height:200px; font-size:11.5px; "
                                                                            f"user-select:text; color:{MUTED}")

    def render():
        side.clear()
        with side:
            sidebar()
        main.clear()
        with main:
            with ui.column().classes("w-full gap-3"):
                if S.view == "quick":
                    quick_view()
                elif S.view == "d2jsp":
                    d2jsp_view()
                else:
                    items_view("Wystawione" if S.view == "listed" else "Przedmioty")

    def tick():
        while not S.logq.empty():
            logbox.push(S.logq.get_nowait().rstrip("\n"))
        if S.dirty and not S.editing:
            S.dirty = False
            render()

    render()
    first_visit()
    ui.timer(0.4, tick)
    ui.timer(NOTIFY_EVERY, notify_tick)


if __name__ in {"__main__", "__mp_main__"}:
    try:
        import webview  # noqa: F401  (pywebview -> natywne okno)
        native = True
    except Exception:
        native = False
    ui.run(title="D2 Trade", native=native, window_size=(1440, 900) if native else None, reload=False,
           show=not native, port=8765, favicon="⚔", show_welcome_message=False, uvicorn_logging_level="warning")
