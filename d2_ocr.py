"""
d2_ocr.py - odczyt tooltipow przedmiotow Diablo II: Resurrected ze screenow
przy uzyciu lokalnego modelu vision w Ollamie.

Uzycie:
    py d2_ocr.py screenshots

Dla kazdego obrazka (png/jpg) w folderze powstaje plik .json obok niego:
    {"file": ..., "rarity_guess": ..., "lines": [...], "seconds": ...}
Gdy model zwroci niepoprawna odpowiedz, surowy tekst laduje w <obrazek>.raw.txt
"""
import re
import sys
import json
import time
from collections import Counter
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops
import llm

MODEL = "qwen3-vl:4b-instruct"  # domyslny model lokalny; faktyczny wybor jest w Ustawieniach (llm.py)
SCALES = (1.5, 1.0)  # kazdy screen czytany w dwoch skalach - rozbieznosci = do sprawdzenia
TIEBREAK_SCALE = 1.25  # trzeci odczyt tylko przy rozbieznosciach
USE_JSON = False     # False = zwykly tekst (szybciej, mniej pustych odpowiedzi)
KEEP_ALIVE = "30m"   # jak dlugo model zostaje w VRAM po ostatnim uzyciu
PATCH = 32           # Qwen3-VL tnie obraz na kafelki 32x32 - wyrownujemy wymiary
MAX_SIDE = 1200    # limit dluzszego boku po skalowaniu (chroni przed przepelnieniem kontekstu)
NUM_CTX = 8192     # kontekst modelu - obraz zamienia sie na tokeny
NUM_PREDICT = 1024  # max dlugosc odpowiedzi - ucina petle modelu
TIMEOUT = 120       # sekundy na jedno zapytanie


# --- lokalizacja tooltipa na duzych zrzutach (z d2_capture.py) ---
LOCATE_MIN_SIDE = 900   # obrazy wieksze niz to traktujemy jako zrzut okolicy kursora
LOCATE_SIZE = 1000      # obraz do lokalizacji skalujemy do 1000x1000 (wspolrzedne 0-1000)
LOCATE_PAD_X = 0.08     # margines w poziomie po dokladnej lokalizacji (czesc szerokosci ramki)
LOCATE_PAD_Y = 0.05     # margines w pionie
LOCATE_EXPAND_X = 0.6   # obszar do 2. etapu lokalizacji: ramka z 1. etapu poszerzona o tyle z kazdej strony
LOCATE_EXPAND_Y = 0.2
CLEAN_BG = True         # wygaszenie tla prześwitujacego przez tooltip (napisy skrzyni, ikony)
TEXT_MIN = 100          # piksele ciemniejsze niz to (najjasniejszy kanal) -> czarne
CROPS = "_crops"        # wyciete tooltipy do podgladu (podfolder, nie jest ponownie przetwarzany)
LOCATE_PROMPT = (
    "This is a Diablo II screenshot. Find the item tooltip: the semi-transparent dark box "
    "with centered lines of text describing one item (name, base type, defense or damage, "
    "requirements, magical properties). Return the bounding box of the whole box, "
    "including all text lines, as bbox_2d [x1, y1, x2, y2]."
)
LOCATE_SCHEMA = {
    "type": "object",
    "properties": {"bbox_2d": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}},
    "required": ["bbox_2d"],
}

PROMPT = (
    "Transcribe every line of text in this Diablo II item tooltip exactly as written, "
    "top to bottom, one entry per line. Do not interpret, translate, correct or add anything."
)

SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
    "required": ["lines"],
}

# Przyblizone kolory nazw przedmiotow w D2R - do skalibrowania na Twoich screenach.
RARITY_COLORS = {
    "unique/runeword": (199, 179, 119),  # zloty
    "set":             (0, 200, 0),      # zielony
    "rare":            (255, 255, 100),  # zolty
    "magic":           (105, 105, 255),  # niebieski
    "crafted":         (255, 165, 0),    # pomaranczowy
    "normal":          (255, 255, 255),  # bialy
    "socketed/eth":    (130, 130, 130),  # szary
}
NEUTRAL = {"normal", "socketed/eth"}


def nearest_color(p):
    return min(RARITY_COLORS, key=lambda k: sum((a - c) ** 2 for a, c in zip(p, RARITY_COLORS[k])))


def guess_rarity(img: Image.Image) -> str:
    """Glosowanie pikseli w gornym pasku tooltipa (nazwa przedmiotu).
    Kolorowy tekst wygrywa, jesli stanowi zauwazalna czesc jasnych pikseli."""
    w, h = img.size
    top = img.crop((0, 0, w, max(1, int(h * 0.12)))).convert("RGB")
    getter = getattr(top, "get_flattened_data", top.getdata)
    bright = [p for p in getter() if max(p) > 80]  # pomijamy czarne tlo
    if not bright:
        return "unknown"
    votes = Counter(nearest_color(p) for p in bright)
    colored = {k: v for k, v in votes.items() if k not in NEUTRAL}
    if colored:
        best = max(colored, key=colored.get)
        if colored[best] > 0.15 * len(bright):
            return best
    return votes.most_common(1)[0][0]


def prepare_image(img: Image.Image, target: float) -> bytes:
    scale = min(target, MAX_SIDE / max(img.size))
    w = max(PATCH, round(img.width * scale / PATCH) * PATCH)
    h = max(PATCH, round(img.height * scale / PATCH) * PATCH)
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ask_model(png: bytes, use_schema: bool = True):
    """Zwraca (tekst odpowiedzi, diagnostyka)."""
    prompt = PROMPT if use_schema else PROMPT + " Output only the lines, one per line, nothing else."
    return llm.ask(png, prompt, schema=SCHEMA if use_schema else None, max_tokens=NUM_PREDICT,
                   keep_alive=KEEP_ALIVE, num_ctx=NUM_CTX, kind="read")


GLYPHS = "\u00d8\u00f8\u2298\u2295\u0398"  # O/0 z kreska lub krzyzykiem z czcionki D2R


def fix_glyphs(line: str) -> str:
    """Przekreslone O z czcionki D2R: obok cyfr -> '0', w pozostalych przypadkach -> 'O'."""
    out = []
    for i, ch in enumerate(line):
        if ch in GLYPHS:
            prev = line[i - 1] if i > 0 else ""
            nxt = line[i + 1] if i + 1 < len(line) else ""
            ch = "0" if (prev.isdigit() or nxt.isdigit()) else "O"
        out.append(ch)
    return "".join(out)


def plain_to_lines(text: str) -> list:
    """Dzieli odpowiedz na linie. Usuwa tylko wypunktowania ("- ", "* ", "1. "),
    NIE minusy przed liczbami (-50% Target Defense)."""
    out = []
    for l in text.strip().strip("`").splitlines():
        l = re.sub(r"^\s*(?:[-*\u2022]\s+|\d+[.)]\s+)", "", l).strip()
        if l:
            out.append(l)
    return out


def ask_box(img: Image.Image):
    """Pyta model o ramke tooltipa na obrazie. Zwraca (x1, y1, x2, y2) w pikselach tego obrazu albo None."""
    small = img.resize((LOCATE_SIZE, LOCATE_SIZE), Image.LANCZOS)
    buf = BytesIO()
    small.save(buf, format="PNG")
    text, _ = llm.ask(buf.getvalue(), LOCATE_PROMPT, schema=LOCATE_SCHEMA, max_tokens=64,
                      keep_alive=KEEP_ALIVE, num_ctx=NUM_CTX, kind="locate")
    try:
        x1, y1, x2, y2 = json.loads(text)["bbox_2d"]
    except Exception:
        return None
    x1, x2 = sorted((max(0, min(LOCATE_SIZE, x1)), max(0, min(LOCATE_SIZE, x2))))
    y1, y2 = sorted((max(0, min(LOCATE_SIZE, y1)), max(0, min(LOCATE_SIZE, y2))))
    if x2 - x1 < 40 or y2 - y1 < 40:  # absurdalnie mala ramka
        return None
    sx, sy = img.width / LOCATE_SIZE, img.height / LOCATE_SIZE
    return x1 * sx, y1 * sy, x2 * sx, y2 * sy


def locate_tooltip(img: Image.Image):
    """Lokalizacja dwuetapowa: zgrubnie na calym zrzucie, potem dokladnie na powiekszonym fragmencie.
    Zwraca (wyciety obraz, ramka w pikselach) albo (None, None)."""
    b1 = ask_box(img)
    if not b1:
        return None, None
    x1, y1, x2, y2 = b1
    w, h = x2 - x1, y2 - y1
    region = (max(0, int(x1 - w * LOCATE_EXPAND_X)), max(0, int(y1 - h * LOCATE_EXPAND_Y)),
              min(img.width, int(x2 + w * LOCATE_EXPAND_X)), min(img.height, int(y2 + h * LOCATE_EXPAND_Y)))
    b2 = ask_box(img.crop(region))
    if b2 and (b2[2] - b2[0]) > 0.5 * w and (b2[3] - b2[1]) > 0.5 * h:
        x1, y1, x2, y2 = b2[0] + region[0], b2[1] + region[1], b2[2] + region[0], b2[3] + region[1]
        px, py = LOCATE_PAD_X, LOCATE_PAD_Y
    else:
        px, py = 0.2, 0.06  # 2. etap nie wyszedl - ramka z 1. etapu z szerszym marginesem
    w, h = x2 - x1, y2 - y1
    box = (max(0, int(x1 - w * px)), max(0, int(y1 - h * py)),
           min(img.width, int(x2 + w * px)), min(img.height, int(y2 + h * py)))
    box = center_fix(clean_background(img), box)
    return img.crop(box), box


def text_lines(clean: Image.Image):
    """Linie tekstu na wygaszonym obrazie: [(y1, y2, x1, x2)]."""
    mask = clean.convert("L").point(lambda v: 255 if v > 0 else 0)
    w, h = mask.size
    rows = [mask.crop((0, y, w, y + 1)).getbbox() is not None for y in range(h)]
    lines, y = [], 0
    while y < h:
        if rows[y]:
            y0 = y
            while y < h and rows[y]:
                y += 1
            if y - y0 >= 4:  # pomijamy szum wysokosci 1-3 px
                bb = mask.crop((0, y0, w, y)).getbbox()
                lines.append((y0, y, bb[0], bb[2]))
        y += 1
    return lines


def center_fix(clean_full: Image.Image, box):
    """Tekst tooltipa D2R jest wysrodkowany. Os wyznaczamy z linii mieszczacych sie w wycinku,
    a wycinek ustawiamy symetrycznie wokol niej - odtwarza to strone ucieta przez model."""
    x1, y1, x2, y2 = box
    crop = clean_full.crop(box)
    w = crop.width
    inside = [(a + b) / 2 for _, _, a, b in text_lines(crop) if a > 4 and b < w - 4 and b - a >= 30]
    if len(inside) < 2:
        return box
    inside.sort()
    axis = inside[len(inside) // 2]              # mediana srodkow linii
    half = max(axis, w - axis)
    nx1 = max(0, int(x1 + axis - half))
    nx2 = min(clean_full.width, int(x1 + axis + half))
    return (nx1, y1, nx2, y2)


def clean_background(img: Image.Image) -> Image.Image:
    """Tooltip jest polprzezroczysty: tlo (napisy skrzyni, ikony) prześwituje przyciemnione.
    Tekst tooltipa jest jasny, wiec wszystko ponizej progu jasnosci zamieniamy na czern."""
    r, g, b = img.convert("RGB").split()
    brightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = brightest.point(lambda v: 255 if v >= TEXT_MIN else 0)
    return Image.composite(img.convert("RGB"), Image.new("RGB", img.size), mask)


def normalize(line: str) -> str:
    """Ujednolicenie do porownan: wielkosc liter, myslniki, spacje."""
    line = line.lower().replace("–", "-")
    line = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", line)  # half-freeze -> half freeze, ale -50% zostaje
    return re.sub(r"\s+", " ", line).strip()


def read_once(png: bytes):
    """Jeden odczyt (bez ponowien - przy temperature 0 wynik i tak bylby ten sam).
    JSON tylko gdy USE_JSON; przy pustym JSON jedna proba tekstowa. Zwraca (linie, tryb, log)."""
    log = []
    if USE_JSON:
        raw, diag = ask_model(png, use_schema=True)
        log.append({"diag": diag, "raw": raw})
        try:
            lines = json.loads(raw).get("lines", [])
            if lines:
                return [fix_glyphs(l) for l in lines], "json", log
        except json.JSONDecodeError:
            pass
    raw, diag = ask_model(png, use_schema=False)
    log.append({"diag": diag, "raw": raw})
    return [fix_glyphs(l) for l in plain_to_lines(raw)], "plain", log


def compare(a: list, b: list) -> list:
    """Lista rozbieznosci miedzy dwoma odczytami (po normalizacji)."""
    na, nb = [normalize(x) for x in a], [normalize(x) for x in b]
    diffs = []
    for i in range(max(len(na), len(nb))):
        x = na[i] if i < len(na) else "<brak>"
        y = nb[i] if i < len(nb) else "<brak>"
        if x != y:
            diffs.append(f"{x}  <>  {y}")
    return diffs


def vote(variants: list):
    """Glosowanie per linia miedzy odczytami. Zwraca (linie, nierozstrzygniete)."""
    n = max(len(v) for v in variants)
    out, unresolved = [], []
    for i in range(n):
        cands = [v[i] for v in variants if i < len(v)]
        counts = Counter(normalize(c) for c in cands)
        best, cnt = counts.most_common(1)[0]
        if cnt >= 2:
            out.append(next(c for c in cands if normalize(c) == best))
        else:
            out.append(cands[0])
            unresolved.append("  <>  ".join(normalize(c) for c in cands))
    return out, unresolved


def read_tooltip(path: Path, manual_box=None) -> dict:
    """manual_box = (x1, y1, x2, y2) ustawione recznie w oknie - wtedy bez automatycznej lokalizacji."""
    img = Image.open(path).convert("RGB")
    size = f"{img.width}x{img.height}"
    print(f"--- {path.name} ({size}) ...", flush=True)

    t0 = time.time()
    located = None
    if manual_box:
        located = [int(v) for v in manual_box]
        img = img.crop(tuple(located))
        (path.parent / CROPS).mkdir(exist_ok=True)
        print("    reczny wycinek", flush=True)
    elif max(img.size) > LOCATE_MIN_SIDE:
        print("    lokalizacja tooltipa ...", end=" ", flush=True)
        tl = time.time()
        crop, located = locate_tooltip(img)
        print(f"{time.time() - tl:.1f} s", flush=True)
        if crop is not None:
            img = crop
            crops = path.parent / CROPS
            crops.mkdir(exist_ok=True)
            img.save(crops / path.name)
        else:
            print("    (nie udalo sie zlokalizowac tooltipa - czytam caly obraz)")
    rarity = guess_rarity(img)
    if CLEAN_BG:
        img = clean_background(img)
        if located:
            img.save(path.parent / CROPS / path.name)  # podglad tego, co faktycznie czyta model

    reads, logs = [], []
    for sc in SCALES:
        lines, mode, log = read_once(prepare_image(img, sc))
        reads.append({"scale": sc, "mode": mode, "lines": lines, "calls": [e["diag"] for e in log]})
        logs.append({"scale": sc, "log": log})

    if not any(r["lines"] for r in reads):
        raw_path = path.with_suffix(".raw.txt")
        raw_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
        raise ValueError(f"brak odczytu w zadnej skali, diagnostyka w {raw_path.name}")

    good = [r for r in reads if r["lines"]]
    main_read = good[0]
    diffs = compare(good[0]["lines"], good[1]["lines"]) if len(good) > 1 else ["drugi odczyt pusty"]

    # rozjemca: trzeci odczyt, glosowanie 2 z 3 dla kazdej linii
    if diffs:
        lines3, mode3, log3 = read_once(prepare_image(img, TIEBREAK_SCALE))
        reads.append({"scale": TIEBREAK_SCALE, "mode": mode3, "lines": lines3, "calls": [e["diag"] for e in log3]})
        logs.append({"scale": TIEBREAK_SCALE, "log": log3})
        good = [r for r in reads if r["lines"]]
        if len(good) >= 2:
            voted, diffs = vote([r["lines"] for r in good])
            main_read = {"lines": voted}

    return {
        "file": path.name,
        "size": size,
        "tooltip_box": located,
        "manual_box": [int(v) for v in manual_box] if manual_box else None,
        "rarity_guess": rarity,
        "mode": "/".join(r["mode"] if r["lines"] else "pusty" for r in reads),
        "needs_review": bool(diffs),
        "diffs": diffs,
        "lines": main_read["lines"],
        "reads": reads,
        "seconds": round(time.time() - t0, 1),
        "timing": {
            k: round(sum(e["diag"][k] for l in logs for e in l["log"]), 1)
            for k in ("load_s", "prefill_s", "gen_s")
        },
    }


def check_gpu() -> bool:
    """Laduje model i sprawdza, czy siedzi w calosci w VRAM. Zwraca True, gdy wszystko OK.
    Dla modelu w chmurze sprawdza tylko polaczenie."""
    if not llm.is_local():
        ok, msg = llm.test_connection()
        print(f"Model w chmurze: {msg}" if ok else f"\n!!! Model w chmurze niedostepny: {msg}")
        return ok
    print(f"Ladowanie modelu {llm.model()} ...", flush=True)
    client = llm.ollama_client()
    client.generate(model=llm.model(), prompt="", keep_alive=KEEP_ALIVE)
    for m in client.ps().get("models", []):
        name = m.get("name") or m.get("model")
        if name != llm.model():
            continue
        size, vram = m.get("size") or 0, m.get("size_vram") or 0
        pct = 100 * vram / size if size else 0
        if pct >= 99:
            print(f"Model w 100% na GPU ({size / 2**30:.1f} GB).")
            return True
        print(f"\n!!! Model tylko w {pct:.0f}% na GPU - reszta na CPU, bedzie BARDZO wolno.")
        print("    Najczestsza przyczyna: model zaladowal sie, gdy dzialala gra lub inny program zajmowal VRAM.")
        print(f"    Zamknij gre, potem:  ollama stop {llm.model()}  i uruchom skrypt ponownie.")
        return False
    return True


def unload_model():
    """Zwalnia VRAM (np. przed uruchomieniem gry). Dla modelu w chmurze nic nie robi."""
    if not llm.is_local():
        return
    try:
        llm.ollama_client().generate(model=llm.model(), prompt="", keep_alive=0)
    except Exception:
        pass


def run(folder: Path, force_gpu: bool = False, redo: bool = False, verbose: bool = True) -> int:
    """Odczytuje screeny z folderu. Pomija te, ktore maja juz plik .json (chyba ze redo). Zwraca liczbe odczytanych."""
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    todo = [p for p in images if redo or not p.with_suffix(".json").exists()]
    if not todo:
        print("   brak nowych screenow")
        return 0
    if not force_gpu and not check_gpu():
        print("    (aby mimo to kontynuowac, dodaj --force)")
        return -1

    done = 0
    for i, p in enumerate(todo, 1):
        manual = None
        prev = p.with_suffix(".json")
        if prev.exists():  # przy --redo zachowujemy recznie ustawiony wycinek
            try:
                manual = json.loads(prev.read_text(encoding="utf-8")).get("manual_box")
            except Exception:
                pass
        try:
            result = read_tooltip(p, manual_box=manual)
        except Exception as e:
            print(f"   [BLAD] {p.name}: {e}")
            continue
        p.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        done += 1
        if not verbose:
            flag = "  !!! odczyty niezgodne" if result["needs_review"] else ""
            print(f"   [{i}/{len(todo)}] {result['lines'][0] if result['lines'] else p.name}  ({result['seconds']} s){flag}")
            continue
        t = result["timing"]
        print(f"\n=== {p.name}  ({result['rarity_guess']}, {result['mode']}, {result['seconds']} s"
              f" = ladowanie {t['load_s']} + obraz {t['prefill_s']} + tekst {t['gen_s']})")
        for r in result["reads"]:
            for c in r["calls"]:
                think = " +MYSLENIE" if c["thinking"] else ""
                print(f"    skala {r['scale']}: {c['eval_count']} tokenow, {c['gen_s']} s, "
                      f"{len(r['lines'])} linii, koniec={c['done_reason']}{think}")
        for line in result["lines"]:
            print("  " + line)
        if result["needs_review"]:
            print("  !!! REVIEW - brak zgodnosci miedzy odczytami:")
            for d in result["diffs"]:
                print("      " + d)
    return done


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(Path(args[0] if args else "screenshots"), force_gpu="--force" in sys.argv, redo="--redo" in sys.argv)


if __name__ == "__main__":
    main()
