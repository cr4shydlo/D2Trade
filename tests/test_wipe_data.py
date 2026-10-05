"""Czyszczenie wszystkich danych: kopia, zdejmowanie ofert, zabezpieczenia."""
import asyncio
import json

from nicegui.testing import User


async def test_kopia_pomija_sekrety_i_zachowuje_dane(user: User):
    """Kopia ma dane robocze, ale nie token i nie klucz API - tego nie pakujemy nigdzie."""
    import zipfile
    import paths
    await user.open("/")
    await asyncio.sleep(1.0)

    paths.SECRETS.mkdir(parents=True, exist_ok=True)
    (paths.SECRETS / "traderie_auth.txt").write_text("Bearer test", encoding="utf-8")

    plik = paths.backup_zip("test")
    w_srodku = zipfile.ZipFile(plik).namelist()
    print("plikow w kopii:", len(w_srodku), "| sekrety w kopii:", [n for n in w_srodku if "secret" in n])
    assert plik.exists() and plik.parent.name == "backups"
    assert not any("secret" in n for n in w_srodku)
    assert any(n.startswith("screenshots/") for n in w_srodku)   # dorobek pracy jest


async def test_czyszczenie_kasuje_dane_ale_nie_ustawienia(user: User):
    """Znikaja przedmioty, rejestr i ceny. Zostaja ustawienia, sekrety i cache."""
    import paths
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)
    assert W.S.items, "wzorzec danych powinien miec przedmioty"

    (paths.DATA / "posted.json").write_text("{}", encoding="utf-8")
    paths.SECRETS.mkdir(parents=True, exist_ok=True)
    (paths.SECRETS / "api_OVH.txt").write_text("klucz", encoding="utf-8")
    # baza z gry powstaje kilkanascie sekund z plikow gracza - czyszczenie nie moze jej zjesc
    (paths.DATA / "game_data").mkdir(parents=True, exist_ok=True)
    (paths.DATA / "game_data" / "items.json").write_text("[]", encoding="utf-8")
    ustawienia_przed = (paths.DATA / "settings.json").read_text(encoding="utf-8")
    cache_przed = len(list((paths.DATA / "cache").glob("*.json")))

    await W.wipe_everything(z_traderie=False)
    await asyncio.sleep(0.3)

    print("przedmioty po:", len(W.S.items), "| cache:", len(list((paths.DATA / 'cache').glob('*.json'))))
    assert not W.S.items
    assert not (paths.DATA / "posted.json").exists() and not (paths.DATA / "prices.json").exists()
    assert (paths.SECRETS / "api_OVH.txt").exists()                      # sekrety nietkniete
    assert (paths.DATA / "game_data" / "items.json").exists()            # baza z gry zostaje
    assert (paths.DATA / "settings.json").read_text(encoding="utf-8") == ustawienia_przed
    assert len(list((paths.DATA / "cache").glob("*.json"))) == cache_przed
    assert (paths.DATA / "screenshots").is_dir()                         # katalog zostaje, pusty
    assert list((paths.DATA / "backups").glob("przed_czyszczeniem_*.zip"))


async def test_blad_na_traderie_zatrzymuje_czyszczenie(user: User, monkeypatch):
    """Gdy oferty nie da sie zdjac, dane zostaja - inaczej na Traderie wisialyby sieroty."""
    import paths
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.5)

    iid = next(iter(W.S.order))
    W.S.items[iid]["lst"]["posted"] = {"time": "2026-10-01 10:00", "price": "ist", "listing_id": "555"}
    W.save_lst(W.S.items[iid])
    W.load_items()
    await asyncio.sleep(0.3)
    monkeypatch.setattr("d2_web.tp.remove_listing", lambda lid, auth: (False, "HTTP 500"))

    ile_przed = len(W.S.items)
    await W.wipe_everything(z_traderie=True)
    await asyncio.sleep(0.3)

    print("przedmioty po nieudanym zdjeciu:", len(W.S.items), "z", ile_przed)
    assert len(W.S.items) == ile_przed                      # nic nie skasowane
    assert list((paths.DATA / "backups").glob("przed_czyszczeniem_*.zip"))   # kopia i tak jest


async def test_slowo_potwierdzenia_odblokowuje_przycisk(user: User):
    """Przycisk kasujacy jest nieczynny, dopoki slowo nie zostanie przepisane co do znaku."""
    import d2_web as W
    await user.open("/")
    await asyncio.sleep(1.0)

    W.wipe_dialog()
    await asyncio.sleep(0.3)
    await user.should_see(W.WIPE_WORD)
    przyciski = [e for e in user.client.elements.values()
                 if type(e).__name__ == "Button" and getattr(e, "text", "") == "Usun bezpowrotnie"]
    assert przyciski, "brak przycisku kasujacego"
    print("przycisk aktywny przed przepisaniem:", przyciski[0].enabled)
    assert przyciski[0].enabled is False
