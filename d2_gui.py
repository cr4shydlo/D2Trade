"""
d2_gui.py - okienkowa obsluga: zrzuty -> odczyt -> ceny -> wystawianie.

Uruchomienie: dwuklik na "D2 Trade.bat" albo:  pyw -3.11 d2_gui.py
"""
import os
import re
import sys
import json
import time
import queue
import random
import threading
import traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox, simpledialog

import paths
paths.use_data_dir()   # pliki (cache, auth, screenshots) obok skryptu (albo w D2_DANE)


def startup_error(msg: str):
    """Blad przy starcie: przy uruchomieniu przez pyw nie ma konsoli, wiec pokazujemy okienko i zapisujemy log."""
    Path("d2_gui_error.log").write_text(msg, encoding="utf-8")
    root = tk.Tk()
    root.withdraw()
    hint = ""
    if "No module named" in msg:
        mod = msg.split("No module named")[-1].strip().strip("'\"").split("'")[0]
        if mod in ("keyboard", "mss", "PIL", "ollama"):
            hint = (f"\n\nBrakuje biblioteki '{mod}'. W konsoli wpisz:\n"
                    "py -3.11 -m pip install keyboard mss pillow ollama")
        else:
            hint = f"\n\nBrakuje pliku {mod}.py w folderze {Path.cwd()}."
    first = msg if msg.startswith("Stare wersje") else msg.strip().splitlines()[-1]
    messagebox.showerror("D2 Trade - blad przy starcie", first + hint + "\n\nSzczegoly: d2_gui_error.log")
    root.destroy()
    sys.exit(1)


try:
    import i18n
    i18n.load()
    i18n.patch_tkinter()
    from PIL import Image, ImageTk
    import traderie_map as tm
    import traderie_price as tpr
    import traderie_post as tp
    import d2jsp_post
    import traderie_notify
    import traderie_sync
    import quick_price
    import app_config
    import d2_capture   # sprawdza od razu keyboard / mss
except Exception:
    startup_error(traceback.format_exc())

# pliki musza byc w zgodnych wersjach - sprawdzamy funkcje, z ktorych korzysta to okno
REQUIRED = {
    "i18n": (i18n, ["PROBLEMS", "languages", "tr", "font", "patch_tkinter", "save_setting"]),
    "traderie_map": (tm, ["SessionExpired", "range_parts", "range_key", "load_auth", "get_item"]),
    "traderie_price": (tpr, ["suggest", "rolls", "stat_name", "short", "ALIASES", "HIGH_ROLL"]),
    "traderie_post": (tp, ["search_items", "parse_price", "set_visible", "remove_listing", "mark_sold",
                           "describe", "fingerprint", "unregister"]),
    "traderie_sync": (traderie_sync, ["sync", "own_listings", "TRASH", "import_listings"]),
    "d2jsp_post": (d2jsp_post, ["build_post", "short_stats", "threads"]),
    "quick_price": (quick_price, ["quick_price", "variable_stats"]),
    "app_config": (app_config, ["apply", "save", "token_info", "OPTIONS"]),
}
_stale = sorted(f"{name}.py" for name, (mod, attrs) in REQUIRED.items() if any(not hasattr(mod, a) for a in attrs))
if _stale:
    startup_error("Stare wersje plikow: " + ", ".join(_stale) +
                  "\n\nPodmien je na najnowsze (sprawdz, czy przegladarka nie zapisala ich jako 'nazwa (1).py').")
try:
    app_config.apply()
except Exception:
    startup_error(traceback.format_exc())

NOTIFY_EVERY = 5 * 60      # co ile sekund sprawdzac powiadomienia Traderie

FOLDER = Path("screenshots")
STATUS = {"ready": "gotowy", "review": "do sprawdzenia", "skipped": "pominiety", "posted": "wystawiony",
          "sold": "sprzedany",
          "dup": "juz wystawiony?", "sending": "wysylanie...", "error": "blad"}
LEVELS = (("floor", "tanio"), ("typical", "typowo"), ("good", "dobrze"), ("high", "drogo"))
CHECK = {True: "\u2611", False: "\u2610"}   # pole wyboru


CARD = {  # kolory w stylu Traderie, rozjasnione
    "bg": "#2a2e36", "title": "#ffffff", "text": "#e8e9eb", "muted": "#b3b8bf", "line": "#454b56",
    "pill": "#3a404b", "pill_fg": "#e0bd6f", "price": "#ffd166", "button": "#d4ae62",
    "font": "Segoe UI",
}
CARD["font"] = i18n.font()   # np. Malgun Gothic dla koreanskiego
COLORS = {"deepskyblue": "#35b8ff", "crimson": "#ff4d6a", "chartreuse": "#9be15d", "gold": "#f5c542",
          "red": "#ff5555", "orange": "#ffa94d", "green": "#6fd96f"}
IMG_DIR = Path("cache") / "img"


def item_image(item: dict):
    """Obrazek przedmiotu z CDN Traderie (z cache na dysku). Zwraca sciezke albo None."""
    url = item.get("img")
    if not url:
        return None
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    path = IMG_DIR / (item.get("slug", "item") + Path(url).suffix)
    if not path.exists():
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": tm.UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                path.write_bytes(r.read())
        except Exception:
            return None
    return path


def render_description(txt, desc: str) -> int:
    """Opis Traderie ('**[color=DeepSkyBlue]+1-3[/color]** To ...') -> kolorowy tekst. Zwraca liczbe linii."""
    import re as _re
    base = CARD["font"]
    txt.tag_configure("b", font=(base, 11, "bold"))
    lines, blank = 0, True
    for raw in desc.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("|"):          # tabelki z wymaganiami pomijamy
            continue
        if not line.strip():
            if not blank:                          # najwyzej jedna pusta linia z rzedu
                txt.insert("end", "\n")
                lines += 1
                blank = True
            continue
        blank = False
        bold, colors = False, []
        for tok in _re.split(r"(\*\*|\[color=[^\]]+\]|\[/color\])", line):
            if tok == "**":
                bold = not bold
            elif tok.startswith("[color="):
                name = tok[7:-1]
                colors.append(COLORS.get(name.lower(), name))
            elif tok == "[/color]":
                colors = colors[:-1]
            elif tok:
                tags = []
                if bold:
                    tags.append("b")
                if colors:
                    tag = "c_" + colors[-1].lstrip("#")
                    try:
                        txt.tag_configure(tag, foreground=colors[-1])
                        tags.append(tag)
                    except tk.TclError:
                        pass
                txt.insert("end", tok, tuple(tags))
        txt.insert("end", "\n")
        lines += 1
    return lines


def friendly_error(what: str, e: Exception) -> str:
    msg = str(e)
    if any(code in msg for code in ("502", "503", "504")):
        return f"({what}: Traderie chwilowo niedostepne - sprobuje przy nastepnym sprawdzeniu)\n"
    return f"({what}: {msg})\n"


class QueueWriter:
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(("log", i18n.tr(s)))
            for stream in (sys.__stdout__,):          # przy pyw konsoli nie ma (None)
                try:
                    if stream:
                        stream.write(s)
                        stream.flush()
                except Exception:
                    pass

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("D2R -> Traderie")
        self.geometry("1440x860")
        self.q = queue.Queue()
        self.items = {}            # iid (nazwa pliku) -> dane przedmiotu
        self.order = []
        self.gen = 0               # numer wczytania listy - stare wyceny z tla sa ignorowane
        self.busy = False
        self.stop_event = threading.Event()
        self.capture_on = False
        self.hint_pool = ThreadPoolExecutor(max_workers=2)
        self.preview_img = None
        self.editor = None
        self.item_defs = {}         # nazwa -> definicja z Traderie (z cache na dysku, trzymana w pamieci)
        self.item_imgs = {}         # nazwa -> sciezka obrazka (cache/img)
        self.photo_cache = {}       # (nazwa, rozmiar) -> PhotoImage
        self.tip = None
        self.tip_iid = None
        self.listing_state = {}     # id oferty Traderie -> {'relist', 'hours_left', 'offers', 'hidden'}
        self.session_sold = set()   # oznaczone w tej sesji - zostaja widoczne, zeby mozna bylo cofnac
        sys.stdout = sys.stderr = QueueWriter(self.q)
        self._style()
        self._build()
        self.after(100, self._poll)
        self.reload_items()
        i18n.languages()
        for problem in dict.fromkeys(i18n.PROBLEMS):
            print(f"(plik jezykowy pominiety - {problem})\n")
        if len(i18n.languages()) == 1:
            print("(brak plikow jezykowych - umiesc en.json, de.json, ko.json w folderze lang obok programu)\n")

    # ================= wyglad =================
    def _style(self):
        """Ciemny motyw spojny z karta przedmiotu (styl Traderie)."""
        C = CARD
        bg, panel, field, text, muted, accent = C["bg"], "#323741", C["pill"], C["text"], C["muted"], C["button"]
        self.configure(bg=bg)
        self.option_add("*TCombobox*Listbox.background", field)
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        f = C["font"]
        st.configure(".", background=bg, foreground=text, fieldbackground=field, bordercolor=C["line"],
                     lightcolor=bg, darkcolor=bg, troughcolor=bg, font=(f, 10), insertcolor=text)
        st.configure("TFrame", background=bg)
        st.configure("TLabel", background=bg, foreground=text)
        st.configure("Title.TLabel", font=(f, 15, "bold"), foreground=C["title"])
        st.configure("Hint.TLabel", foreground=muted)
        st.configure("TButton", background=field, foreground=text, borderwidth=0, padding=(10, 5), relief="flat")
        st.map("TButton", background=[("disabled", panel), ("pressed", C["line"]), ("active", "#4a515e")],
               foreground=[("disabled", "#7d838c")])
        st.configure("Step.TButton", font=(f, 11, "bold"), padding=(14, 9), background=accent, foreground="#1b1b1b")
        st.map("Step.TButton", background=[("disabled", "#5a4f3a"), ("pressed", "#b08a44"), ("active", "#e0bb6b")],
               foreground=[("disabled", "#2a2a2a")])
        st.configure("Level.TButton", font=(f, 10, "bold"), padding=(10, 5), background=field, foreground=C["price"])
        st.map("Level.TButton", background=[("active", "#4a515e")])
        st.configure("TCheckbutton", background=bg, foreground=text, indicatorbackground=field,
                     indicatorforeground=accent)
        st.map("TCheckbutton", background=[("active", bg)], indicatorbackground=[("selected", field)])
        st.configure("TEntry", fieldbackground=field, foreground=text, insertcolor=text, padding=4)
        st.map("TEntry", fieldbackground=[("disabled", panel)], foreground=[("disabled", muted)])
        st.configure("Treeview", background=panel, fieldbackground=panel, foreground=text, rowheight=28,
                     font=(f, 10), borderwidth=0)
        st.map("Treeview", background=[("selected", "#4a6fa5")], foreground=[("selected", "#ffffff")])
        st.configure("Treeview.Heading", background=field, foreground=C["pill_fg"], font=(f, 10, "bold"),
                     relief="flat", padding=(4, 6))
        st.map("Treeview.Heading", background=[("active", "#4a515e")])
        st.configure("Vertical.TScrollbar", background=field, troughcolor=bg, arrowcolor=muted, borderwidth=0)
        st.configure("TPanedwindow", background=bg)
        st.configure("TCombobox", fieldbackground=field, background=field, foreground=text, arrowcolor=text,
                     selectbackground=field, selectforeground=text)
        st.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", text)])
        self.option_add("*TCombobox*Listbox.foreground", text)
        st.configure("Sash", sashthickness=6, gripcount=0, background=C["line"])

    def _build(self):
        # --- kroki ---
        steps = ttk.Frame(self, padding=8)
        steps.pack(fill="x")
        self.btn_capture = ttk.Button(steps, style="Step.TButton", command=self.toggle_capture)
        self.btn_capture.pack(side="left", padx=4)
        self.btn_read = ttk.Button(steps, text="2. Odczytaj nowe screeny", style="Step.TButton",
                                   command=self.prepare)
        self.btn_read.pack(side="left", padx=4)
        self.btn_post = ttk.Button(steps, style="Step.TButton", command=self.post_selected)
        self.btn_post.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(steps, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(steps, text="Folder screenow", command=lambda: os.startfile(FOLDER.resolve())).pack(side="right")
        ttk.Button(steps, text="Ustawienia", command=lambda: SettingsDialog(self)).pack(side="right", padx=6)
        self._capture_label()

        tools = ttk.Frame(self, padding=(8, 0))
        tools.pack(fill="x")
        ttk.Button(tools, text="Uzyj podpowiedzi dla wszystkich bez ceny", command=self.fill_hints).pack(side="left")
        ttk.Label(tools, text="     Szybka wycena:").pack(side="left")
        self.quick_var = tk.StringVar()
        qe = ttk.Entry(tools, textvariable=self.quick_var, width=28)
        qe.pack(side="left", padx=4)
        qe.bind("<Return>", lambda e: self.quick_check())
        ttk.Button(tools, text="Sprawdz", command=self.quick_check).pack(side="left")
        self.redo_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="przy odczycie: wszystkie screeny od nowa", variable=self.redo_var).pack(
            side="left", padx=12)
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="pokaz tez pominiete i dawniej sprzedane", variable=self.show_all,
                        command=self.fill_tree).pack(side="right")

        tools2 = ttk.Frame(self, padding=(8, 4))
        tools2.pack(fill="x")
        ttk.Label(tools2, text="d2jsp:").pack(side="left")
        ttk.Button(tools2, text="Kopiuj post sprzedazowy", command=self.copy_d2jsp).pack(side="left", padx=4)
        ttk.Button(tools2, text="Otworz moje watki", command=self.open_threads).pack(side="left", padx=4)
        ttk.Button(tools2, text="zmien linki", command=self.edit_threads).pack(side="left")
        ttk.Label(tools2, text="   Traderie:").pack(side="left")
        ttk.Button(tools2, text="Sprawdz oferty (sprzedane, do odnowienia)", command=self.sync_sold).pack(side="left", padx=4)
        self.notify_var = tk.BooleanVar(value=False)
        self.notify_lbl = ttk.Label(tools2, text="")
        self.notify_lbl.pack(side="right", padx=6)
        langs = i18n.languages()
        self.lang_codes = list(langs)
        self.lang_var = tk.StringVar(value=langs.get(i18n.current(), "Polski"))
        lc = ttk.Combobox(tools2, textvariable=self.lang_var, values=list(langs.values()), state="readonly", width=10)
        lc.pack(side="right", padx=(4, 0))
        lc.bind("<<ComboboxSelected>>", self.change_language)
        ttk.Label(tools2, text="   Jezyk:").pack(side="right")
        ttk.Checkbutton(tools2, text=f"sprawdzaj powiadomienia i sprzedane na Traderie co {NOTIFY_EVERY // 60} min",
                        variable=self.notify_var, command=self.toggle_notify).pack(side="right")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # --- tabela ---
        left = ttk.Frame(body)
        cols = ("sel", "name", "stats", "hint", "price", "status", "sold")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a in (("sel", "Wystaw", 64, "center"), ("name", "Przedmiot", 190, "w"),
                           ("stats", "Staty", 260, "w"), ("hint", "Podpowiedz", 90, "center"),
                           ("price", "Cena (dwuklik)", 150, "center"), ("status", "Status", 110, "center"),
                           ("sold", "Sprzedany", 80, "center")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, stretch=(c == "stats"))
        for st, color in (("ready", "#33443a"), ("review", "#56462c"), ("skipped", "#30343c"), ("sold", "#30343c"),
                          ("posted", "#33405a"), ("relist", "#6a4f22"), ("dup", "#553849"), ("error", "#6a3540"),
                          ("sending", "#55502c")):
            self.tree.tag_configure(st, background=color)
        self.tree.tag_configure("skipped", foreground="#9aa0a8")
        self.tree.tag_configure("sold", foreground="#9aa0a8")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_details())
        self.tree.bind("<Button-1>", self.on_click, add="+")
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Return>", lambda e: self.price_dialog(self.current()))
        self.tree.bind("<Delete>", lambda e: self.delete_item())
        self.tree.bind("<Motion>", self.on_motion)
        self.tree.bind("<Leave>", lambda e: self.hide_tip())
        body.add(left, weight=3)

        # --- panel szczegolow ---
        right = ttk.Frame(body, padding=(10, 0))
        self.title_lbl = ttk.Label(right, text="", style="Title.TLabel")
        self.title_lbl.pack(anchor="w")
        self.img_label = ttk.Label(right)
        self.img_label.pack(anchor="w", pady=4)
        self.info = ttk.Label(right, text="", wraplength=460, justify="left")
        self.info.pack(anchor="w", fill="x")

        ttk.Label(right, text="Cena z ostatnich transakcji (kliknij, zeby ustawic):").pack(anchor="w", pady=(10, 2))
        self.levels_row = ttk.Frame(right)
        self.levels_row.pack(anchor="w")

        row = ttk.Frame(right)
        row.pack(anchor="w", pady=(10, 0))
        ttk.Label(row, text="Wlasna cena:").pack(side="left")
        self.price_var = tk.StringVar()
        self.price_entry = ttk.Entry(row, textvariable=self.price_var, width=20, font=("Segoe UI", 11))
        self.price_entry.pack(side="left", padx=6)
        self.price_entry.bind("<Return>", lambda e: self.commit_side_price())
        self.price_entry.bind("<FocusOut>", lambda e: self.commit_side_price())
        ttk.Button(row, text="Wybierz cene...", command=self.price_dialog).pack(side="left", padx=4)
        ttk.Label(right, text="np.  ist   ist+mal   2 ist   3 pamy   ber | jah   offer   (puste = nie wystawiaj)",
                  style="Hint.TLabel").pack(anchor="w", pady=2)
        self.price_msg = ttk.Label(right, text="", foreground="#ff6b6b")
        self.price_msg.pack(anchor="w")
        ttk.Button(right, text="Zly odczyt? Zaznacz tooltip recznie i odczytaj ponownie",
                   command=self.fix_crop).pack(anchor="w", pady=(12, 0))
        self.btn_sold = ttk.Button(right, text="Oznacz jako sprzedany", command=self.toggle_sold)
        self.btn_sold.pack(anchor="w", pady=(6, 0))
        row2 = ttk.Frame(right)
        row2.pack(anchor="w", pady=(6, 0))
        self.btn_hide = ttk.Button(row2, text="Ukryj na Traderie", command=self.toggle_hidden)
        self.btn_hide.pack(side="left")
        self.btn_remove = ttk.Button(row2, text="Usun oferte z Traderie", command=self.remove_from_traderie)
        self.btn_remove.pack(side="left", padx=6)
        ttk.Button(right, text="Usun z listy (nie sprzedaje tego)", command=self.delete_item).pack(anchor="w", pady=(6, 0))
        body.add(right, weight=2)

        # --- pasek stanu i log ---
        self.status_bar = ttk.Label(self, text="", padding=(8, 2))
        self.status_bar.pack(fill="x")
        self.log = tk.Text(self, height=7, font=("Consolas", 9), bg="#22252c", fg="#d6d9de", relief="flat",
                           highlightthickness=0, insertbackground="#d6d9de", padx=8, pady=6)
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    def _capture_label(self):
        import d2_capture
        key = d2_capture.HOTKEY.upper()
        self.btn_capture.config(text=f"1. Zrzuty w grze ({key}): {'WLACZONE' if self.capture_on else 'wylaczone'}")

    # ================= watki =================
    def _poll(self):
        try:
            while True:
                kind, *data = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", i18n.tr(data[0]))
                    self.log.see("end")
                elif kind == "hint":
                    gen, iid, res = data
                    if gen == self.gen and iid in self.items:
                        self.items[iid]["hint"] = res
                        self.refresh_row(iid)
                        if self.current() == iid:
                            self.show_details(keep_entry=True)
                elif kind == "reload":
                    self.reload_items()
                elif kind == "row":
                    self.refresh_row(data[0])
                elif kind == "done":
                    self.set_busy(False)
                elif kind == "error":
                    messagebox.showerror("Blad", data[0])
                elif kind == "state":
                    self.listing_state = data[0]
                    for iid in list(self.items):
                        self.refresh_row(iid)
                    if self.current():
                        self.show_details(keep_entry=True)
                elif kind == "quick":
                    self.show_quick(data[0], data[1])
                elif kind == "sold":
                    self.bell()
                    self.session_sold |= {i for i, it in self.items.items() if it["lst"].get("name") in data[0]}
                    print("Sprzedane na Traderie: " + ", ".join(data[0]) +
                          "  - skopiuj post d2jsp ponownie, zeby je z niego usunac\n")
                    self.reload_items()
                elif kind == "notif":
                    new = data[0]
                    if new:
                        self.bell()
                        self.title(f"D2R -> Traderie  ({len(new)} nowych powiadomien)")
                        self.notify_lbl.config(text=f"ostatnio: {len(new)} nowych, {time.strftime('%H:%M')}")
                        for when, text in new:
                            self.log.insert("end", f"[Traderie {when}] {text}\n")
                        self.log.see("end")
                    else:
                        self.notify_lbl.config(text=f"brak nowych ({time.strftime('%H:%M')})")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def set_busy(self, busy: bool):
        self.busy = busy
        st = "disabled" if busy else "normal"
        self.btn_read.config(state=st)
        self.btn_post.config(state=st)
        self.btn_stop.config(state="normal" if busy else "disabled")

    def run_bg(self, fn):
        if self.busy:
            return
        self.set_busy(True)
        self.stop_event.clear()

        def wrap():
            try:
                fn()
            except Exception:
                print(traceback.format_exc())
                self.q.put(("error", "Cos poszlo nie tak - szczegoly w logu na dole."))
            finally:
                self.q.put(("done",))
        threading.Thread(target=wrap, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        print("\n-- zatrzymywanie po biezacym kroku --\n")

    # ================= krok 1: zrzuty =================
    def toggle_capture(self):
        import keyboard
        import d2_capture
        if self.capture_on:
            keyboard.remove_hotkey(self._hotkey)
            self.capture_on = False
        else:
            self._hotkey = keyboard.add_hotkey(d2_capture.HOTKEY, d2_capture.capture)
            self.capture_on = True
            print(f"Zrzuty wlaczone - w grze najedz na przedmiot i wcisnij {d2_capture.HOTKEY.upper()}.\n")
        self._capture_label()

    # ================= krok 2: odczyt =================
    def prepare(self):
        redo = self.redo_var.get()

        def job():
            import d2_ocr
            FOLDER.mkdir(exist_ok=True)
            print("Odczyt screenow (gra musi byc zamknieta - model potrzebuje karty graficznej)\n")
            if d2_ocr.run(FOLDER, redo=redo, verbose=False) < 0:
                self.q.put(("error", "Model nie miesci sie na karcie graficznej - zamknij gre i sprobuj ponownie."))
                return
            d2_ocr.unload_model()
            print("\nDopasowanie do Traderie\n")
            tm.run(FOLDER, verbose=False)
            self.q.put(("reload",))
        self.redo_var.set(False)
        self.run_bg(job)

    # ================= lista =================
    def reload_items(self):
        FOLDER.mkdir(exist_ok=True)
        self.gen += 1
        registry = tp.load_registry(FOLDER)
        prices = json.loads(tp.PRICES_FILE.read_text(encoding="utf-8")) if tp.PRICES_FILE.exists() else {}
        self.items, self.order = {}, []
        for f in sorted(FOLDER.glob("*.listing.json")):
            lst = json.loads(f.read_text(encoding="utf-8"))
            if lst.get("sold"):
                status = "sold"
            elif lst.get("posted"):
                status = "posted"
            elif lst.get("skipped"):
                status = "skipped"
            elif lst.get("needs_review") or "listing" not in lst:
                status = "review"
            elif tp.fingerprint(lst) in registry:
                status = "dup"
            else:
                status = "ready"
            price = (lst.get("posted") or {}).get("price") or lst.get("planned_price") or ""
            iid = f.name
            self.items[iid] = {"file": f, "lst": lst, "status": status, "price": price, "hint": None,
                               "selected": status == "ready" and bool(price),
                               "dup": registry.get(tp.fingerprint(lst)) if status == "dup" else None,
                               "last": prices.get(lst.get("slug"))}
            self.order.append(iid)
        self.fill_tree()
        names = {self.items[i]["lst"].get("name") for i in self.order if self.items[i]["lst"].get("name")}
        threading.Thread(target=self._prefetch, args=(sorted(names),), daemon=True).start()
        for iid in self.order:
            if self.items[iid]["status"] in ("ready", "dup"):
                self.hint_pool.submit(self._hint_job, self.gen, iid, self.items[iid]["lst"])

    def _hint_job(self, gen, iid, lst):
        try:
            res = tpr.suggest(lst, tm.get_item(lst["name"]))
        except Exception as e:
            res = {"text": f"(wycena nie powiodla sie: {e})", "price": "", "levels": {}}
        self.q.put(("hint", gen, iid, res))

    def fill_tree(self):
        sel = self.current()
        self.tree.delete(*self.tree.get_children())
        for iid in self.order:
            it = self.items[iid]
            hidden = it["status"] == "skipped" or (it["status"] == "sold" and iid not in self.session_sold)
            if self.show_all.get() or not hidden:
                self.tree.insert("", "end", iid=iid, values=self.row_values(it), tags=(it["status"],))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
        self.update_counts()

    def row_values(self, it):
        lst = it["lst"]
        name = (lst.get("name") or lst.get("ocr_name", "?")) + (i18n.tr("  [z Traderie]") if lst.get("imported") else "")
        if it["status"] == "skipped":
            stats = lst.get("skipped", "")
        elif it["status"] == "review":
            stats = "; ".join(lst.get("warnings") or ["odczyt niepewny - sprawdz screen"])
        else:
            item = self.item_def(lst.get("name"))
            short, flags = d2jsp_post.short_stats(lst, item)
            stats = "/".join(short) + (f"  ({', '.join(flags)})" if flags else "")
        can = it["status"] in ("ready", "dup")
        sel = CHECK[bool(it["selected"])] if can else ""
        hint = (it["hint"] or {}).get("price", "") if can else ""
        if can and it["hint"] is None:
            hint = "..."
        sold = CHECK[bool(it["lst"].get("sold"))] if it["status"] in ("posted", "ready", "dup", "sold") else ""
        status = i18n.tr(STATUS.get(it["status"], it["status"]))
        st = self.state_of(it)
        if st:
            if st["hidden"]:
                status += i18n.tr(" (ukryty)")
            if st["relist"]:
                status = i18n.tr("DO ODNOWIENIA")
            if st["offers"]:
                status += i18n.tr(" | oferty: ") + str(st["offers"])
        return (sel, name, i18n.tr(stats), hint, it["price"], i18n.tr(status), sold)

    def _prefetch(self, names):
        """W tle: definicje i obrazki przedmiotow z listy (kazdy pobierany tylko raz, potem z dysku)."""
        for n in names:
            try:
                item = self.item_def(n)
                if item and n not in self.item_imgs:
                    self.item_imgs[n] = item_image(item)
            except Exception:
                pass

    def photo(self, name, size):
        """Miniatura obrazka przedmiotu (tylko z dysku - bez czekania na siec)."""
        key = (name, size)
        if key not in self.photo_cache:
            path = self.item_imgs.get(name)
            if not path or not Path(path).exists():
                return None
            try:
                img = Image.open(path).convert("RGBA")
                img.thumbnail(size)
                self.photo_cache[key] = ImageTk.PhotoImage(img)
            except Exception:
                return None
        return self.photo_cache[key]

    def item_def(self, name):
        if name not in self.item_defs:
            self.item_defs[name] = tm.get_item(name) if name else None
        return self.item_defs[name]

    def state_of(self, it):
        if it["status"] != "posted":
            return None
        return self.listing_state.get(str((it["lst"].get("posted") or {}).get("listing_id")))

    def refresh_row(self, iid):
        it = self.items.get(iid)
        if it and self.tree.exists(iid):
            st = self.state_of(it)
            tag = "relist" if st and st["relist"] else it["status"]
            self.tree.item(iid, values=self.row_values(it), tags=(tag,))
        self.update_counts()

    def update_counts(self):
        c = {}
        for it in self.items.values():
            c[it["status"]] = c.get(it["status"], 0) + 1
        n = self.selected_count()
        self.btn_post.config(text=f"3. Wystaw zaznaczone ({n})")
        self.status_bar.config(text=f"gotowe: {c.get('ready', 0)}     do sprawdzenia: {c.get('review', 0)}     "
                                    f"mozliwe duplikaty: {c.get('dup', 0)}     wystawione: {c.get('posted', 0)}     "
                                    f"pominiete: {c.get('skipped', 0)}     sprzedane: {c.get('sold', 0)}")

    def selected_count(self):
        return sum(1 for it in self.items.values() if it["selected"] and it["status"] in ("ready", "dup"))

    def current(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    # ================= klikanie w tabeli =================
    def on_click(self, e):
        if self.tree.identify_region(e.x, e.y) != "cell":
            return
        iid = self.tree.identify_row(e.y)
        col = self.tree.identify_column(e.x)
        if iid and col == "#1":
            self.toggle(iid)
        elif iid and col == "#7":
            self.toggle_sold(iid)

    def change_language(self, e=None):
        names = i18n.languages()
        code = next((k for k, v in names.items() if v == self.lang_var.get()), "pl")
        if code == i18n.current():
            return
        i18n.save_setting("lang", code)
        if messagebox.askyesno("Jezyk", "Zmiana jezyka wymaga ponownego uruchomienia okna. Uruchomic ponownie teraz?"):
            self.destroy()
            os.execl(sys.executable, sys.executable, str(Path(__file__).resolve()))

    # ---------- dymek ze statami ----------
    def on_motion(self, e):
        iid = self.tree.identify_row(e.y)
        if iid != self.tip_iid:
            self.hide_tip()
            self.tip_iid = iid
            if iid:
                self._tip_job = self.after(350, lambda: self.show_tip(iid))
        elif self.tip is not None:
            self.tip.geometry(f"+{e.x_root + 18}+{e.y_root + 14}")

    def hide_tip(self):
        if getattr(self, "_tip_job", None):
            self.after_cancel(self._tip_job)
            self._tip_job = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None
        self.tip_iid = None if self.tip is None else self.tip_iid

    def show_tip(self, iid):
        self._tip_job = None
        it = self.items.get(iid)
        if not it or it["status"] == "skipped" or not it["lst"].get("listing"):
            return
        lst = it["lst"]
        item = self.item_def(lst.get("name"))
        C = CARD
        tip = tk.Toplevel(self, bg=C["line"])
        tip.wm_overrideredirect(True)
        outer = tk.Frame(tip, bg=C["bg"], padx=12, pady=8)
        outer.pack(padx=1, pady=1)
        ph = self.photo(lst.get("name"), (70, 110))
        if ph:
            tk.Label(outer, image=ph, bg=C["bg"]).pack(side="left", anchor="n", padx=(0, 12))
        body = tk.Frame(outer, bg=C["bg"])
        body.pack(side="left", anchor="n")
        tk.Label(body, text=lst.get("name", "?"), bg=C["bg"], fg=C["title"], font=(C["font"], 12, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        r = 1
        rolls = tpr.rolls(lst, item) if item else []
        rolled = {pid for pid, *_ in rolls}
        if rolls:
            tk.Label(body, text="ZMIENNE", bg=C["bg"], fg=C["muted"], font=(C["font"], 8, "bold")).grid(
                row=r, column=0, sticky="w")
            r += 1
            for pid, name, v, lo, hi, pct in rolls:
                high = pct >= tpr.HIGH_ROLL
                tk.Label(body, text=name, bg=C["bg"], fg=C["text"], font=(C["font"], 10)).grid(
                    row=r, column=0, sticky="w", padx=(0, 10))
                tk.Label(body, text=f"[{lo}-{hi}]", bg=C["bg"], fg=COLORS["deepskyblue"],
                         font=(C["font"], 10)).grid(row=r, column=1, sticky="e", padx=(0, 8))
                tk.Label(body, text=f"{v}  ({round(pct * 100)}%)", bg=C["bg"],
                         fg=C["price"] if high else C["title"], font=(C["font"], 10, "bold")).grid(
                    row=r, column=2, sticky="w")
                r += 1
        others = []
        defs = {p["property_id"]: p for p in item["properties"]} if item else {}
        for e in lst["listing"]:
            d = defs.get(e["property_id"]) or {"property": e.get("property", "")}
            prop = d.get("property", "")
            if e["property_id"] in rolled or d.get("required") or prop in tp.REQUIRED:
                continue
            others.append(f"{tpr.stat_name(prop)}: {e['value']}" if e["value"] is not True else tpr.stat_name(prop))
        if others:
            tk.Label(body, text="POZOSTALE", bg=C["bg"], fg=C["muted"], font=(C["font"], 8, "bold")).grid(
                row=r, column=0, sticky="w", pady=(6, 0))
            r += 1
            for o in others:
                tk.Label(body, text=o, bg=C["bg"], fg=C["text"], font=(C["font"], 10)).grid(
                    row=r, column=0, columnspan=3, sticky="w")
                r += 1
        if not rolls and not others:
            tk.Label(body, text="brak zmiennych statow", bg=C["bg"], fg=C["muted"], font=(C["font"], 10)).grid(
                row=r, column=0, sticky="w")
        x, y = self.winfo_pointerx() + 18, self.winfo_pointery() + 14
        tip.geometry(f"+{x}+{y}")
        self.tip = tip
        self.tip_iid = iid

    def on_double(self, e):
        iid = self.tree.identify_row(e.y)
        col = self.tree.identify_column(e.x)
        if iid and col in ("#4", "#5"):
            self.price_dialog(iid)

    def toggle(self, iid):
        it = self.items[iid]
        if it["status"] not in ("ready", "dup"):
            return
        if not it["selected"] and not it["price"]:
            hint = (it["hint"] or {}).get("price")
            if hint:
                self.set_price(iid, hint)      # zaznaczenie bez ceny -> bierzemy podpowiedz
                return
            messagebox.showinfo("Cena", "Najpierw ustaw cene (dwuklik w kolumnie 'Twoja cena').")
            return
        it["selected"] = not it["selected"]
        self.refresh_row(iid)

    def price_dialog(self, iid=None):
        iid = iid or self.current()
        if not iid or self.items[iid]["status"] not in ("ready", "dup"):
            return
        it = self.items[iid]
        cur = it["price"] or (it["hint"] or {}).get("price", "")
        PriceDialog(self, it["lst"].get("name", "?"), cur, lambda v: self.set_price(iid, v))

    def edit_price(self, iid):
        if not iid or self.items[iid]["status"] not in ("ready", "dup"):
            return
        if self.editor:
            self.editor.destroy()
        x, y, w, h = self.tree.bbox(iid, "#5")
        var = tk.StringVar(value=self.items[iid]["price"] or (self.items[iid]["hint"] or {}).get("price", ""))
        ent = ttk.Entry(self.tree, textvariable=var, justify="center")
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_set()
        ent.select_range(0, "end")
        self.editor = ent

        def done(save):
            if self.editor is None:
                return
            self.editor = None
            ent.destroy()
            if save:
                self.set_price(iid, var.get())
        ent.bind("<Return>", lambda e: done(True))
        ent.bind("<FocusOut>", lambda e: done(True))
        ent.bind("<Escape>", lambda e: done(False))

    # ================= ceny =================
    def set_price(self, iid, val: str) -> bool:
        """Zapisuje cene przedmiotu. Niepusta cena = zaznaczony do wystawienia, pusta = odznaczony."""
        it = self.items[iid]
        val = val.strip().lower()
        if val:
            try:
                tp.parse_price(val)
            except ValueError as e:
                # bez okienka - okienko zabiera fokus i wywoluje zapis ponownie
                self.price_msg.config(text=f"{it['lst'].get('name')}: niepoprawna cena '{val}' ({e})")
                self.bell()
                return False
        self.price_msg.config(text="")
        it["price"] = val
        it["selected"] = bool(val)
        if val:
            it["lst"]["planned_price"] = val
        else:
            it["lst"].pop("planned_price", None)
        it["file"].write_text(json.dumps(it["lst"], ensure_ascii=False, indent=2), encoding="utf-8")
        self.refresh_row(iid)
        if self.current() == iid:
            self.show_details()
        return True

    def commit_side_price(self):
        iid = self.current()
        if getattr(self, "_committing", False) or not iid:
            return
        it = self.items[iid]
        if it["status"] in ("ready", "dup") and self.price_var.get().strip().lower() != it["price"]:
            self._committing = True
            try:
                self.set_price(iid, self.price_var.get())
            finally:
                self._committing = False

    def fill_hints(self):
        n = 0
        for iid in self.order:
            it = self.items[iid]
            if it["status"] == "ready" and not it["price"] and (it["hint"] or {}).get("price"):
                self.set_price(iid, it["hint"]["price"])
                n += 1
        print(f"Ustawiono podpowiedz dla {n} przedmiotow (duplikatow nie ruszam).\n")

    # ================= panel szczegolow =================
    def stem_of(self, it):
        src = Path(it["lst"].get("source", ""))
        return Path(src.name).stem if src.name else it["file"].name.replace(".listing.json", "")

    def show_details(self, keep_entry=False):
        iid = self.current()
        if not iid:
            return
        it = self.items[iid]
        lst = it["lst"]
        self.title_lbl.config(text=lst.get("name") or lst.get("ocr_name", "?"))
        stem = self.stem_of(it)
        img_path = next((p for p in (FOLDER / "_crops" / f"{stem}.png", FOLDER / f"{stem}.png") if p.exists()), None)
        if img_path:
            img = Image.open(img_path)
            img.thumbnail((460, 330))
            self.preview_img = ImageTk.PhotoImage(img)
            self.img_label.config(image=self.preview_img)
        else:   # np. oferta zaimportowana z Traderie - obrazek przedmiotu zamiast screena
            ph = self.photo(lst.get("name"), (160, 220))
            self.img_label.config(image=ph or "")

        t = []
        if it["status"] == "posted":
            p = lst["posted"]
            t.append(f"Wystawiony {p.get('time')} za {p.get('price')}.")
            st = self.state_of(it)
            if st:
                t.append("Gotowy do ODNOWIENIA - odnow go na stronie Traderie (przycisk ze strzalkami)." if st["relist"]
                         else f"Odnowienie mozliwe za ok. {st['hours_left']:.0f} h.")
                if st["offers"]:
                    t.append(f"Oferty kupna: {st['offers']} - sprawdz na Traderie.")
        if it["dup"]:
            d = it["dup"]
            t += [f"Podobny przedmiot wystawiono {d.get('time')} za {d.get('price')}.",
                  f"Wtedy: {', '.join(d.get('stats') or []) or '-'}",
                  "Jesli to inny egzemplarz - ustaw cene, zeby go wystawic."]
        for w in lst.get("warnings") or []:
            t.append("! " + w)
        if lst.get("skipped"):
            t.append(lst["skipped"])
        if it["hint"]:
            t.append(it["hint"].get("text", "").replace("   ", "").strip())
        elif it["status"] in ("ready", "dup"):
            t.append("wycena w toku...")
        if it["last"]:
            t.append(f"Ostatnio wystawiales ten przedmiot za: {it['last']}")
        self.info.config(text="\n".join(x for x in t if x))

        for w in self.levels_row.winfo_children():
            w.destroy()
        levels = (it["hint"] or {}).get("levels") or {}
        can = it["status"] in ("ready", "dup")
        for key, label in LEVELS:
            if levels.get(key):
                ttk.Button(self.levels_row, text=f"{label}: {levels[key]}", style="Level.TButton",
                           state="normal" if can else "disabled",
                           command=lambda v=levels[key], i=iid: self.set_price(i, v)).pack(side="left", padx=2)
        if not levels:
            ttk.Label(self.levels_row, text="-", style="Hint.TLabel").pack(side="left")

        # pole wlasnej ceny: nie nadpisujemy, gdy uzytkownik akurat w nim pisze
        if not (keep_entry and self.focus_get() == self.price_entry):
            self.price_var.set(it["price"])
        self.price_entry.config(state="normal" if can else "disabled")
        self.btn_sold.config(text="Cofnij: nie sprzedany" if lst.get("sold") else "Oznacz jako sprzedany")
        on_t = it["status"] == "posted" and bool(lst["posted"].get("listing_id"))
        self.btn_remove.config(state="normal" if on_t else "disabled")
        st = self.state_of(it)
        self.btn_hide.config(state="normal" if on_t else "disabled",
                             text="Pokaz na Traderie" if (st and st["hidden"]) else "Ukryj na Traderie")

    # ================= sprzedane / d2jsp / powiadomienia =================
    def toggle_sold(self, iid=None):
        iid = iid or self.current()
        if not iid:
            return
        it = self.items[iid]
        lst = it["lst"]
        if lst.get("sold"):
            lst.pop("sold")
            lst.pop("sold_via", None)
            it["file"].write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Cofnieto sprzedaz: {lst.get('name', '')} (na Traderie cofnij recznie, jesli trzeba)\n")
            self.session_sold.discard(iid)
            self.reload_items()
            self.show_details()
            return

        lid = (lst.get("posted") or {}).get("listing_id")
        on_traderie = False
        if lid:
            on_traderie = messagebox.askyesno(
                "Sprzedany", f"{lst.get('name')} jest wystawiony na Traderie.\n\n"
                             "Oznaczyc go tam tez jako sprzedany (zeby nikt go nie kupil drugi raz)?")
        lst["sold"] = time.strftime("%Y-%m-%d %H:%M")
        it["file"].write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
        self.session_sold.add(iid)
        print(f"Oznaczono jako sprzedany: {lst.get('name', '')}  (skopiuj post d2jsp ponownie)\n")
        self.reload_items()
        self.show_details()
        if on_traderie:
            def job():
                ok, msg = tp.mark_sold(lid, tm.load_auth())
                if ok:
                    lst["sold_via"] = "recznie + Traderie"
                    it["file"].write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"   Traderie: oferta {lst.get('name')} oznaczona jako sprzedana\n")
                else:
                    self.q.put(("error", f"Nie udalo sie oznaczyc na Traderie: {msg}\n\n"
                                         "Oznacz ja recznie na stronie (Mark Sold)."))
            self.run_bg(job)

    def delete_item(self, iid=None):
        """Usuwa przedmiot z listy (pliki trafiaja do screenshots/_trash - mozna je przywrocic recznie)."""
        iid = iid or self.current()
        if not iid:
            return
        it = self.items[iid]
        lst = it["lst"]
        lid = (lst.get("posted") or {}).get("listing_id") if it["status"] == "posted" else None
        also_traderie = False
        if lid:
            ans = messagebox.askyesnocancel(
                "Usun z listy", f"{lst.get('name')} jest wystawiony na Traderie.\n\n"
                                "Tak - usun z listy i zdejmij oferte z Traderie\n"
                                "Nie - usun tylko z listy (oferta zostaje na Traderie)\nAnuluj - nic nie rob")
            if ans is None:
                return
            also_traderie = ans
        elif not messagebox.askyesno("Usun z listy", f"Usunac {lst.get('name') or lst.get('ocr_name')} z listy?"):
            return

        def move():
            trash = FOLDER / traderie_sync.TRASH
            trash.mkdir(exist_ok=True)
            stem = self.stem_of(it)
            files = [it["file"]] + [p for p in FOLDER.glob(stem + ".*") if p != it["file"]]
            files += [p for p in (FOLDER / "_crops").glob(stem + ".*")]
            for p in files:
                if p.exists():
                    p.replace(trash / p.name)
            print(f"Usunieto z listy: {lst.get('name') or lst.get('ocr_name')}\n")
            self.q.put(("reload",))

        if also_traderie:
            def job():
                ok, msg = tp.remove_listing(lid, tm.load_auth())
                if not ok:
                    self.q.put(("error", f"Nie udalo sie zdjac oferty z Traderie: {msg}\nPrzedmiot zostaje na liscie."))
                    return
                tp.unregister(lst)
                lst["removed"] = {"time": time.strftime("%Y-%m-%d %H:%M"), **lst.pop("posted")}
                it["file"].write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
                move()
            self.run_bg(job)
        else:
            move()

    def toggle_hidden(self, iid=None):
        iid = iid or self.current()
        if not iid:
            return
        it = self.items[iid]
        lid = str((it["lst"].get("posted") or {}).get("listing_id") or "")
        if it["status"] != "posted" or not lid:
            return
        st = self.listing_state.get(lid)
        visible = bool(st and st["hidden"])          # ukryty -> przywroc, w pozostalych przypadkach -> ukryj

        def job():
            ok, msg = tp.set_visible(lid, visible, tm.load_auth())
            if not ok:
                self.q.put(("error", f"Nie udalo sie {'przywrocic' if visible else 'ukryc'} oferty: {msg}"))
                return
            state = dict(self.listing_state)
            state[lid] = {**(state.get(lid) or {"relist": False, "hours_left": 0, "offers": 0}), "hidden": not visible}
            self.q.put(("state", state))
            print(f"{'Przywrocono' if visible else 'Ukryto'} na Traderie: {it['lst'].get('name')}\n")
        self.run_bg(job)

    def remove_from_traderie(self, iid=None):
        iid = iid or self.current()
        if not iid:
            return
        it = self.items[iid]
        lst = it["lst"]
        lid = (lst.get("posted") or {}).get("listing_id")
        if it["status"] != "posted" or not lid:
            return
        if not messagebox.askyesno("Usun z Traderie", f"Usunac oferte {lst.get('name')} z Traderie?\n\n"
                                                      "Przedmiot wroci na liste jako gotowy do wystawienia."):
            return

        def job():
            ok, msg = tp.remove_listing(lid, tm.load_auth())
            if not ok:
                self.q.put(("error", f"Nie udalo sie usunac oferty: {msg}"))
                return
            tp.unregister(lst)
            lst["removed"] = {"time": time.strftime("%Y-%m-%d %H:%M"), **lst.pop("posted")}
            it["file"].write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Usunieto z Traderie: {lst.get('name')}\n")
            self.q.put(("reload",))
        self.run_bg(job)

    def copy_d2jsp(self):
        entries = []
        for iid in self.order:
            it = self.items[iid]
            if it["status"] in ("posted", "ready", "dup") and it["price"] and not it["lst"].get("sold"):
                entries.append((it["lst"], it["price"]))
        if not entries:
            messagebox.showinfo("d2jsp", "Brak przedmiotow z cena (wystawionych albo gotowych).")
            return
        text = d2jsp_post.build_post(entries)
        self.clipboard_clear()
        self.clipboard_append(text)
        print(f"Skopiowano post d2jsp ({len(entries)} przedmiotow) - wklej go w swoim watku.\n")
        messagebox.showinfo("d2jsp", f"Post z {len(entries)} przedmiotami jest w schowku.\n\n"
                                     "Wklej go w nowym watku albo edytuj nim pierwszy post istniejacego.")

    def edit_threads(self):
        cur = ", ".join(d2jsp_post.threads())
        val = simpledialog.askstring("Watki d2jsp", "Linki do Twoich watkow sprzedazowych (oddziel przecinkami):",
                                     initialvalue=cur, parent=self)
        if val is not None:
            d2jsp_post.save_threads([u.strip() for u in val.split(",") if u.strip().startswith("http")])

    def open_threads(self):
        urls = d2jsp_post.threads()
        if not urls:
            self.edit_threads()
            urls = d2jsp_post.threads()
        for u in urls:
            webbrowser.open(u)

    def quick_check(self):
        q = self.quick_var.get().strip()
        if not q:
            messagebox.showinfo("Szybka wycena", "Wpisz nazwe i opcjonalnie staty, np.:\n\n"
                                                 "shako def 136\nspirit fcr 35 mana 110\narach ed 120\n"
                                                 "annihilus attr 20 @20 xp 10")
            return

        def job():
            try:
                res = quick_price.quick_price(q)
            except Exception as e:
                res = {"title": "Szybka wycena", "text": f"Blad: {e}", "levels": {}}
            if not res.get("item") and res.get("title") and res["title"] != "Szybka wycena":
                res["item"] = tm.get_item(res["title"])   # starsza wersja quick_price nie zwracala przedmiotu
            if res.get("item"):
                res["img_path"] = item_image(res["item"])
            self.q.put(("quick", q, res))
        threading.Thread(target=job, daemon=True).start()
        print(f"Szybka wycena: {q} ...\n")

    def show_quick(self, q, res):
        """Karta przedmiotu w stylu Traderie: ciemne tlo, obrazek, tagi, kolorowy opis, poziomy ceny."""
        C = CARD
        win = tk.Toplevel(self, bg=C["bg"])
        win.title(f"Wycena: {res['title']}")
        item = res.get("item") or {}
        pad = {"padx": 18}

        # obrazek
        if res.get("img_path"):
            try:
                img = Image.open(res["img_path"]).convert("RGBA")
                img.thumbnail((140, 180))
                win._img = ImageTk.PhotoImage(img)
                tk.Label(win, image=win._img, bg=C["bg"]).pack(pady=(14, 4))
            except Exception:
                pass
        tk.Label(win, text=res["title"], bg=C["bg"], fg=C["title"], font=(C["font"], 18, "bold")).pack(
            anchor="w", **pad, pady=(6, 4))

        # tagi jak na Traderie
        tags = [t.get("tag") for t in item.get("tags") or [] if t.get("tag")]
        if tags:
            tr = tk.Frame(win, bg=C["bg"])
            tr.pack(anchor="w", **pad, pady=(0, 8))
            for t in tags[:6]:
                tk.Label(tr, text=t, bg=C["pill"], fg=C["pill_fg"], font=(C["font"], 9, "bold"),
                         padx=10, pady=3).pack(side="left", padx=(0, 6))

        # opis z kolorami
        desc = item.get("description") or ""
        if desc:
            txt = tk.Text(win, width=56, bg=C["bg"], fg=C["text"], font=(C["font"], 11), relief="flat",
                          highlightthickness=0, wrap="word", padx=0, pady=0, spacing1=2)
            n = render_description(txt, desc)
            txt.config(height=max(3, n), state="disabled")
            txt.pack(anchor="w", **pad, pady=(0, 6), fill="x")

        tk.Frame(win, bg=C["line"], height=1).pack(fill="x", **pad, pady=8)

        # ceny
        tk.Label(win, text="CENA Z OSTATNICH TRANSAKCJI", bg=C["bg"], fg=C["muted"],
                 font=(C["font"], 9, "bold")).pack(anchor="w", **pad)
        row = tk.Frame(win, bg=C["bg"])
        row.pack(anchor="w", **pad, pady=(4, 6))
        for key, label in LEVELS:
            v = res.get("levels", {}).get(key)
            if v:
                cell = tk.Frame(row, bg=C["pill"], padx=10, pady=4)
                cell.pack(side="left", padx=(0, 6))
                tk.Label(cell, text=label, bg=C["pill"], fg=C["muted"], font=(C["font"], 9)).pack()
                tk.Label(cell, text=v, bg=C["pill"], fg=C["price"], font=(C["font"], 12, "bold")).pack()
        info = "\n".join(i18n.tr(l) for l in res["text"].splitlines()
                         if l.strip() and not l.startswith("Zmienne staty") and not l.startswith("  "))
        if info:
            t2 = tk.Text(win, width=56, height=min(8, info.count("\n") + 2), bg=C["bg"], fg=C["muted"],
                         font=(C["font"], 10), relief="flat", highlightthickness=0, wrap="word")
            t2.insert("1.0", info)
            t2.config(state="disabled")
            t2.pack(anchor="w", **pad, fill="x")

        # inne pasujace
        if res.get("others"):
            tk.Label(win, text="INNE PASUJACE", bg=C["bg"], fg=C["muted"], font=(C["font"], 9, "bold")).pack(
                anchor="w", **pad, pady=(10, 2))
            box = tk.Frame(win, bg=C["bg"])
            box.pack(anchor="w", **pad, pady=(0, 6))
            for i, name in enumerate(res["others"]):
                tk.Button(box, text=name, bg=C["pill"], fg=C["pill_fg"], activebackground=C["line"],
                          activeforeground=C["title"], relief="flat", font=(C["font"], 9, "bold"), padx=8, pady=3,
                          cursor="hand2", command=lambda n=name: self.quick_open(n, win)).grid(
                    row=i // 3, column=i % 3, sticky="w", padx=(0, 6), pady=3)

        bottom = tk.Frame(win, bg=C["bg"])
        bottom.pack(fill="x", **pad, pady=(8, 14))
        for text, cmd in (("Kopiuj", lambda: (self.clipboard_clear(), self.clipboard_append(
                f"{res['title']}\n{res['text']}"))), ("Zamknij", win.destroy)):
            tk.Button(bottom, text=text, command=cmd, bg=C["button"], fg="#1f1f1f", relief="flat",
                      font=(C["font"], 10, "bold"), padx=14, pady=4, cursor="hand2",
                      activebackground=C["price"]).pack(side="right" if text == "Zamknij" else "left")

    def quick_open(self, name, win=None):
        """Wycena innego przedmiotu z listy 'inne pasujace'."""
        if win is not None:
            win.destroy()
        self.quick_var.set(name)
        self.quick_check()

    def sync_sold(self):
        def job():
            print("Sprawdzam oferty na Traderie (sprzedane, do odnowienia)...\n")
            try:
                sold, state, imported = traderie_sync.sync(FOLDER)
            except Exception as e:
                print(friendly_error("sprawdzanie ofert", e))
                return
            self.q.put(("state", state))
            if imported:
                print(f"   zaimportowano oferty wystawione poza skryptem: {', '.join(imported)}\n")
                self.q.put(("reload",))
            if sold:
                self.q.put(("sold", sold))
            else:
                print("   brak nowych sprzedanych\n")
            ready = sum(1 for v in state.values() if v["relist"])
            offers = sum(v["offers"] for v in state.values())
            print(f"   aktywnych ofert: {len(state)}, gotowych do odnowienia: {ready}, ofert kupna: {offers}\n")
        self.run_bg(job)

    def toggle_notify(self):
        if self.notify_var.get():
            if not tm.load_auth():
                messagebox.showerror("Powiadomienia", f"Brak lub niepoprawny plik {tm.AUTH_FILE}.")
                self.notify_var.set(False)
                return
            self.notify_stop = threading.Event()
            threading.Thread(target=self._notify_loop, args=(self.notify_stop,), daemon=True).start()
            self.notify_lbl.config(text="sprawdzam...")
        else:
            if getattr(self, "notify_stop", None):
                self.notify_stop.set()
            self.notify_lbl.config(text="")
            self.title("D2R -> Traderie")

    def _notify_loop(self, stop):
        while not stop.is_set():
            try:
                self.q.put(("notif", traderie_notify.fetch_new()))
            except Exception as e:
                self.q.put(("log", friendly_error("powiadomienia", e)))
            try:
                sold, state, imported = traderie_sync.sync(FOLDER)
                self.q.put(("state", state))
                if imported:
                    self.q.put(("log", f"Zaimportowano z Traderie: {', '.join(imported)}\n"))
                    self.q.put(("reload",))
                if sold:
                    self.q.put(("sold", sold))
            except Exception as e:
                self.q.put(("log", friendly_error("sprawdzanie ofert", e)))
            stop.wait(NOTIFY_EVERY)

    # ================= reczny wycinek =================
    def fix_crop(self):
        iid = self.current()
        if not iid:
            return
        it = self.items[iid]
        if it["status"] == "posted":
            messagebox.showinfo("Wycinek", "Ten przedmiot jest juz wystawiony. Jesli oferta jest bledna, usun ja "
                                           "na Traderie i usun pliki .json i .listing.json tego screena.")
            return
        stem = self.stem_of(it)
        png = next((p for p in FOLDER.glob(stem + ".*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")), None)
        if not png:
            messagebox.showerror("Wycinek", f"Nie znaleziono screena {stem}.png")
            return
        ocr_file = FOLDER / f"{stem}.json"
        box = json.loads(ocr_file.read_text(encoding="utf-8")).get("tooltip_box") if ocr_file.exists() else None
        CropDialog(self, png, box, lambda b: self.reread(png, b))

    def reread(self, png: Path, box):
        def job():
            import d2_ocr
            if not d2_ocr.check_gpu():
                self.q.put(("error", "Model nie miesci sie na karcie graficznej - zamknij gre i sprobuj ponownie."))
                return
            result = d2_ocr.read_tooltip(png, manual_box=box)
            png.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            res = tm.map_item(result)
            (FOLDER / f"{png.stem}.listing.json").write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                                             encoding="utf-8")
            print("   odczytano: " + " | ".join(result["lines"][:4]) + " ...\n")
            if res.get("warnings"):
                print("   uwagi: " + "; ".join(res["warnings"]) + "\n")
            d2_ocr.unload_model()
            self.q.put(("reload",))
        self.run_bg(job)

    # ================= krok 3: wystawianie =================
    def post_selected(self):
        if self.editor:
            self.focus_set()   # zatwierdz edytowana komorke
            self.update()
        self.commit_side_price()
        if self.price_msg.cget("text"):
            messagebox.showwarning("Cena", "Popraw najpierw cene zaznaczona na czerwono.")
            return
        plan = []
        for iid in self.order:
            it = self.items[iid]
            if not (it["selected"] and it["status"] in ("ready", "dup")):
                continue
            try:
                price, make_offer = tp.parse_price(it["price"])
            except ValueError as e:
                messagebox.showwarning("Cena", f"{it['lst']['name']}: {e}")
                return
            plan.append((iid, it, price, make_offer))
        if not plan:
            messagebox.showinfo("Wystawianie", "Nic nie jest zaznaczone. Ustaw ceny przedmiotom, ktore chcesz wystawic.")
            return
        mins = round((len(plan) - 1) * sum(tp.DELAY) / 2 / 60) or 1
        lines = "\n".join(f"{it['lst']['name']}  -  {it['price']}" for _, it, _, _ in plan[:25])
        if not messagebox.askyesno("Wystawic?", f"{len(plan)} przedmiotow, potrwa ok. {mins} min:\n\n{lines}"):
            return
        auth = tm.load_auth()
        if not auth:
            messagebox.showerror("Autoryzacja", f"Brak lub niepoprawny plik {tm.AUTH_FILE}.")
            return

        def job():
            registry = tp.load_registry(FOLDER)
            prices = json.loads(tp.PRICES_FILE.read_text(encoding="utf-8")) if tp.PRICES_FILE.exists() else {}
            for n, (iid, it, price, make_offer) in enumerate(plan, 1):
                if n > 1:
                    wait = random.randint(*tp.DELAY)
                    print(f"   ... {wait} s\n")
                    if self.stop_event.wait(wait):
                        print("Zatrzymano - reszta zostaje z zapamietanymi cenami.\n")
                        return
                if self.stop_event.is_set():
                    return
                lst, f = it["lst"], it["file"]
                item = tm.get_item(lst["name"])
                it["status"] = "sending"
                self.q.put(("row", iid))
                try:
                    status, body = tp.post(tp.build_payload(lst, item, price, make_offer), auth)
                    resp = json.loads(body)
                except Exception as e:
                    it["status"] = "error"
                    self.q.put(("row", iid))
                    self.q.put(("error", f"{lst['name']}: {e}\n\nWystawianie przerwane (wygasla sesja? captcha?)."))
                    return
                if not resp.get("success") or not resp.get("listing"):
                    it["status"] = "error"
                    self.q.put(("row", iid))
                    self.q.put(("error", f"{lst['name']}: nieoczekiwana odpowiedz Traderie:\n{body[:300]}"))
                    return
                lst["posted"] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "price": it["price"],
                                 "listing_id": resp["listing"]}
                lst.pop("planned_price", None)
                f.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
                registry[tp.fingerprint(lst)] = {"name": lst["name"], **lst["posted"], "source": f.name,
                                                 "stats": tp.describe(lst, item)[1]}
                tp.save_registry(registry)
                prices[lst["slug"]] = it["price"]
                tp.PRICES_FILE.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
                it["status"], it["selected"] = "posted", False
                self.q.put(("row", iid))
                print(f"[{n}/{len(plan)}] {lst['name']}: wystawiono za {it['price']}\n")
            print("Wystawianie zakonczone.\n")
        self.run_bg(job)


class SettingsDialog(tk.Toplevel):
    """Ustawienia: konto Traderie (ID, token) i domyslne parametry ofert."""

    def __init__(self, master):
        super().__init__(master, bg=CARD["bg"])
        C = CARD
        self.C, self.app = C, master
        self.title("Ustawienia")
        f = C["font"]
        cur = app_config.current()
        self.vars = {}
        hdr = dict(bg=C["bg"], fg=C["muted"], font=(f, 9, "bold"))
        lab = dict(bg=C["bg"], fg=C["text"], font=(f, 10))
        grid = tk.Frame(self, bg=C["bg"])
        grid.pack(fill="x", padx=18, pady=(14, 4))

        tk.Label(grid, text="KONTO TRADERIE", **hdr).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        tk.Label(grid, text="ID konta (seller):", **lab).grid(row=1, column=0, sticky="w", pady=3)
        self.vars["seller_id"] = tk.StringVar(value=cur["seller_id"])
        self.entry(grid, self.vars["seller_id"], 22).grid(row=1, column=1, sticky="w", pady=3)
        tk.Label(grid, text="Token (naglowek Authorization):", **lab).grid(row=2, column=0, sticky="w", pady=3)
        self.vars["token"] = tk.StringVar(value=cur["token"])
        self.tok = self.entry(grid, self.vars["token"], 46, show="*")
        self.tok.grid(row=2, column=1, sticky="w", pady=3)
        self.show = tk.BooleanVar(value=False)
        tk.Checkbutton(grid, text="pokaz", variable=self.show, bg=C["bg"], fg=C["text"], selectcolor=C["pill"],
                       activebackground=C["bg"], activeforeground=C["title"], font=(f, 9),
                       command=lambda: self.tok.config(show="" if self.show.get() else "*")).grid(
            row=2, column=2, sticky="w", padx=6)
        tk.Label(grid, text="Wklej z DevTools (widok Nieprzetworzone) cala linie Authorization albo sam token.",
                 bg=C["bg"], fg=C["muted"], font=(f, 9)).grid(row=3, column=0, columnspan=3, sticky="w")
        self.tok_info = tk.Label(grid, text="", bg=C["bg"], fg=C["price"], font=(f, 9, "bold"))
        self.tok_info.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self.vars["token"].trace_add("write", lambda *a: self.describe_token())

        tk.Label(grid, text="DOMYSLNE USTAWIENIA OFERT", **hdr).grid(row=5, column=0, columnspan=3, sticky="w",
                                                                    pady=(14, 4))
        labels = {"platform": "Platforma:", "mode": "Tryb:", "ladder": "Ladder:", "game_version": "Wersja gry:"}
        for i, (key, text) in enumerate(labels.items()):
            tk.Label(grid, text=text, **lab).grid(row=6 + i, column=0, sticky="w", pady=3)
            self.vars[key] = tk.StringVar(value=cur[key])
            ttk.Combobox(grid, textvariable=self.vars[key], values=app_config.OPTIONS[key], state="readonly",
                         width=24).grid(row=6 + i, column=1, sticky="w", pady=3)

        self.msg = tk.Label(self, text="", bg=C["bg"], fg=C["text"], font=(f, 10), wraplength=520, justify="left")
        self.msg.pack(anchor="w", padx=18, pady=(10, 0))
        bottom = tk.Frame(self, bg=C["bg"])
        bottom.pack(fill="x", padx=18, pady=14)
        self.btn(bottom, "Testuj polaczenie", self.test).pack(side="left")
        self.btn(bottom, "Zapisz", self.save, accent=True).pack(side="right")
        self.btn(bottom, "Anuluj", self.destroy).pack(side="right", padx=6)
        self.describe_token()
        self.transient(master)
        self.grab_set()

    def entry(self, parent, var, width, show=""):
        C = self.C
        return tk.Entry(parent, textvariable=var, width=width, show=show, bg=C["pill"], fg=C["title"],
                        insertbackground=C["title"], relief="flat", font=(C["font"], 10))

    def btn(self, parent, text, cmd, accent=False):
        C = self.C
        return tk.Button(parent, text=text, command=cmd, relief="flat", cursor="hand2", padx=10, pady=4,
                         font=(C["font"], 10, "bold"), bg=C["button"] if accent else C["pill"],
                         fg="#1f1f1f" if accent else C["pill_fg"], activebackground="#4a515e",
                         activeforeground=C["title"])

    def describe_token(self):
        tok = app_config.normalize_token(self.vars["token"].get())
        if not tok:
            self.tok_info.config(text="brak tokenu - wystawianie i sprawdzanie ofert nie beda dzialac", fg="#ff8080")
            return
        problem = app_config.token_problem(tok)
        if problem:
            self.tok_info.config(text=problem, fg="#ff8080")
            return
        info = app_config.token_info(tok)
        parts = []
        if info.get("expires"):
            exp = info["expires"]
            left = (exp - datetime.now()).total_seconds() / 86400
            parts.append(f"wazny do {exp:%Y-%m-%d %H:%M}" + (" (WYGASL)" if left < 0 else f" (jeszcze {left:.0f} dni)"
                                                              if left >= 1 else " (wygasa dzis)"))
        if info.get("user_id"):
            parts.append(f"ID w tokenie: {info['user_id']}")
            if not self.vars["seller_id"].get().strip():
                self.vars["seller_id"].set(info["user_id"])
        self.tok_info.config(text="token OK" + (" - " + ", ".join(parts) if parts else ""),
                             fg="#ff8080" if "WYGASL" in " ".join(parts) else self.C["price"])

    def values(self):
        return {k: v.get() for k, v in self.vars.items()}

    def save(self):
        tok = app_config.normalize_token(self.vars["token"].get())
        if tok and app_config.token_problem(tok):
            self.msg.config(text="Popraw token: " + app_config.token_problem(tok), fg="#ff8080")
            return
        if not self.vars["seller_id"].get().strip().isdigit():
            self.msg.config(text="ID konta powinno skladac sie z samych cyfr (z adresu listy ofert: seller=...).",
                            fg="#ff8080")
            return
        app_config.save(self.values())
        print("Zapisano ustawienia.\n")
        self.destroy()

    def test(self):
        tok = app_config.normalize_token(self.vars["token"].get())
        if not tok or app_config.token_problem(tok):
            self.msg.config(text="Najpierw wklej poprawny token.", fg="#ff8080")
            return
        old = (traderie_sync.SELLER_ID, dict(tm.load_auth()))
        self.msg.config(text="sprawdzam...", fg=self.C["muted"])

        def job():
            traderie_sync.SELLER_ID = self.vars["seller_id"].get().strip()
            tm._AUTH = {"Authorization": tok}
            ok, text = app_config.test_connection()
            traderie_sync.SELLER_ID, tm._AUTH = old[0], old[1]     # test nie zmienia ustawien
            self.after(0, lambda: self.msg.config(text=text, fg=self.C["price"] if ok else "#ff8080"))
        threading.Thread(target=job, daemon=True).start()


class PriceDialog(tk.Toplevel):
    """Ukladanie ceny z dowolnych przedmiotow: wyszukiwarka + szybkie przyciski + opcje 'ALBO'."""
    RUNES = ["Lem", "Pul", "Um", "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber", "Jah", "Cham", "Zod"]
    KEYS = ["Key of Terror", "Key of Hate", "Key of Destruction"]

    def __init__(self, master, item_name: str, current: str, on_ok):
        super().__init__(master, bg=CARD["bg"])
        C = CARD
        self.C, self.on_ok = C, on_ok
        self.title(f"Cena: {item_name}")
        self.groups = self.parse(current)          # [[(ilosc, nazwa), ...], ...] - grupy = opcje ALBO
        self.active = 0
        self.offer = tk.BooleanVar(value=(current or "").strip().lower() == "offer")
        self.q = queue.Queue()
        self._search_job = None
        f = C["font"]
        lbl = dict(bg=C["bg"], fg=C["muted"], font=(f, 9, "bold"))

        tk.Label(self, text=item_name, bg=C["bg"], fg=C["title"], font=(f, 14, "bold")).pack(
            anchor="w", padx=16, pady=(12, 6))

        # --- wyszukiwarka ---
        tk.Label(self, text="SZUKAJ PRZEDMIOTU (np. terror, ist, essence, perfect)", **lbl).pack(anchor="w", padx=16)
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="x", padx=16, pady=(2, 0))
        self.search_var = tk.StringVar()
        ent = tk.Entry(row, textvariable=self.search_var, bg=C["pill"], fg=C["title"], insertbackground=C["title"],
                       relief="flat", font=(f, 11), width=34)
        ent.pack(side="left", ipady=4)
        ent.bind("<KeyRelease>", self.on_type)
        ent.bind("<Return>", lambda e: self.add_selected())
        tk.Label(row, text="  ilosc:", bg=C["bg"], fg=C["text"], font=(f, 10)).pack(side="left")
        self.qty = tk.Spinbox(row, from_=1, to=999, width=5, bg=C["pill"], fg=C["title"], relief="flat",
                              buttonbackground=C["pill"], font=(f, 11), insertbackground=C["title"])
        self.qty.pack(side="left", padx=4, ipady=3)
        self.btn(row, "Dodaj", self.add_selected, accent=True).pack(side="left", padx=4)
        self.results = tk.Listbox(self, height=6, bg=C["pill"], fg=C["text"], selectbackground="#4a6fa5",
                                  relief="flat", font=(f, 10), highlightthickness=0, activestyle="none")
        self.results.pack(fill="x", padx=16, pady=(4, 8))
        self.results.bind("<Double-1>", lambda e: self.add_selected())

        # --- szybkie przyciski ---
        tk.Label(self, text="SZYBKO", **lbl).pack(anchor="w", padx=16)
        quick = tk.Frame(self, bg=C["bg"])
        quick.pack(anchor="w", padx=16, pady=(2, 4))
        for i, r in enumerate(self.RUNES):
            self.btn(quick, r, lambda n=r: self.add(n + " Rune")).grid(row=i // 7, column=i % 7, padx=2, pady=2,
                                                                         sticky="we")
        quick2 = tk.Frame(self, bg=C["bg"])
        quick2.pack(anchor="w", padx=16, pady=(0, 8))
        self.btn(quick2, "Perfect Amethyst", lambda: self.add("Perfect Amethyst")).pack(side="left", padx=2)
        for k in self.KEYS:
            self.btn(quick2, k.replace("Key of ", "Klucz "), lambda n=k: self.add(n)).pack(side="left", padx=2)
        self.btn(quick2, "Dowolne klucze", self.any_keys).pack(side="left", padx=(10, 2))

        # --- ulozona cena ---
        tk.Label(self, text="CENA (opcje ALBO - kupujacy wybiera jedna)", **lbl).pack(anchor="w", padx=16)
        self.box = tk.Frame(self, bg=C["bg"])
        self.box.pack(fill="x", padx=16, pady=(2, 4))
        row2 = tk.Frame(self, bg=C["bg"])
        row2.pack(fill="x", padx=16, pady=(0, 6))
        self.btn(row2, "+ Dodaj opcje ALBO", self.new_group).pack(side="left")
        self.btn(row2, "Wyczysc", self.clear).pack(side="left", padx=6)
        tk.Checkbutton(row2, text="Bez ceny - czekam na oferty", variable=self.offer, command=self.refresh,
                       bg=C["bg"], fg=C["text"], selectcolor=C["pill"], activebackground=C["bg"],
                       activeforeground=C["title"], font=(f, 10)).pack(side="left", padx=10)
        self.preview = tk.Label(self, text="", bg=C["bg"], fg=C["price"], font=(f, 10, "bold"), wraplength=520,
                                justify="left")
        self.preview.pack(anchor="w", padx=16, pady=(4, 0))

        bottom = tk.Frame(self, bg=C["bg"])
        bottom.pack(fill="x", padx=16, pady=12)
        self.btn(bottom, "Zapisz", self.ok, accent=True).pack(side="right")
        self.btn(bottom, "Anuluj", self.destroy).pack(side="right", padx=6)
        self.refresh()
        self.transient(master)
        self.grab_set()
        ent.focus_set()
        self.after(100, self.poll)

    def btn(self, parent, text, cmd, accent=False):
        C = self.C
        return tk.Button(parent, text=text, command=cmd, relief="flat", cursor="hand2", padx=8, pady=3,
                         font=(C["font"], 9, "bold"), bg=C["button"] if accent else C["pill"],
                         fg="#1f1f1f" if accent else C["pill_fg"], activebackground="#4a515e",
                         activeforeground=C["title"])

    # ----- model ceny -----
    @staticmethod
    def parse(text: str):
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
                q = 1
                m = re.match(r"(\d+)\s+(.+)", part)
                if m:
                    q, part = int(m.group(1)), m.group(2)
                g.append((q, part))
            groups.append(g)
        return groups or [[]]

    @staticmethod
    def short(name: str) -> str:
        return tpr.short(name)

    @staticmethod
    def pretty(n: str) -> str:
        """'key of terror' -> 'Key of Terror', 'ist' -> 'Ist'."""
        small = {"of", "the", "and"}
        return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(n.split()))

    def text(self) -> str:
        if self.offer.get():
            return "offer"
        return " | ".join("+".join(f"{q} {n}" if q > 1 else n for q, n in g) for g in self.groups if g)

    def refresh(self):
        C = self.C
        for w in self.box.winfo_children():
            w.destroy()
        for gi, g in enumerate(self.groups):
            if gi:
                tk.Label(self.box, text="ALBO", bg=C["bg"], fg=C["muted"], font=(C["font"], 9, "bold")).pack(
                    anchor="w", pady=(2, 0))
            fr = tk.Frame(self.box, bg="#3a4a63" if gi == self.active else C["pill"], padx=8, pady=4, cursor="hand2")
            fr.pack(fill="x", pady=2)
            fr.bind("<Button-1>", lambda e, i=gi: self.set_active(i))
            if not g:
                tk.Label(fr, text="(pusta - dodaj przedmiot)", bg=fr["bg"], fg=C["muted"],
                         font=(C["font"], 10)).pack(side="left")
            for ii, (q, n) in enumerate(g):
                cell = tk.Frame(fr, bg=fr["bg"])
                cell.pack(side="left", padx=(0, 10))
                tk.Label(cell, text=f"{q} x {self.pretty(n)}", bg=fr["bg"], fg=C["title"], font=(C["font"], 10, "bold")).pack(
                    side="left")
                tk.Button(cell, text="x", command=lambda a=gi, b=ii: self.remove(a, b), relief="flat",
                          bg=fr["bg"], fg="#ff8080", activebackground=fr["bg"], font=(C["font"], 9, "bold"),
                          padx=2, pady=0, cursor="hand2").pack(side="left")
        t = self.text()
        self.preview.config(text=("Zapisze jako: " + t) if t else "Zapisze jako: (bez ceny - przedmiot nie bedzie wystawiony)")

    def set_active(self, i):
        self.active = i
        self.refresh()

    def add(self, name: str, qty: int = None):
        if qty is None:
            try:
                qty = max(1, int(self.qty.get()))
            except ValueError:
                qty = 1
        self.offer.set(False)
        key = self.short(name)
        g = self.groups[self.active]
        for i, (q, n) in enumerate(g):
            if n == key:
                g[i] = (q + qty, n)
                break
        else:
            g.append((qty, key))
        threading.Thread(target=lambda: tm.get_item(name), daemon=True).start()   # definicja do cache z wyprzedzeniem
        self.refresh()

    def remove(self, gi, ii):
        del self.groups[gi][ii]
        if not self.groups[gi] and len(self.groups) > 1:
            del self.groups[gi]
            self.active = min(self.active, len(self.groups) - 1)
        self.refresh()

    def new_group(self):
        if self.groups[-1]:
            self.groups.append([])
        self.active = len(self.groups) - 1
        self.refresh()

    def clear(self):
        self.groups, self.active = [[]], 0
        self.offer.set(False)
        self.refresh()

    def any_keys(self):
        """'Dowolne klucze': N x Terror ALBO N x Hate ALBO N x Destruction."""
        try:
            qty = max(1, int(self.qty.get()))
        except ValueError:
            qty = 1
        self.offer.set(False)
        if self.groups == [[]]:
            self.groups = []
        for k in self.KEYS:
            self.groups.append([(qty, self.short(k))])
            threading.Thread(target=lambda n=k: tm.get_item(n), daemon=True).start()
        self.active = len(self.groups) - 1
        self.refresh()

    # ----- wyszukiwarka -----
    def on_type(self, e=None):
        if self._search_job:
            self.after_cancel(self._search_job)
        q = self.search_var.get().strip()
        if len(q) < 2:
            self.results.delete(0, "end")
            return
        self._search_job = self.after(350, lambda: threading.Thread(target=self._search, args=(q,),
                                                                    daemon=True).start())

    def _search(self, q):
        try:
            self.q.put(("res", q, tp.search_items(q, 25)))
        except Exception as ex:
            self.q.put(("res", q, [f"(blad wyszukiwania: {ex})"]))

    def poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, q, names = self.q.get_nowait()
                if q == self.search_var.get().strip():
                    self.results.delete(0, "end")
                    for n in names or ["(nic nie znaleziono)"]:
                        self.results.insert("end", n)
                    if names:
                        self.results.selection_set(0)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def add_selected(self):
        sel = self.results.curselection()
        if not sel:
            return
        name = self.results.get(sel[0])
        if name.startswith("("):
            return
        self.add(name)

    def ok(self):
        self.on_ok(self.text())
        self.destroy()


class CropDialog(tk.Toplevel):
    """Recznie zaznaczenie tooltipa na screenie: przeciagnij mysza prostokat."""
    MAX_W, MAX_H = 1100, 760

    def __init__(self, master, png: Path, box, on_ok):
        super().__init__(master)
        self.title(f"Zaznacz tooltip - {png.name}")
        self.on_ok = on_ok
        self.img = Image.open(png).convert("RGB")
        self.scale = min(1.0, self.MAX_W / self.img.width, self.MAX_H / self.img.height)
        shown = self.img.resize((int(self.img.width * self.scale), int(self.img.height * self.scale)))
        self.tkimg = ImageTk.PhotoImage(shown)
        ttk.Label(self, text="Przeciagnij mysza prostokat obejmujacy caly tooltip (z zapasem po bokach). "
                             "Czerwona ramka = obecny wycinek.").pack(anchor="w", padx=6, pady=4)
        self.canvas = tk.Canvas(self, width=shown.width, height=shown.height, cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack(padx=6)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tkimg)
        if box:
            self.canvas.create_rectangle(*[v * self.scale for v in box], outline="red", width=2, dash=(4, 2))
        self.rect, self.start, self.box = None, None, None
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=6)
        self.btn_ok = ttk.Button(row, text="Odczytaj ponownie", command=self.ok, state="disabled")
        self.btn_ok.pack(side="right")
        ttk.Button(row, text="Anuluj", command=self.destroy).pack(side="right", padx=6)
        self.transient(master)
        self.grab_set()

    def press(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00ff66", width=2)

    def drag(self, e):
        if self.start:
            self.canvas.coords(self.rect, *self.start, e.x, e.y)

    def release(self, e):
        if not self.start:
            return
        x1, x2 = sorted((self.start[0], e.x))
        y1, y2 = sorted((self.start[1], e.y))
        if x2 - x1 < 20 or y2 - y1 < 20:
            return
        s = self.scale
        self.box = (max(0, int(x1 / s)), max(0, int(y1 / s)),
                    min(self.img.width, int(x2 / s)), min(self.img.height, int(y2 / s)))
        self.btn_ok.config(state="normal")

    def ok(self):
        if self.box:
            self.on_ok(self.box)
        self.destroy()


if __name__ == "__main__":
    try:
        app = App()
    except Exception:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        startup_error(traceback.format_exc())
    app.mainloop()
