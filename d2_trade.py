"""
d2_trade.py - calosc w jednym miejscu.

    py d2_trade.py capture     W GRZE: zrzuty tooltipow klawiszem F12 (wyjscie: Ctrl+Alt+Q)
    py d2_trade.py             PO ZAMKNIECIU GRY: odczyt nowych screenow -> dopasowanie -> podglad
    py d2_trade.py --send      to samo + wystawianie na Traderie (z pytaniem o cene przy kazdym)

Opcje:  --no-prices  bez podpowiedzi cen
        --force      odczyt nawet gdy model nie miesci sie w calosci na GPU
        --redo       odczytaj ponownie wszystkie screeny (np. po zmianie modelu)
"""
import sys
from pathlib import Path

import paths

paths.use_data_dir()   # dane obok skryptu (albo tam, gdzie wskazuje D2_DANE)
FOLDER = Path("screenshots")


def main():
    args = sys.argv[1:]
    if "capture" in args:
        import d2_capture
        d2_capture.main()
        return

    import d2_ocr
    import traderie_map
    import traderie_post
    import app_config
    app_config.apply()        # ID konta, token, platforma itd. z okna Ustawienia

    stale = [m.__name__ + ".py" for m in (d2_ocr, traderie_map, traderie_post) if not hasattr(m, "run")]
    if stale:
        print("!!! Stare wersje plikow: " + ", ".join(stale))
        print("    Podmien je na nowe (sprawdz, czy przegladarka nie zapisala ich jako 'nazwa (1).py').")
        return

    FOLDER.mkdir(exist_ok=True)
    send = "--send" in args

    print("[1/3] Odczyt screenow")
    if d2_ocr.run(FOLDER, force_gpu="--force" in args, redo="--redo" in args, verbose=False) < 0:
        return
    d2_ocr.unload_model()  # zwalniamy VRAM - nie jest juz potrzebny

    print("\n[2/3] Dopasowanie do Traderie")
    traderie_map.run(FOLDER, verbose=False)

    print(f"\n[3/3] {'Wystawianie' if send else 'Podglad (nic nie jest wysylane - dodaj --send, zeby wystawic)'}")
    traderie_post.run(FOLDER, send=send, hints="--no-prices" not in args)


if __name__ == "__main__":
    main()
