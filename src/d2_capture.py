"""
d2_capture.py - zrzut okolicy kursora jednym klawiszem (do odczytu tooltipow D2R).

Najedz myszka na przedmiot, wcisnij HOTKEY -> skrypt zapisuje duzy obszar
wokol kursora do screenshots/. Samo znalezienie i wyciecie tooltipa robi d2_ocr.py
(model vision), wiec nic nie zostanie uciete niezaleznie od tla.

Uzycie:
    py d2_capture.py
Wyjscie: EXIT_HOTKEY (domyslnie ctrl+alt+q) albo Ctrl+C w konsoli.

Wymagania: py -m pip install mss keyboard pillow
D2R ustaw w trybie "Okno (pelny ekran)" / "Windowed Fullscreen".
"""
import ctypes
import time
import winsound
from datetime import datetime
from pathlib import Path

import keyboard
import mss
from PIL import Image

HOTKEY = "f12"
EXIT_HOTKEY = "ctrl+alt+q"
OUT = Path("screenshots")

# obszar wokol kursora (piksele ekranu): tooltip pojawia sie zwykle nad przedmiotem,
# przy gornej krawedzi ekranu - pod nim lub obok
LEFT, RIGHT = 800, 800
UP, DOWN = 1100, 600


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def capture():
    t0 = time.time()
    cx, cy = cursor_pos()
    with mss.mss() as sct:
        mon = next((m for m in sct.monitors[1:]
                    if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]),
                   sct.monitors[1])
        left = max(mon["left"], cx - LEFT)
        top = max(mon["top"], cy - UP)
        right = min(mon["left"] + mon["width"], cx + RIGHT)
        bottom = min(mon["top"] + mon["height"], cy + DOWN)
        shot = sct.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"item_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.png"
    img.save(path)
    winsound.Beep(1200, 80)
    print(f"[OK] {path.name}  {img.width}x{img.height}  ({time.time() - t0:.2f} s)")


def main():
    print(f"Najedz na przedmiot i wcisnij {HOTKEY.upper()}. Wyjscie: {EXIT_HOTKEY}.")
    keyboard.add_hotkey(HOTKEY, capture)
    keyboard.wait(EXIT_HOTKEY)


if __name__ == "__main__":
    main()