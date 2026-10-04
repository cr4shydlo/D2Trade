"""
game_extract.py - buduje lokalna baze przedmiotow z plikow Diablo II: Resurrected.

Po co: bez tokenu Traderie program nie ma skad wziac definicji przedmiotow (jakie staty
moze miec dany slot, jakie sa zakresy unikatow, jak wyglada ikona). Te same dane leza
w plikach gry na dysku uzytkownika - wystarczy je raz przeczytac.

    py -3.11 game_extract.py "C:\\Program Files (x86)\\Diablo II Resurrected"
    py -3.11 game_extract.py                 # szuka gry w typowych miejscach

Wynik (katalog game_data/, poza repozytorium - kazdy robi go sobie sam):
    meta.json      skad i kiedy, liczniki
    props.json     wspolna pula wlasciwosci (szablony linii tooltipa)
    items.json     przedmioty: baza/unikat/set/runeword, staty z min-max, ikona, tagi
    icons/*.png    ikony ekwipunku (HD .sprite -> PNG)

Program tylko czyta pliki gry. Nie modyfikuje instalacji, nie uruchamia gry i nie
rozsyla tego, co wyciagnie - baza zostaje na dysku uzytkownika.
"""
import json
import re
import sys
import time
from pathlib import Path

import game_casc as gc
import paths

KATALOG = paths.DATA / "game_data"      # obok danych roboczych, nie w repozytorium
IKONY = KATALOG / "icons"

TABELE = ("armor", "weapons", "misc", "uniqueitems", "setitems", "runes", "properties",
          "itemstatcost", "itemtypes", "charstats", "skills", "skilldesc",
          "magicprefix", "magicsuffix", "automagic")
STRINGI = "data/local/lng/strings"
# Teksty, z ktorych skladamy opisy. Nazwy przedmiotow sa w osobnych plikach niz opisy statow,
# a nazwa z tabeli (kolumna index) to klucz wewnetrzny - gra pokazuje tekst z tych plikow.
PLIKI_NAZW = ("item-names", "item-runes", "item-gems")
PLIKI_OPISOW = ("item-modifiers",)
PLIKI_UMIEJETNOSCI = ("skills",)
EXCEL = "data/global/excel"
HD_MAPY = "data/hd/items"
HD_IKONY = "data/hd/global/ui/items"
BAZY = ("armor", "weapons", "misc")
WARIANTY = ("normal", "uber", "ultra")     # kolejnosc szukania grafiki: normalny, wyjatkowy, elitarny

# Trzy identyfikatory wlasciwosci Traderie, ktore kod traktuje specjalnie (obrona calkowita,
# obrona dodana, wymagany poziom). Nadajemy je takze lokalnie, zeby ta sama logika dzialala
# w trybie lokalnym. Pozostale wlasciwosci dostaja numery ujemne - nigdy nie pomyli sie ich
# z prawdziwymi, a wystawienie takiego listingu jest zablokowane w traderie_post.build_payload().
PID_OBRONA = 1855        # "Defense" - obrona calkowita z tooltipa
PID_OBRONA_DODANA = 399  # "+{{value}} Defense"
PID_POZIOM = 796         # "Required Level {{value}}"

# Tag "Item Type" w slowniku Traderie, nie gry: rare_eval.slot_of() dopasowuje tagi, a gra
# nazywa Grand Charma "Large Charm" - gdyby tag poszedl wprost z itemtypes.txt, skiller
# zostalby wyceniony jak Large Charm. Kolejnosc = od najbardziej szczegolowego typu.
TAGI_TYPU = (
    ("circ", "Circlet"), ("helm", "Helm"), ("tors", "Armor"), ("shie", "Shield"), ("shld", "Shield"),
    ("glov", "Gloves"), ("boot", "Boots"), ("belt", "Belt"), ("ring", "Ring"), ("amul", "Amulet"),
    ("jewl", "Jewel"), ("scha", "Small Charm"), ("mcha", "Large Charm"), ("lcha", "Grand Charm"),
    ("orb", "Orb"), ("weap", "Weapon"),
)
# typy z misc.txt, ktore na Traderie sa osobnymi kategoriami, a nie "biala baza"
TYP_PO_KATEGORII = {"rune": "runes", "gem": "gems"}

# Wlasciwosci wspolne dla wszystkich baz: linie, ktore w tooltipie nie pochodza z afiksu.
WSPOLNE = [
    (PID_OBRONA, "Defense", "number"),
    (PID_POZIOM, "Required Level {{value}}", "number"),
    (None, "Socketed ({{value}})", "number"),     # tak wyglada ta linia w tooltipie gry
    (None, "Ethereal", "bool"),
    (None, "Unidentified", "bool"),
]
# Pola wymagane przez listing (te same, co w definicjach Traderie).
USTAWIENIA = [
    ("Platform", ["PC", "playstation", "xbox", "switch"]),
    ("Mode", ["softcore", "hardcore"]),
    ("Ladder", ["Ladder", "Non Ladder"]),
    ("Game version", ["classic (base game)", "lord of destruction", "reign of the warlock"]),
]
RZADKOSC = ("Rarity", ["rare", "magic"])

ZNACZNIKI = re.compile(r"%%|%\+d|%d|%s|%\+?[0-9]")
STAT_KLASOWY = "item_addclassskills"     # '+X do umiejetnosci klasy' - ktorej, mowi kolumna val
STAT_TRUCIZNA = "poisonmindam"           # obrazenia od trucizny to w tooltipie jedna linia
# Wlasciwosci, ktore zmieniaja kilka statow, ale w tooltipie sa jedna linia. Wartosci to klucze
# tekstow gry, zeby nie wpisywac angielszczyzny do kodu - przy modzie albo nowej wersji gry
# wezmie sie to, co naprawde pokazuje gra.
ZBIORCZE = {"res-all": "strModAllResistances", "all-stats": "Moditem2allattrib"}
TRUCIZNA = ("strModPoisonDamage", "strModPoisonDamageRange")
PER_POZIOM = "ModStre9c"                 # '(Based on Character Level)'
MODY_AFIKSU = (1, 2, 3)
# nazwy kolumn z wlasciwosciami: (kod, parametr, min, max)
KOL_PRZEDMIOT = ("prop%d", "par%d", "min%d", "max%d")
KOL_RUNEWORD = ("T1Code%d", "T1Param%d", "T1Min%d", "T1Max%d")


# ---------------- teksty statow ----------------
def na_szablon(tekst: str, param=None):
    """Format opisu z gry -> szablon w stylu Traderie.

    '%+d%% Enhanced Defense' -> '+{{value}}% Enhanced Defense'
    '%+d to %s' + param 'Teleport' -> '+{{value}} to Teleport'
    Zwraca (szablon, typ) albo (None, None), gdy brakuje wartosci dla '%s'.
    """
    if not tekst:
        return None, None
    licznik = [0]
    brak = [False]

    def zamien(m):
        znak = m.group(0)
        if znak == "%%":
            return "%"
        if znak == "%s":
            if param is None:
                brak[0] = True
                return ""
            return str(param)
        licznik[0] += 1
        nazwa = "value" if licznik[0] == 1 else "v%d" % licznik[0]
        return ("+{{%s}}" if znak.startswith("%+") else "{{%s}}") % nazwa

    szablon = re.sub(r"\s+", " ", ZNACZNIKI.sub(zamien, tekst)).strip()
    if brak[0] or not szablon:
        return None, None
    return szablon, ("number" if "{{" in szablon else "bool")


def wczytaj_teksty(z, pliki) -> dict:
    """Teksty gry: klucz -> tekst angielski. Pierwszy plik z lista wygrywa przy powtorce."""
    out = {}
    for nazwa in pliki:
        try:
            dane = json.loads(z.czytaj("%s/%s.json" % (STRINGI, nazwa)).decode("utf-8-sig", "replace"))
        except Exception:
            continue
        for w in dane if isinstance(dane, list) else []:
            if isinstance(w, dict) and w.get("Key") and w.get("enUS"):
                out.setdefault(w["Key"], w["enUS"])
    return out


def opisy_statow(isc: list, opisy: dict) -> dict:
    """stat z itemstatcost -> tekst opisu z plikow jezykowych."""
    out = {}
    for r in isc:
        stat = (r.get("Stat") or "").strip()
        if not stat:
            continue
        out[stat] = opisy.get((r.get("descstrpos") or "").strip())
    return out


def wlasciwosci_gry(properties: list, opis_statu: dict) -> dict:
    """kod wlasciwosci ('ac%') -> {'opisy': [(stat, tekst, val)], 'tooltip': ...}."""
    out = {}
    for r in properties:
        kod = (r.get("code") or "").strip()
        if not kod:
            continue
        opisy = []
        for i in range(1, 8):
            stat = (r.get("stat%d" % i) or "").strip()
            if stat and opis_statu.get(stat):
                opisy.append((stat, opis_statu[stat], gc.liczba(r.get("val%d" % i), None)))
        out[kod] = {"opisy": opisy, "tooltip": (r.get("*Tooltip") or "").strip() or None}
    return out


def klasy_postaci(charstats: list, tekst) -> list:
    """Klasy w kolejnosci numeracji gry: nazwa, opis '+X do umiejetnosci klasy', '(X Only)'.

    Wiersz 'Expansion' w charstats to separator, nie klasa - gdyby wszedl do listy,
    wszystkie klasy po nim mialyby numer o jeden za duzy.
    """
    out = []
    for r in charstats:
        nazwa = (r.get("class") or "").strip()
        if not nazwa or nazwa.lower().startswith("expansion"):
            continue
        tylko = (r.get("StrClassOnly") or "").strip()
        out.append({
            "name": nazwa,
            "allskills": tekst((r.get("StrAllSkills") or "").strip()),
            "only": tekst(tylko),
            # charstats nie ma kolumny z kodem klasy, ale klucz tekstu go zawiera:
            # 'SorOnly' -> 'sor', czyli dokladnie to, co skills.txt ma w charclass
            "kod": tylko[:3].lower(),
        })
    return out


def nazwy_umiejetnosci(skills: list, skilldesc: list, tekst_um) -> dict:
    """Numer umiejetnosci -> {'name', 'class'}. Numer to pozycja wiersza w skills.txt.

    Afiksy podaja umiejetnosc numerem ('charged' z param 106), a unikaty nazwa
    ('oskill' z param 'Teleport') - stad dwa klucze dla tego samego wpisu.
    """
    opis = {(r.get("skilldesc") or "").strip(): (r.get("str name") or "").strip() for r in skilldesc}
    out = {}
    for nr, r in enumerate(skills):
        wew = (r.get("skill") or "").strip()
        if not wew:
            continue
        klucz = opis.get((r.get("skilldesc") or "").strip())
        wpis = {"name": tekst_um(klucz) or wew, "kod_klasy": (r.get("charclass") or "").strip()}
        out[str(nr)] = wpis
        out[wew.lower()] = wpis
        out[wpis["name"].lower()] = wpis
    return out


def drzewka_umiejetnosci(charstats: list, opisy: dict) -> dict:
    """param wlasciwosci 'skilltab' -> {'text': nazwa drzewka, 'only': '(Klasa Only)'}.

    Sam stat ma opis pierwszego drzewka w grze, wiec bez parametru kazde '+1 do drzewka'
    nazywaloby sie tak samo. Param N odpowiada kluczowi StrSklTabItem{N+1}, a charstats
    mowi, ktora klasa ma ktore drzewko.
    """
    out = {}
    for r in charstats:
        klasa = (r.get("class") or "").strip()
        if not klasa or klasa.lower().startswith("expansion"):
            continue
        for i in (1, 2, 3):
            klucz = (r.get("StrSkillTab%d" % i) or "").strip()
            if not klucz.startswith("StrSklTabItem"):
                continue
            nr = gc.liczba(klucz[len("StrSklTabItem"):], None)
            if nr is None:
                continue
            out[str(nr - 1)] = {"class": klasa, "text": opisy.get(klucz),
                                "only": opisy.get((r.get("StrClassOnly") or "").strip())}
    return out


def umiejetnosc(param, kontekst: dict):
    """Parametr wlasciwosci -> (nazwa umiejetnosci, '(Klasa Only)' albo '').

    Afiksy podaja umiejetnosc numerem, unikaty i runewordy nazwa. Dopisek klasowy
    bierze sie z klasy, do ktorej umiejetnosc nalezy - umiejetnosci wspolne go nie maja.
    """
    wpis = kontekst["skille"].get(str(param).strip().lower())
    if not wpis:
        return None, ""
    klasa = next((k for k in kontekst["klasy"] if k["kod"] and k["kod"] == wpis["kod_klasy"]), None)
    return wpis["name"], ((klasa or {}).get("only") or "")


def teksty_wlasciwosci(kod: str, param, wl: dict, kontekst: dict) -> list:
    """Opisy (jeszcze w formacie gry) dla wlasciwosci - czasem jeden, czasem kilka."""
    wpis = wl.get(kod) or {}
    if kod in kontekst["zbiorcze"]:
        return [kontekst["zbiorcze"][kod]]             # jedna linia zamiast kilku statow
    staty = wpis.get("opisy") or []
    if any(s == STAT_TRUCIZNA for s, _, _ in staty) and kontekst["trucizna"]:
        # "+50 poison damage over 3 seconds" - jedna linia z trzech statow (min, max, czas)
        return list(kontekst["trucizna"])
    out = []
    for stat, tekst, val in staty:
        if stat == STAT_KLASOWY:
            # itemstatcost ma dla '+X do umiejetnosci klasy' opis tylko pierwszej klasy;
            # o ktora chodzi, mowi kolumna val w properties.txt
            klasa = kontekst["klasy"][val] if val is not None and val < len(kontekst["klasy"]) else None
            tekst = (klasa or {}).get("allskills") or tekst
        out.append(tekst)
    if not out and wpis.get("tooltip"):
        # '+#% Enhanced Damage' - zapis z kolumny *Tooltip, gdy stat nie ma wlasnego opisu
        out = [wpis["tooltip"].replace("#", "%d").replace("+%d", "%+d")]
    return out


def opisy_wlasciwosci(kod: str, param, wl: dict, kontekst: dict) -> list:
    """Szablony linii tooltipa dla wlasciwosci gry: [(szablon, typ)].

    Jedna wlasciwosc to czasem kilka linii (res-all zmienia cztery odpornosci), a czasem
    jedna zbiorcza - gra pisze wtedy "All Resistances +30", a nie cztery osobne linie.
    """
    if kod == "skilltab":
        d = kontekst["drzewka"].get(str(param)) if param is not None else None
        if not d or not d.get("text"):
            return []
        # tekst drzewka jest juz pelna linia ('%+d to Javelin and Spear Skills'),
        # dokladamy tylko dopisek klasowy
        szablon, typ = na_szablon(d["text"] + " " + (d["only"] or ""))
        return [(szablon, typ)] if szablon else []

    nazwa_um, tylko = umiejetnosc(param, kontekst) if param is not None else (None, "")
    teksty = teksty_wlasciwosci(kod, param, wl, kontekst)
    if kod.endswith("/lvl") and kontekst["per_poziom"]:
        # w tooltipie taki stat ma dopisek '(Based on Character Level)' i jest osobna
        # wlasciwoscia - bez dopisku zlalby sie ze zwyklym '+X do sily'
        teksty = ["%s %s" % (t, kontekst["per_poziom"]) for t in teksty]

    out = []
    for tekst in teksty:
        # '%+d to %s %s' = '+X do <umiejetnosc> (<Klasa> Only)': drugie %s to dopisek klasowy,
        # wiec wstawiamy go, zanim param wypelni pierwsze
        if tekst.count("%s") == 2 and nazwa_um:
            glowa, _, ogon = tekst.rpartition("%s")
            tekst = glowa + tylko + ogon
        szablon, typ = na_szablon(tekst, nazwa_um if nazwa_um else param)
        if szablon:
            out.append((szablon, typ))
    return out


# ---------------- pula wlasciwosci ----------------
class Pula:
    """Wspolna lista wlasciwosci: szablon -> numer. Ten sam stat na dwoch przedmiotach
    dostaje ten sam numer, wiec plik jest maly, a listingi porownywalne miedzy soba."""

    def __init__(self):
        self.po_szablonie = {}
        self.lista = []
        self.nastepny = -1

    def dodaj(self, szablon: str, typ: str, **extra) -> int:
        if not szablon:
            return None
        stary = self.po_szablonie.get(szablon)
        if stary is not None:
            return stary
        pid = extra.pop("pid", None)
        if pid is None:
            pid = self.nastepny
            self.nastepny -= 1
        wpis = {"property_id": pid, "id": pid, "property": szablon, "type": typ,
                "required": False, "options": None, "default_value": None,
                "min": None, "max": None, "format": None, "img": None,
                "affected_properties": None, "item_format": None}
        wpis.update(extra)
        self.po_szablonie[szablon] = pid
        self.lista.append(wpis)
        return pid


def przodkowie(itemtypes: list) -> dict:
    """kod typu -> zbior jego typow nadrzednych (z nim samym). Equiv1/Equiv2 to rodzic."""
    rodzic = {}
    for r in itemtypes:
        kod = (r.get("Code") or "").strip()
        if not kod:
            continue
        rodzic[kod] = [x for x in ((r.get("Equiv%d" % i) or "").strip() for i in (1, 2)) if x]
    out = {}

    def rozwin(kod, slad=()):
        if kod in slad:
            return set()
        wynik = {kod}
        for g in rodzic.get(kod, []):
            wynik |= rozwin(g, slad + (kod,))
        return wynik

    for kod in rodzic:
        out[kod] = rozwin(kod)
    return out


def tag_typu(typ: str, rodzina: dict):
    """Tag 'Item Type' dla typu bazy. Najbardziej szczegolowy z TAGI_TYPU."""
    rodzinka = rodzina.get(typ) or {typ}
    for kod, tag in TAGI_TYPU:
        if kod in rodzinka:
            return tag
    return None


# ---------------- opis przedmiotu ----------------
def linia_opisu(szablon: str, lo, hi) -> str:
    """Szablon + zakres -> linia opisu w formacie, ktory czyta traderie_map.parse_ranges().

    Zmienny stat musi byc w [color=...] z zakresem - tak wyglada opis na Traderie
    i tylko wtedy program wie, ze wartosc jest losowa i nalezy do listingu.
    """
    if lo is None and hi is None:
        return szablon.replace("{{value}}", "").replace("+ ", "+")
    if hi is None or lo == hi:
        return re.sub(r"\{\{\w+\}\}", str(lo), szablon)
    wstawka = "[color=Lime]%d-%d[/color]" % (lo, hi)
    return szablon.replace("{{value}}", wstawka, 1)


def opis_przedmiotu(linie: list, levelreq) -> str:
    out = list(linie)
    if levelreq:
        out.append("Req. Level: %d" % levelreq)
    return "\n".join(out)


# ---------------- skladanie bazy ----------------
def mapa_hd(z, nazwa: str) -> dict:
    """items.json / uniques.json / sets.json z katalogu hd - lista jednoelementowych slownikow."""
    sciezka = "%s/%s" % (HD_MAPY, nazwa)
    try:
        dane = json.loads(z.czytaj(sciezka).decode("utf-8-sig", "replace"))
    except Exception:
        return {}
    out = {}
    for wpis in dane if isinstance(dane, list) else []:
        if isinstance(wpis, dict):
            out.update(wpis)
    return out


def zapisz_ikony(z, assety: set) -> dict:
    """Konwertuje potrzebne ikony .sprite na PNG. Zwraca asset -> nazwa pliku."""
    IKONY.mkdir(parents=True, exist_ok=True)
    pliki = [n for n in z.lista(HD_IKONY, rek=True)
             if n.lower().endswith(".sprite") and ".lowend." not in n.lower()]
    po_koncowce = {}
    for n in pliki:
        czesci = n[len(HD_IKONY) + 1:-7].split("/")
        po_koncowce.setdefault("/".join(czesci[-2:]), n)
        po_koncowce.setdefault(czesci[-1], n)
    out, bledy = {}, 0
    for asset in sorted(a for a in assety if a):
        zrodlo = po_koncowce.get(asset) or po_koncowce.get(asset.split("/")[-1])
        if not zrodlo:
            continue
        nazwa = asset.replace("/", "_") + ".png"
        cel = IKONY / nazwa
        if not cel.exists():
            try:
                cel.write_bytes(gc.sprite_na_png(z.czytaj(zrodlo)))
            except Exception:
                bledy += 1
                continue
        out[asset] = nazwa
    if bledy:
        print("  ikon nie udalo sie przerobic: %d" % bledy)
    return out


def main(argv):
    sciezka = argv[1] if len(argv) > 1 else gc.zgadnij_gre()
    if not sciezka:
        print("Nie znalazlem gry w typowych miejscach. Podaj katalog, na przyklad:")
        print("    py -3.11 game_extract.py \"C:\\Program Files (x86)\\Diablo II Resurrected\"")
        print("Mozesz tez wskazac katalog z wypakowanym 'data' (np. z CascView).")
        return 2
    try:
        zrodlo = gc.otworz(sciezka)
    except gc.BrakZrodla as e:
        print("!!! %s" % e)
        return 2
    start = time.time()
    print("zrodlo: %s (%s)" % (sciezka, zrodlo.etykieta))

    with zrodlo as z:
        tab = {}
        for nazwa in TABELE:
            try:
                tab[nazwa] = gc.tabela(z.czytaj("%s/%s.txt" % (EXCEL, nazwa)))
            except Exception as e:
                print("!!! nie udalo sie wczytac tabeli %s: %s" % (nazwa, e))
                return 2
        print("tabele: " + ", ".join("%s %d" % (k, len(v)) for k, v in tab.items()))

        try:
            opisy = wczytaj_teksty(z, PLIKI_OPISOW)
            nazwy = wczytaj_teksty(z, PLIKI_NAZW)
            teksty_um = wczytaj_teksty(z, PLIKI_UMIEJETNOSCI)
        except Exception as e:
            print("!!! nie udalo sie wczytac tekstow z %s: %s" % (STRINGI, e))
            return 2
        if not opisy or not nazwy:
            print("!!! brak tekstow gry w %s - sprawdz, czy to na pewno katalog z D2R" % STRINGI)
            return 2

        opis_statu = opisy_statow(tab["itemstatcost"], opisy)
        wl = wlasciwosci_gry(tab["properties"], opis_statu)
        kontekst = {
            "drzewka": drzewka_umiejetnosci(tab["charstats"], opisy),
            "klasy": klasy_postaci(tab["charstats"], opisy.get),
            "skille": nazwy_umiejetnosci(tab["skills"], tab["skilldesc"], teksty_um.get),
            "zbiorcze": {k: opisy[v] for k, v in ZBIORCZE.items() if opisy.get(v)},
            "trucizna": [opisy[k] for k in TRUCIZNA if opisy.get(k)],
            "per_poziom": opisy.get(PER_POZIOM),
        }
        rodzina = przodkowie(tab["itemtypes"])
        print("teksty: opisy %d, nazwy %d | wlasciwosci %d | drzewka %d | klasy %d | umiejetnosci %d"
              % (len(opisy), len(nazwy), len(wl), len(kontekst["drzewka"]),
                 len(kontekst["klasy"]), len(tab["skills"])))

        pula = Pula()
        for pid, szablon, typ in WSPOLNE:
            pula.dodaj(szablon, typ, pid=pid)
        pid_obrona_dodana = pula.dodaj("+{{value}} Defense", "number", pid=PID_OBRONA_DODANA)
        wspolne_pid = [p["property_id"] for p in pula.lista]
        ustawienia_pid = [pula.dodaj(nazwa, "option", options=opcje, required=True)
                          for nazwa, opcje in USTAWIENIA]
        rzadkosc_pid = pula.dodaj(RZADKOSC[0], "option", options=RZADKOSC[1], required=True)

        # --- afiksy: to, co moze sie wylosowac na magic/rare ---
        for tabela in ("magicprefix", "magicsuffix", "automagic"):
            for r in tab[tabela]:
                if not (r.get("Name") or "").strip():
                    continue
                for i in MODY_AFIKSU:
                    kod = (r.get("mod%dcode" % i) or "").strip()
                    if not kod:
                        continue
                    par = (r.get("mod%dparam" % i) or "").strip() or None
                    for szablon, typ in opisy_wlasciwosci(kod, par, wl, kontekst):
                        pula.dodaj(szablon, typ)
        print("wlasciwosci po afiksach: %d" % len(pula.lista))

        # --- przedmioty ---
        hd_bazy = mapa_hd(z, "items.json")
        hd_uniq = mapa_hd(z, "uniques.json")
        hd_sets = mapa_hd(z, "sets.json")
        przedmioty, assety = [], set()

        def stale_props(r, kolumny, ile):
            """Wlasciwosci stale przedmiotu -> (lista pid, linie opisu).

            kolumny: nazwy kolumn z numerem, bo uniqueitems ma prop1/par1/min1/max1,
            a runes (runewordy) T1Code1/T1Param1/T1Min1/T1Max1.
            """
            kod_k, par_k, min_k, max_k = kolumny
            pids, linie = [], []
            for i in range(1, ile + 1):
                kod = (r.get(kod_k % i) or "").strip()
                if not kod:
                    continue
                par = (r.get(par_k % i) or "").strip() or None
                lo = gc.liczba(r.get(min_k % i), None)
                hi = gc.liczba(r.get(max_k % i), None)
                for szablon, typ in opisy_wlasciwosci(kod, par, wl, kontekst):
                    pid = pula.dodaj(szablon, typ)
                    if pid is None:
                        continue
                    if pid not in pids:
                        pids.append(pid)
                    linie.append(linia_opisu(szablon, lo, hi))
            return pids, linie

        def dodaj(kind, klucz, nazwa, typ, tag, asset, levelreq, pids, linie, **extra):
            """Dodaje przedmiot. 'klucz' to nazwa z tabeli gry - zapisujemy ja jako alias,
            bo opisy przedmiotow w sieci czesto uzywaja jej zamiast nazwy z gry."""
            assety.add(asset)
            alias = [klucz] if klucz and klucz != nazwa else []
            przedmioty.append(dict({
                "kind": kind, "name": nazwa, "slug": gc.slug(nazwa), "type": typ,
                "tags": [{"tag": tag, "category": "Item Type"}] if tag else [],
                "levelreq": levelreq, "asset": asset, "aliases": alias,
                "props": pids, "desc": opis_przedmiotu(linie, levelreq),
            }, **extra))

        kody_baz = {}
        for tabela in BAZY:
            for r in tab[tabela]:
                kod = (r.get("code") or "").strip()
                klucz = (r.get("name") or "").strip()
                # nazwa z kolumny to klucz wewnetrzny; gra pokazuje tekst z item-names,
                # a mody wlasnie tam zmieniaja nazwy przedmiotow
                nazwa = nazwy.get(kod) or klucz
                if not kod or not nazwa or nazwa.lower().startswith("expansion"):
                    continue
                kody_baz[kod] = r
                typ_gry = (r.get("type") or "").strip()
                rodzinka = rodzina.get(typ_gry) or {typ_gry}
                kategoria = next((v for k, v in TYP_PO_KATEGORII.items() if k in rodzinka), "base")
                pids = list(wspolne_pid) + list(ustawienia_pid)
                if kategoria == "base":
                    # biala baza moze sie trafic jako magic albo rare, wiec potrzebuje
                    # rzadkosci; staty dokladane sa wszystkim przedmiotom (patrz 'statowe')
                    pids += [rzadkosc_pid, pid_obrona_dodana]
                dodaj("base", klucz, nazwa, kategoria, tag_typu(typ_gry, rodzina),
                      (hd_bazy.get(kod) or {}).get("asset"),
                      gc.liczba(r.get("levelreq"), None), pids, [], base=kod, itype=typ_gry)

        def wariant(mapa, klucz, kod_bazy):
            """Wlasna grafika unikatu/setu, a gdy jej nie ma - grafika bazy."""
            wpis = mapa.get(klucz) or {}
            for w in WARIANTY:
                if wpis.get(w):
                    return wpis[w]
            return (hd_bazy.get(kod_bazy) or {}).get("asset")

        for r in tab["uniqueitems"]:
            idx = (r.get("index") or "").strip()
            kod = (r.get("code") or "").strip()
            # wiersze bez kodu bazy to naglowki sekcji w pliku gry ("Rings", "Elite Uniques")
            if not idx or not kod or idx.lower().startswith("expansion"):
                continue
            baza = kody_baz.get(kod) or {}
            pids, linie = stale_props(r, KOL_PRZEDMIOT, 12)
            lr = gc.liczba(r.get("lvl req"), None)
            dodaj("unique", idx, nazwy.get(idx) or idx, "uniques",
                  tag_typu((baza.get("type") or "").strip(), rodzina),
                  wariant(hd_uniq, gc.slug(idx), kod), lr,
                  list(wspolne_pid) + list(ustawienia_pid) + [pid_obrona_dodana] + pids,
                  linie, base=kod)

        for r in tab["setitems"]:
            idx = (r.get("index") or "").strip()
            kod = (r.get("item") or "").strip()
            if not idx or not kod or idx.lower().startswith("expansion"):
                continue
            baza = kody_baz.get(kod) or {}
            pids, linie = stale_props(r, KOL_PRZEDMIOT, 9)
            lr = gc.liczba(r.get("lvl req"), None)
            dodaj("set", idx, nazwy.get(idx) or idx, "sets",
                  tag_typu((baza.get("type") or "").strip(), rodzina),
                  wariant(hd_sets, gc.slug(idx), kod), lr,
                  list(wspolne_pid) + list(ustawienia_pid) + [pid_obrona_dodana] + pids,
                  linie, base=kod, set=(r.get("set") or "").strip())

        for r in tab["runes"]:
            runy = [x for x in ((r.get("Rune%d" % i) or "").strip() for i in range(1, 7)) if x]
            klucz = (r.get("Name") or "").strip()
            # kolumna '*Rune Name' to komentarz dla autorow gry i bywa niezgodna z nazwa
            # pokazywana graczowi ('Hustle (armor)' to w grze 'Hysteria')
            nazwa = nazwy.get(klucz) or (r.get("*Rune Name") or klucz).strip()
            if not runy or not nazwa:
                continue
            pids, linie = stale_props(r, KOL_RUNEWORD, 7)
            itypes = [x for x in ((r.get("itype%d" % i) or "").strip() for i in range(1, 7)) if x]
            tag = next((tag_typu(t, rodzina) for t in itypes if tag_typu(t, rodzina)), None)
            dodaj("runeword", (r.get("*Rune Name") or "").strip(), nazwa, "runewords",
                  tag, None, None,
                  list(wspolne_pid) + list(ustawienia_pid) + [pid_obrona_dodana] + pids,
                  linie, runes=runy, itypes=itypes)

        print("przedmioty: %s" % ", ".join(
            "%s %d" % (k, sum(1 for p in przedmioty if p["kind"] == k))
            for k in ("base", "unique", "set", "runeword")))

        ikony = zapisz_ikony(z, assety)

    for p in przedmioty:
        p["icon"] = ikony.get(p["asset"] or "")
    KATALOG.mkdir(parents=True, exist_ok=True)
    # 'statowe' to wszystkie wlasciwosci opisujace stat (bez pol wymaganych przez listing).
    # game_source dokleja je kazdemu przedmiotowi, bo tooltip potrafi pokazac linie, ktorej
    # tabela przedmiotu nie przewiduje: runa albo klejnot w gniezdzie, afiks na crafcie,
    # a w modzie takze afiksy, ktorych nie ma w tabelach afiksow.
    _zapisz("props.json", {"list": pula.lista,
                           "statowe": [p["property_id"] for p in pula.lista if not p["required"]]})
    _zapisz("items.json", przedmioty)
    _zapisz("meta.json", {
        "source": str(sciezka), "kind": zrodlo.etykieta,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "items": len(przedmioty), "props": len(pula.lista), "icons": len(ikony),
    })
    z_ikona = sum(1 for p in przedmioty if p.get("icon"))
    print("ikony: %d plikow, przedmiotow z ikona: %d/%d" % (len(ikony), z_ikona, len(przedmioty)))
    print("gotowe w %.0f s -> %s" % (time.time() - start, KATALOG))
    return 0


def _zapisz(nazwa, dane):
    plik = KATALOG / nazwa
    plik.write_text(json.dumps(dane, ensure_ascii=False), encoding="utf-8")
    print("  %-12s %7.1f MB" % (nazwa, plik.stat().st_size / 1048576.0))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
