# D2 Trade — przewodnik po projekcie

Narzędzie do sprzedaży przedmiotów z Diablo II: Resurrected (mod **Reign of the Warlock**) na
[Traderie](https://traderie.com/diablo2resurrected) i d2jsp.

Przepływ: zrzut ekranu w grze (F12) → odczyt tooltipa modelem wizyjnym → dopasowanie do pozycji
w Traderie → podpowiedź ceny → wystawienie oferty → post sprzedażowy na d2jsp.

Od 4 X 2026 projekt jest repozytorium git i działa też **bez tokenu Traderie**: definicje
przedmiotów, zakresy statów i ikony wyciąga wtedy z plików gry użytkownika (sekcja 11).
Opis dla osoby z zewnątrz jest w [README.md](README.md) — ten plik jest dla pracujących nad kodem.

Projekt powstał w rozmowie z Claude (wrzesień–październik 2026) i dopiero teraz trafia do IDE.
Kod działa na komputerze autora (Windows, Python 3.11, `py -3.11`). Katalog projektu jest dowolny —
wszystkie ścieżki w kodzie są względne względem pliku `.py` (okna robią `os.chdir` na swój katalog,
a pliki `.bat` zaczynają od `cd /d "%~dp0"`).

---

## 1. Zasady, które obowiązują w tym projekcie

Te reguły wynikły z pracy nad projektem i trzeba je utrzymać.

1. **Żadnej automatyzacji w grze ani na d2jsp.** Program czyta wyłącznie zrzuty ekranu robione przez
   użytkownika i nie wysyła żadnych zdarzeń do gry. Regulamin d2jsp (§20) zabrania automatyzacji, więc
   narzędzie tylko generuje BBCode do ręcznego wklejenia i otwiera wątki w przeglądarce. Traderie
   obsługujemy przez jego (nieoficjalne) API, ale z losowym opóźnieniem 45–90 s między wystawieniami.
2. **Program nigdy nie ustawia ceny sam.** Podpowiada poziomy z transakcji; cenę zatwierdza człowiek.
   Przy magic/rare wycena jest wyłącznie pomocą — patrz sekcja 7.
3. **Lepiej nie podać ceny niż podać mylącą.** Jeśli nie da się odfiltrować podobnych egzemplarzy,
   nie pokazujemy ceny i mówimy wprost dlaczego.
4. **Komentarze i interfejs po polsku, bez polskich znaków w kodzie** (pliki `.py` są ASCII — tak
   powstał cały projekt; teksty UI z ogonkami są w plikach językowych i w literałach UI).
   Nazwy przedmiotów i statów zostają po angielsku, bo tak nazywa je gra i Traderie.
5. **Każda zmiana musi być sprawdzona na prawdziwych danych** (pliki w `screenshots/`, `cache/`) albo
   testem — patrz sekcja 9. W tym projekcie testy wyłapały kilka realnych błędów.
6. **Repozytorium ma być klonowalne przez obcą osobę.** Żadnych danych autora w plikach
   wchodzących do repo: ID konta, tokenu, nazw postaci, zrzutów z czytelnymi danymi konta.
   `settings.json`, `screenshots/`, `posted.json`, `secrets/` i `game_data/` są w `.gitignore`;
   wzorzec `sample_data/` ma wartości zastępcze (`seller_id: 0000000000`). Prawdziwe ID konta
   siedziało kiedyś na stałe w `traderie_sync.SELLER_ID` — teraz to pusty string i bierze się
   z ustawień. Przed commitem sprawdzaj, czy nie wraca.
7. **Zawartości gry nie rozpowszechniamy.** Czytanie plików własnej instalacji jest w porządku,
   ale `game_data/` (tabele, teksty, ikony Blizzarda) zostaje na dysku użytkownika.
8. **Sekrety leżą w jednym katalogu `secrets/`** (`traderie_auth.txt`, `api_OVH.txt`), cały katalog
   jest w `.gitignore` i **nigdy** nie trafia do `settings.json`. Oba wkleja się w Ustawieniach
   (pola ukryte, z podglądem) — zapis robi `app_config.save()` / `llm.save_api_key()`, ścieżki daje
   `paths.secret()`, a `paths.collect_secrets()` przy starcie przenosi pliki ze starych miejsc.
   **Zakaz dla każdego, kto pracuje nad kodem (także dla Claude): nie otwierać, nie wypisywać,
   nie kopiować i nie wysyłać zawartości tych plików ani nigdzie jej nie wklejać.** Przenoszenie
   pliku bez czytania jest w porządku; podgląd treści nie.

---

## 2. Uruchomienie

```bat
py -3.11 -m pip install nicegui pywebview keyboard mss pillow ollama
```

| Plik | Co robi |
|---|---|
| `D2 Trade.bat` | nowe okno (NiceGUI + pywebview), bez konsoli |
| `D2 Trade (console).bat` | to samo z konsolą — do diagnozy |
| `D2 Trade (old window).bat` | stare okno tkinter (`d2_gui.py`), zapasowe |
| `Extract game data.bat` | buduje `game_data/` z plików D2R (sekcja 11) |
| `py -3.11 d2_trade.py` | tryb konsolowy: `[--send] [--redo] [--force] [--no-prices]` |

Okno startuje na `http://127.0.0.1:8765` (w pywebview jako natywne okno).

---

## 3. Mapa plików

### Rdzeń (logika — tu mieszka wartość projektu)

| Plik | Odpowiedzialność |
|---|---|
| `d2_capture.py` | globalny skrót F12, zapis wycinka wokół kursora do `screenshots/` |
| `d2_ocr.py` | lokalizacja tooltipa + odczyt tekstu modelem, głosowanie między skalami |
| `llm.py` | **jeden interfejs do modelu**: Ollama albo endpoint zgodny z OpenAI (OVH); licznik tokenów |
| `traderie_map.py` | linie z OCR → pozycja w Traderie + lista statów do oferty; cache definicji |
| `traderie_price.py` | wycena unikatów/setów/runewordów (price-check, aktywne oferty, jakość rzutu) |
| `rare_eval.py` | ocena i wycena pomocnicza dla magic/rare (na podstawie `affixes_data.json`); `quality_label()` + progi `MID_ROLL`/`LOW_ROLL`/`WEAK_ROLL` dla opisu słownego rzutu |
| `traderie_post.py` | składnia cen, budowa payloadu, wystawianie, sprzedany/ukryj/usuń, rejestr duplikatów |
| `traderie_sync.py` | pobranie własnych ofert, import ofert spoza programu, status „do odnowienia” |
| `traderie_notify.py` | odpytywanie powiadomień Traderie |
| `quick_price.py` | szybka wycena z wolnego tekstu („shako def 140”) |
| `game_db.py` | katalog nazw przedmiotów (`game_items.json` + `game_data/`) — rozpoznaje nazwę bez pytania Traderie |
| `game_casc.py` | czytanie plików D2R: archiwum CASC albo wypakowany katalog `data/`; `.sprite` → PNG |
| `game_extract.py` | CLI: pliki gry → `game_data/` (przedmioty, szablony statów, ikony) |
| `game_source.py` | `game_data/` → definicje w formacie Traderie; źródło zapasowe dla `get_item()` |
| `d2jsp_post.py` | skróty statów i generowanie BBCode posta sprzedażowego |
| `app_config.py` | ustawienia konta i modelu; test połączenia |
| `i18n.py` | tłumaczenie UI + `settings.json` |
| `paths.py` | gdzie leżą pliki programu, a gdzie dane (`D2_DANE` przestawia dane — tego używają testy) |
| `affixes_build.py` | generator `affixes_data.json` z plików danych gry |

### Interfejs

| Plik | Uwaga |
|---|---|
| `d2_web.py` | **aktualne okno** (NiceGUI, jasny motyw). 1550 linii — kandydat do podziału, patrz sekcja 10 |
| `d2_gui.py` | **stare okno** (tkinter), tylko jako zapasowe. Nie rozwijać; docelowo usunąć |

### Dane (tworzone w czasie pracy, nie w repo)

```
screenshots/          zrzuty .png + <nazwa>.json (OCR) + <nazwa>.listing.json (mapowanie)
screenshots/_crops/   wycięte tooltipy do podglądu
screenshots/_trash/   kosz (ręczne usunięcie z listy)
cache/<slug>.json     definicje przedmiotów z Traderie
cache/img/            obrazki przedmiotów z CDN
cache/price_check.json   wyniki price-check (TTL 12 h) — mniej zapytań przy tej samej wycenie
game_data/            baza wyciągnięta z gry (items.json, props.json, meta.json, icons/)
logs/d2_RRRRMMDD.log  log okna
posted.json           rejestr wystawionych (po odcisku zawartości)
prices.json           ostatnia cena per przedmiot
token_usage.csv       licznik tokenów (nasz vs dostawcy)
settings.json         ustawienia (bez sekretów)
secrets/traderie_auth.txt   nagłówek Authorization do Traderie  [sekret, nie zaglądać]
secrets/api_OVH.txt         klucz API do OVH AI Endpoints       [sekret, nie zaglądać]
d2jsp_threads.json    linki do własnych wątków
d2jsp_fg.json         opcjonalny kurs run na FG
sample_data/          wzorzec danych do testow (w repo: screenshots + cache + settings bez sekretow)
backups/              kopie zapasowe danych (zip, poza repo)
```

Katalog danych ustawia `paths.py`: domyślnie obok skryptów, a `D2_DANE=<ścieżka>` przenosi go
w inne miejsce. Dzięki temu testy nie mogą dotknąć prawdziwych ofert, cen i ustawień.

---

## 4. Przepływ danych

```
F12 → screenshots/item_<ts>.png
   d2_ocr.run()        → screenshots/item_<ts>.json         {lines, tooltip_box, rarity_guess, reads}
   traderie_map.run()  → screenshots/item_<ts>.listing.json {item_id, name, kind, rarity, listing[], warnings}
   traderie_price.suggest()  → podpowiedź ceny (dla magic/rare przekierowanie do rare_eval.suggest())
   traderie_post.post()      → oferta na Traderie, wpis w posted.json
   d2jsp_post.build_post()   → BBCode do schowka
```

Pole `listing` to lista `{property_id, value}` — dokładnie to, co idzie do Traderie.
Pole `properties` to to samo z nazwami, do wyświetlania.

Pozostałe pola w `.listing.json` (dopisywane w trakcie pracy, nie przez odczyt):

| pole | znaczenie |
|---|---|
| `planned_price` | cena ustawiona w oknie, jeszcze nie wystawiona |
| `posted` | `{time, price, listing_id}` + `refreshed` po potwierdzonym odnowieniu |
| `sold`, `sold_via` | data sprzedaży i gdzie (traderie / ręcznie) |
| `removed` | dane zdjętej oferty (po usunięciu z Traderie) |
| `where` | `{char, stash}` — na której postaci i w której skrzyni leży przedmiot |
| `unmatched` | linie odczytu bez odpowiednika w Traderie (nie trafiają do oferty) |
| `needs_review` | trafia do „do sprawdzenia” |
| `imported` | oferta wciągnięta z Traderie, bez screena |

---

## 5. Odczyt (`d2_ocr.py`)

- **Dwuetapowa lokalizacja tooltipa**: model dostaje cały zrzut przeskalowany do 1000×1000 i zwraca
  ramkę, potem drugi raz na poszerzonym wycinku. `center_fix()` prostuje asymetryczne wycięcia po osi
  symetrii tekstu (tooltipy D2R są wyśrodkowane).
- **Czyszczenie tła** (`CLEAN_BG`): półprzezroczyste tło tooltipa przepuszcza UI skrzyni; piksele
  ciemniejsze niż `TEXT_MIN` idą na czarno.
- **Głosowanie**: każdy screen czytany w skalach 1.5 i 1.0; przy rozbieżności trzeci odczyt 1.25 jako
  rozstrzygający. Rozbieżności trafiają do `diffs` i oznaczają przedmiot do sprawdzenia.
- **Poprawki glifów**: czcionka D2R ma przekreślone O, mylone z zerem.
- **Ręczna korekta**: użytkownik może zaznaczyć tooltip myszą; ramka ląduje w `manual_box` i przeżywa
  ponowny odczyt.

`rarity_guess` (kolor nazwy) **jest zawodny** — w praktyce często zwraca `socketed/eth`. Dlatego
rozpoznanie rare/magic opiera się na tekście (patrz niżej), a kolor służy już tylko do wykrycia craftów.

---

## 6. Dopasowanie (`traderie_map.py`)

- Nazwa → `cache/<slug>.json` → `/items?id=<slug>&properties=true` → **pliki gry** (`game_source`).
  Kolejność jest celowa: cache z Traderie ma prawdziwe `property_id`, więc jest lepszy od
  definicji złożonej lokalnie. Bez tokenu krok sieciowy jest pomijany (`have_auth()`), żeby
  nie wisieć na żądaniach, które i tak wrócą z `Unauthorized`.
- **Rare**: baza jest w drugiej linii tooltipa („RING”, „JARED'S STONE”). **Magic**: baza siedzi
  w nazwie („Russet **Grand Charm** of Life”) — szukamy najdłuższego pasującego fragmentu przed „of”.
  Funkcja `find_base()` zwraca `(definicja, indeks pierwszej linii statów, 'rare'|'magic')`.
- Pola wynikowe:
  - `kind` — etykieta dla użytkownika: `unique` / `set` / `runeword` / `rare` / `magic` / `crafted` / `baza`
  - `rarity` — wartość wysyłana do Traderie, **tylko** `rare` albo `magic` (crafty idą jako rare)
- Dopasowanie statów: trzy przebiegi (dokładny regex → tolerancyjny z odwróconym znakiem → zbiór słów).
- „Adds 1-4 fire damage” rozbijane na dwa staty (min i max), bo tak zapisuje to Traderie.
- Zabezpieczenie: jeśli pobranie definicji padło z błędu sieci (`LOOKUP_FAILED`), przedmiot trafia do
  „do sprawdzenia”, **nie** jest brany za rare'a.
- Ustawienia oferty (`PLATFORM`, `MODE`, `LADDER`, `GAME_VERSION`) nadpisuje `app_config.apply()`.

---

## 7. Wycena

### Unikaty, sety, runewordy — `traderie_price.py`

1. `items/price-check` z filtrami ustawień i statów; przy wysokim rzucie (≥ `HIGH_ROLL` = 0.85)
   dokładany jest filtr na ten stat ±10% zakresu.
2. Gdy transakcji za mało (`MIN_TRADES`) — filtry luzowane, potem aktywne oferty jako ostateczność.
3. `rune_combo()` zamienia wartość w Ist na kombinację run; `RUNE_VALUES` bierze się z odpowiedzi API.

### Magic i rare — `rare_eval.py`

`affixes_data.json` zawiera **maksima statów per slot i rzadkość**, wyciągnięte wprost z CASC
gry (projekt `d2r_assets`, `tools/export_affixes_data.py`; 1496 afiksów). Poprzednia wersja
pochodziła z `affixes_build.py` i repo `blizzhackers/d2data` — obie zgadzają się w 401 z 402
wartości. Jedyna różnica: życie na Grand Charmie to **45**, nie 50. Afiks „of Vita” 46–50 jest
w tabelach gry, ale wymaga ilvl 110, a ilvl nie przekracza 99 — nigdy nie wypada, więc liczony
do maksimum sprawiał, że idealny 45-życiowy skiller wychodził na 90%.

- `KEYS` — staty, które decydują o wartości danego slotu (kolejność = ważność).
- `STRONG = 0.75` — stat ≥ 75% maksimum liczy się jako mocny.
- **Cena pokazywana jest tylko wtedy, gdy przedmiot ma co najmniej jeden mocny kluczowy stat.**
  Inaczej filtr nie zawęża wyników i cenę zawyżają dobre egzemplarze (tak powstał błąd „mal za
  śmieciowy charm”).
- `RULES` — **twarde warunki per slot**, bo sam próg `STRONG` nie wystarcza:

  | slot | warunek | dlaczego |
  |---|---|---|
  | `lcha` (Grand Charm) | wymagany stat `tab` (+1 do drzewka) | cała cena bierze się ze skillera; 45 life bez skillera to złom |
  | `scha` (Small Charm) | ≥ 1 mocny stat „meta”: life / @res / pojedynczy res / MF / max dmg / AR | sam FHR, mana albo atrybut nie ma wartości |
  | `mcha` (Large Charm) | 2 staty ≥ 90% maksimum | zajmuje dwa pola w ekwipunku, więc musi być naprawdę dobry |

  Pola reguły: `must` (staty obowiązkowe), `meta` (staty budujące cenę), `need` (ile mocnych poza
  `must`), `strong` (własny próg). Staty z `must` zawsze wchodzą do filtra price-check — przy
  skillerze to konkretne drzewko decyduje o cenie.
  Źródła: almarsguides „Loot Worth Keeping”, d2r-lootgoblin „Item Valuation”, ceny skillerów
  (45 life > 12% FHR > sam skiller).
- Przy dobrych rare'ach program sugeruje `offer` zamiast ceny sztywnej.

### Bez tokenu Traderie

Ceny biorą się z transakcji, a te są tylko na Traderie — więc w trybie lokalnym `suggest()`
w obu modułach kończy się na ocenie rzutu i dopisuje `traderie_price.NO_TRADERIE`. Ocena działa
w całości offline, bo maksima i tak pochodzą z plików gry. **Nie zgadujemy ceny z niczego innego**
— to ta sama zasada co w punkcie 3 sekcji 1.

---

## 8. Traderie API (nieoficjalne)

Baza: `https://traderie.com/api/diablo2resurrected`, nagłówek `Authorization: Bearer <JWT>` z
`traderie_auth.txt` (token trzeba kopiować z DevTools z widoku **Nieprzetworzone** — zwykły widok go ucina).

| Operacja | Metoda | Ścieżka / uwagi |
|---|---|---|
| definicja przedmiotu | GET | `/items?id=<slug>&variants=&tags=&properties=true` |
| wyszukiwarka | GET | `/items?search=<tekst>` |
| transakcje | GET | `/items/price-check?item=<id>&limit=100&prop_*=...` (też `prop_Rarity=rare,magic`) |
| aktywne oferty | GET | `/listings?item=<id>&selling=true&...&priceValues=true` |
| własne oferty | GET | `/listings?seller=<id>&completed=false\|true&active=all&...` |
| wystawienie | POST | `/listings/create` |
| sprzedany | POST | `/sell` — `{"listing":"id","selling":true,"remove":false}` |
| usunięcie | POST | `/sell` — `{...,"remove":true}` |
| ukryj / pokaż | **PUT** | `/listings/toggle` — `{"listing":"id","active":false\|true}` |
| odnowienie oferty | **PUT** | `/listings/refresh` — `{"listing":"id"}`; odpowiedź `{"success":true,"version":"1.3.0"}` |
| powiadomienia | GET | `/notifications` |

Wygasły token zwraca `{"error":"Unauthorized jwt"}` — rozpoznaje to `traderie_post.is_expired()`
i `traderie_map.SessionExpired`.

**Metoda ma znaczenie, a 404 kłamie.** Przy złej metodzie ten serwer odpowiada tym samym 404 co przy
nieznanej ścieżce: `{"status":"fail","message":"Can't find /api/... on this server!"}`. Przy 404
sprawdzaj więc najpierw metodę — `/listings/toggle` i `/listings/refresh` to **PUT**, nie POST.
Tak powstał błąd „odnów nie działa”: ścieżka była dobra od początku.

Ceny w ofercie: pozycje w tej samej grupie (`group`) to „i”, różne grupy to „albo”.
Składnia tekstowa w programie: `ist+mal` (razem), `ber | jah` (do wyboru), `3 pamy` (ilość),
`offer` (czekam na oferty).

---

## 9. Testy

W projekcie są testy dla NiceGUI (`nicegui.testing.User`) — symulują użytkownika bez przeglądarki.

```bat
.venv\Scripts\python -m pytest -q      albo:  py -3.11 -m pytest -q
```

> **Uwaga wyniesiona z wpadki (2 X 2026).** Izolacja stoi na `D2_DANE`, a `paths.DATA` czyta tę
> zmienną **raz, przy imporcie**. Cokolwiek zaimportuje moduł programu przed `conftest.py` (np.
> wtyczka podana w `-p`, bo wtyczki ładują się wcześniej), sprawia, że `DATA` pokazuje na katalog
> projektu i testy piszą po **prawdziwych** danych — wtedy poszedł klucz OVH w `secrets/`,
> `seller_id`, ustawienia modelu i pola w `screenshots/*.listing.json`. `conftest.py` przerywa
> teraz przebieg, gdy `paths` jest już w `sys.modules` albo gdy `paths.DATA` nie jest katalogiem
> testowym. Audyt wymagający własnej wtyczki uruchamiaj z `D2_DANE=<katalog tymczasowy>` w poleceniu.

Testy **nie ruszają prawdziwych danych**: `conftest.py` ustawia `D2_DANE` na katalog tymczasowy
i przed każdym testem rozpakowuje tam `sample_data/`. `posted.json`, `prices.json`, `screenshots/`
i `settings.json` w projekcie zostają nietknięte. Traderie i model nie są odpytywane
(`traderie_map.http_json` to atrapa).

Wymagane `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
main_file = run_app.py
```

Scenariusze w repo (**95 testów**, `py -3.11 -m pytest -q` ≈ 100 s):

| plik | co sprawdza |
|---|---|
| `test_app.py` | przepływ główny, widoki, okno ceny, szybka wycena, synchronizacja; strażnik `ui.notify` w funkcjach async |
| `test_actions.py` | wystawianie z potwierdzeniem, sprzedaż, usuwanie z listy, odblokowanie „do sprawdzenia”, kopertka z wiadomościami |
| `test_rare2.py` | panel magic/rare ze statami na tle maksimum |
| `test_llm.py`, `test_switch.py` | dostawca modelu, licznik tokenów, cennik, klucz API zapisany do pliku w `secrets/` (a nie do `settings.json`) |
| `test_charms.py` | reguły charmów (Grand Charm bez skillera nie dostaje ceny) |
| `test_price_cache.py` | cache price-check: TTL, inne filtry = inne pytanie, `force`, błąd sieci oddaje poprzedni wynik |
| `test_game_catalog.py` | katalog nazw z gry: rozpoznanie bez sieci, nazwy bez „The”, mniej zapytań |
| `test_roll_quality.py` | opis słowny jakości rzutu i skala kolorów paska |
| `test_local_mode.py` | praca bez tokenu: definicja z plików gry, odczyt rare'a, blokada wystawiania, brak cen, post d2jsp, sekcja „Dane z gry” w Ustawieniach, podpowiedź w pasku bocznym |
| `test_game_extract.py` | wyciąg z gry na sztucznych tabelach: formaty opisów, trudne staty (drzewka, klasy, per poziom), nazwy z tabel tekstowych |
| `test_relisting.py` | odnawianie: PUT, zaznaczone vs wszystkie, „serwer potwierdził, ale nie odnowił”, padnięcie `ui.notify`, pole „gdzie leży”, samoczynne sprawdzenie ofert po wejściu w „Wystawione”, zerwane połączenie przy tym sprawdzeniu nie blokuje okna |
| `test_mapping.py` | magic/rare bez fałszywych ostrzeżeń, staty bez liczby, staty których Traderie nie ma, ponowny odczyt nie gubi wpisów |
| `test_paging.py` | podział listy na strony, numeracja, wybór 10/20/50 zapisany w `settings.json` |
| `test_d2jsp.py` | ceny w poście: cztery kombinacje runy/FG, zaokrąglanie do pół FG, przelicznik kursów i ich cache |
| `test_wipe_data.py` | czyszczenie danych: kopia bez sekretów, co znika a co zostaje, błąd Traderie przerywa, słowo potwierdzenia blokuje przycisk |
| `test_theme.py` | jasny/ciemny: obie palety mają te same klucze, stałe kolorów wskazują na zmienne CSS, wybór zapisany w `settings.json` |

Wzorzec danych odświeżasz, kopiując wybrane pliki `.json`/`.listing.json` ze `screenshots/`
do `sample_data/screenshots/` (+ `cache/<slug>.json`, jeśli to nowy przedmiot).

Przy zmianach w logice (bez UI) najszybszą kontrolą jest przepuszczenie prawdziwych plików
`screenshots/*.json` przez `traderie_map.map_item()` i porównanie wyniku.

---

## 10. Stan i co dalej

### Zrobione (październik 2026, po przeniesieniu do IDE)

- **Repozytorium git i praca bez Traderie (4 X 2026)** — projekt da się sklonować i uruchomić
  bez żadnych poświadczeń. Szczegóły w sekcji 11; tu dwie rzeczy warte zapamiętania.
  **Z kodu wyleciało ID konta autora**: `traderie_sync.SELLER_ID` było wpisane na stałe,
  a ten sam numer siedział we wzorcu testów — mimo że okno zasłania to pole, żeby nie świeciło
  na nagraniu. Teraz stała jest pusta, wartość bierze się z ustawień, a `own_listings()` bez niej
  mówi wprost, czego brakuje, zamiast pytać Traderie o oferty nikogo.
  **Nazwy przedmiotów szły ze złej kolumny**: `uniqueitems.index` / `runes.*Rune Name` to klucze
  wewnętrzne, a gracz widzi tekst z `item-names` / `item-runes`. Rozjeżdżały się w 126 miejscach
  („Unique Warlock Helm" to „Hellwarden's Will", „Wartraveler" to „War Traveler", „Hustle (armor)"
  to „Hysteria"). Dotyczyło to też `game_items.json` — plik jest przebudowany, stare zapisy
  zostały jako `aliases`, więc jedno i drugie nadal się rozpoznaje.
- **Katalog gry w Ustawieniach (4 X 2026)** — sekcja „Dane z gry” pod „Kontem Traderie”:
  pole ze ścieżką (podpowiadane przez `game_casc.zgadnij_gre()`), przycisk „Wyciągnij dane
  z gry” / „Odśwież bazę” i stan bazy (ile przedmiotów, ile ikon, z kiedy). Wywołuje
  `game_extract.zbuduj(ścieżka, log)` przez `run.io_bound`, a po zakończeniu zapomina leniwe
  katalogi (`game_source.odswiez()`, `game_db._INDEKS`, `S.defs`, `S.imgs`) — inaczej okno
  pokazywałoby stare dane. Ścieżka ląduje w `settings.json` jako `game_dir`.
  Gdy nie ma tokenu, pasek boczny mówi, czy dane z gry są włączone, czy trzeba wskazać katalog.
  **ID konta może być puste** — bez konta Traderie program i tak działa, więc walidacja
  „same cyfry” nie może blokować zapisu ustawień.
- **`start_post()` sprawdza `local` przed cenami** — przedmiot rozpoznany z plików gry nie da
  się wystawić, więc mówimy o tym od razu. Wcześniej `build_payload()` przerywał w połowie
  wystawiania, a użytkownik najpierw słyszał o złej cenie.
- **Nazwy plików po angielsku, README po angielsku, licencja MIT (4 X 2026)** — repozytorium
  ma trafić na GitHub. `.bat`, makiety i pliki testów dostały angielskie nazwy; treść plików
  (komentarze, ten dokument, literały UI) zostaje po polsku. README ma instrukcję krok po
  kroku dla kogoś, kto nigdy nie uruchamiał Pythona.

- **Nowy wygląd okna (2 X 2026)** — ciemny, spokojny motyw zamiast jasnego i pastelowego.
  Zasada: **jedyne nasycone kolory to kolory rzadkości przedmiotów** (`RAR` w `d2_web.py`, takie jak
  w grze) plus trzy barwy znaczeniowe `OK` / `WARN` / `BAD` (+ `ACT` dla „do odnowienia”). Rodzaj
  przedmiotu niesie pasek 3 px przy wierszu i kolor etykiety, a nie kolorowe tło. Status to kropka
  i tekst, nie pigułka. Promienie 3 px (kontrolki) i 5 px (panele), zero cieni i podnoszenia kart.
  Pismo: IBM Plex Sans + IBM Plex Mono (ceny, staty, liczby — równa szerokość cyfr, klasa `.mono`).
  Akcja główna to klasa `.primary` (kontrast, nie kolor marki).
- **Czyszczenie wszystkich danych (3 X 2026)** — Ustawienia → zwinięta „Strefa niebezpieczna" →
  „Wyczyść wszystkie dane…". Okno pokazuje, ile przedmiotów zniknie i co zostaje, pozwala przy
  okazji **zdjąć oferty z Traderie**, a przycisk kasujący jest nieczynny, dopóki nie przepisze się
  słowa `WIPE_WORD` (`USUWAM`). Kolejność w `wipe_everything()`: najpierw `paths.backup_zip()`
  (do `backups/`, **bez `secrets/`** — czyszczenie ich nie dotyka, więc nie ma czego odtwarzać),
  potem zdejmowanie ofert po kolei z przerwą `REFRESH_DELAY` i przyciskiem Stop, na końcu
  `paths.wipe_data()`. **Nieudane zdjęcie choćby jednej oferty przerywa całość i nie kasuje
  niczego lokalnie** — inaczej na Traderie wisiałyby oferty, o których program już nic nie wie.
  Znika `screenshots/` (z `_crops/` i `_trash/`), `posted.json`, `prices.json`; zostają
  ustawienia, sekrety, `cache/`, logi, kopie i linki d2jsp (`paths.KEEP`).
- **ID konta zasłonięte** — pole „ID konta (seller)" jest `password` z podglądem, tak jak token
  i klucz API: nie świeci na zrzucie ekranu ani na nagraniu.
- **Motyw jasny i ciemny (2 X 2026)** — wybór w Ustawieniach → „Wygląd”, zapisywany w
  `settings.json` (`theme`, domyślnie `dark` — okno stoi obok pełnoekranowej gry). Zmiana działa
  od razu, bez „Zapisz” i bez przebudowy widoku. **Kolory są zmiennymi CSS**: stałe `BG`, `MUTED`,
  `RAR[...]` itd. trzymają nazwy (`var(--muted)`), a wartości leżą w `PALETY` — dlatego żadne
  z ~200 wywołań `style(f"color:{MUTED}")` nie wymagało zmiany. `_zmienne_css()` wstawia obie
  palety do `HEAD` jako `:root[data-theme=…]`, `index()` dokłada wybraną na goły `:root`
  (żeby okno wstało w swoich kolorach, bez mrugnięcia), a `set_motyw()` podmienia atrybut na
  `<html>` i przestawia `ui.dark_mode` (Quasar maluje tak menu, tabele i powiadomienia).
  W jasnej palecie kolory rzadkości są przyciemnione — growe złoto i żółć są na jasnym tle
  nieczytelne. Dwa miejsca zostają przy stałym hexie (`CROP_BOX`, `CROP_SEL`): to ramka wycinka
  rysowana **atrybutem** SVG, który nie rozumie `var()`, a leży na zrzucie z gry, nie na tle okna.
  Podgląd palety: `mockup_light_theme.html` (przycisk przełącza motyw).
- **Etykiety sekcji bez wersalików** — „STATYSTYKI” → „Statystyki” itd. Teksty są kluczami
  tłumaczeń, więc razem z kodem zmieniły się `lang/en.json`, `de.json`, `ko.json` i asercje w testach.
- **Katalogi po angielsku** — `screenshots/` (z `_crops/` i `_trash/`), `cache/`, `logs/`,
  `backups/`, `secrets/`, `sample_data/`, `lang/`. Stary układ (`screeny/`, `kopie/`, `sekrety/`,
  `_usuniete/`) przenosi przy starcie `paths.migrate_layout()`, więc dane z poprzedniej wersji
  same trafiają na swoje miejsce. Polskie słowo „screeny” w tekstach dla użytkownika zostało.
- **Sekrety w jednym katalogu** — `secrets/traderie_auth.txt` i `secrets/api_OVH.txt`
  (`paths.SEKRETY`, `paths.secret()`); `paths.collect_secrets()` przenosi pliki z poprzednich
  lokalizacji przy starcie, bez czytania ich treści.
- **Klucz API modelu wklejany w oknie** — pole „Klucz API:” (ukryte, jak token Traderie) w sekcji
  chmury; zapisuje się do pliku w `secrets/`, nie do ustawień. Okno nie pyta już o nazwę pliku
  (`llm_key_file` zostało ustawieniem technicznym z domyślną wartością `api_OVH.txt`). „Testuj model” sprawdza klucz
  jeszcze przed zapisaniem (`llm.override_key()` na czas testu).
- **Powiadomienia włączone domyślnie** — przełącznik nazywa się „Sprawdzaj wiadomości w Traderie
  co 5 min”,
  startuje włączony, a wybór zapisuje się w `settings.json` (`notify`, `set_notify()`).
- **Pasek boczny** jest `sticky` z własnym przewijaniem (`min/max-height:100vh`), żeby ostatni
  wiersz nie był przycinany przy niskim oknie ani nie odstawał od dołu na pełnym ekranie.
- **„Testuj połączenie”** jest w sekcji „Konto Traderie” (nie pod językiem), a wynik ląduje
  w etykiecie przy tokenie.
- **Kopertka z wiadomościami** — nowe powiadomienia z Traderie liczą się przy ikonie koperty
  w nagłówku (`mail_button()`); kliknięcie otwiera listę (`messages_dialog()`, ostatnie
  `MAX_MESSAGES` = 50) z przyciskiem „Otwórz na Traderie”. Otwarcie okna zeruje licznik.
- **Sekcja „Post d2jsp” w Ustawieniach** — dwa niezależne przełączniki: „Ceny w runach”
  (`d2jsp_runes`) i „Ceny w FG” (`d2jsp_fg`), plus kurs „Ile FG za 1 Ist” (`d2jsp_fg_per_ist`).
  Daje to: oba → `ist + mal (~87.5 fg)`, samo FG → `87.5 fg`, same runy → `ist + mal`,
  żadne → linia kończy się na statach (bez ceny). FG włączone bez kursu nie ma z czego liczyć,
  więc zostaje to, co wybrano poza nim. Kwoty **zaokrąglane w dół do pół FG** (`fg_round()`).
  Kursy pozostałych walut liczą się z wartości run podanych przez Traderie, zapamiętanych
  w `cache/rune_values.json` (`traderie_price.save_runes()` / `load_runes()`); `d2jsp_fg.json`
  nadal nadpisuje pojedyncze waluty. **Kursu FG nie pobieramy z d2jsp** — nie ma źródła, które
  wolno odpytywać (regulamin, pkt 20), więc wpisuje go człowiek.
- **FG także w oknie** — `d2_web.fg_text()` dokleja `(~N fg)` w nawiasie, tym samym kolorem co cena: przy cenie na karcie
  i pod kafelkami poziomów (panel i szybka wycena). Wymaga wpisanego kursu i włączonego
  przelącznika `fg_in_app` (osobny od tego dla posta); liczy
  go ten sam przelicznik co post d2jsp (tabela cache'owana na 5 s, żeby nie czytać ustawień
  przy każdej karcie).
- **Samoczynne sprawdzanie ofert** — wejście w „Wystawione” odpala `do_sync()` (`auto_sync()` w
  `d2_web.py`), ale nie częściej niż co `SYNC_GAP` = 120 s; czas zapisuje się **przed** pobraniem,
  więc zerwane połączenie nie powoduje pytania przy każdym kliknięciu. Przycisk „Sprawdź oferty”
  został — wymusza sprawdzenie od razu.
  **To sprawdzenie nie idzie przez `task()`** (`background_sync()`, 2 X 2026): `task()` ustawia
  `S.busy`, a to wyszarza wszystkie przyciski — m.in. „Odczytaj screeny” — na czas pobierania
  (`http_json` ma 30 s na żądanie, a `sync()` robi ich kilka), więc przy milczącym Traderie okno
  stało bezużyteczne i kończyło się śladem wyjątku w logu. Teraz zerwane połączenie to jedna linia
  w logu. Przycisk „Sprawdź oferty” nadal idzie przez `task()` — tam blokada i głośny błąd są na
  miejscu, bo użytkownik czeka na wynik.
- **Stronicowanie listy** — `PAGE_SIZES = (10, 20, 50)`, domyślnie 20; wybór zapisuje się w
  `settings.json` (`page_size`). Pasek pod listą pojawia się, gdy pozycji jest więcej niż 10.
  Strona wraca na pierwszą przy zmianie widoku, filtra postaci i przełącznika „pominięte”.

- **Wycena charmów** — twarde warunki per slot (`RULES` w `rare_eval.py`, sekcja 7). Grand Charm bez
  skillera nie dostaje ceny, nawet z maksymalnym rzutem.
- **Odnawianie ofert** (sprawdzone na żywej ofercie 2 X 2026) — `traderie_post.refresh_listing()`
  (`PUT /listings/refresh`) + przyciski
  „Odnów ofertę” (pojedynczo, w panelu) i „Odnów wszystkie (N)” (po kolei, z przerwą
  `REFRESH_DELAY` = 8–15 s). **Sukces nie jest zakładany**: `refresh_listing` wymaga wyraźnego
  potwierdzenia od serwera (inaczej zwraca treść odpowiedzi do logu), a `d2_web.verify_relist()`
  po wysłaniu pobiera stan ofert i sprawdza, czy licznik naprawdę drgnął. Jeśli nie — mówi to
  wprost i nie zapisuje `posted.refreshed`. Pierwsza wersja wierzyła odpowiedzi „bez błędu”
  i dwa razy skłamała, że odnowiła ofertę.
- **Gdzie leży przedmiot** — pole `where` w `.listing.json` (`{"char", "stash"}`), edytowane w panelu,
  plakietka na karcie, filtr „Postać:” nad listą i okno „Co wyjąć (sprzedane)”: sprzedane przedmioty
  pogrupowane po postaci i skrzyni, do skopiowania (żeby za jednym logowaniem pozbierać wszystko).
- **Zaznaczanie w widoku „Wystawione”** — checkbox pojawia się przy ofertach gotowych do odnowienia;
  `relist_plan()` bierze zaznaczone, a gdy nic nie zaznaczono — wszystkie gotowe. Przycisk zmienia się
  na „Odnów zaznaczone (N)”, obok „Zaznacz gotowe / Odznacz”. Odnowiona oferta odznacza się sama.
- **Tłumaczenia** — `lang/en.json`, `de.json`, `ko.json` mają pełne pokrycie tekstów widocznych
  w oknie (351 wpisów + 47 fragmentów). Polska etykieta „JAKOŚĆ RZUTU” nazywa się teraz
  `STATYSTYKI` (angielskie „ROLL QUALITY” zostało bez zmian) — to także klucz tłumaczenia.
  Dociągnięte 2 X 2026 po zgłoszeniu autora („przełączam na angielski i po lewej Przedmioty,
  Wystawione…”): pasek boczny, licznik stanów, stan tokenu, wybór dostawcy modelu, nagłówki tabeli
  tokenów, ostrzeżenia z `traderie_map.py` i oceny z `rare_eval.py` (werdykty i powody per slot
  jako `phrases`, bo wchodzą w środek linii „ocena (rare): …”).
- **Dopasowanie magic/rare** — koniec z fałszywymi ostrzeżeniami z tabeli afiksów bazy; staty bez
  liczby w tooltipie (sundery) dostają `default_value`; staty, których Traderie nie ma, są widoczne
  w panelu zamiast cicho znikać; ponowny odczyt nie gubi `where`/`planned_price` (`KEEP_ON_REMAP`).
- **Bezpieczeństwo danych** — testy pracują na kopii (`D2_DANE` + `sample_data/`), nie na prawdziwych
  ofertach; `.gitignore` i `requirements.txt` uzupełnione; kopia danych w `backups/*.zip`.
- **Środowisko** — `.venv` ma wszystkie zależności, pliki `.bat` wybierają `.venv`, a gdy go nie ma,
  spadają na `py -3.11`. Ścieżki w kodzie są względne (`paths.py`), katalog projektu można przenosić.

### Decyzje autora (2 X 2026) — nie wracać do tego bez jego polecenia

1. **Odnawianie z programu działa** — potwierdzone na żywej ofercie po zmianie metody na `PUT`
   (wersja z POST zwracała 404). Temat zamknięty.
2. **Etykieta rodzaju (`kind`) przy starszych przedmiotach zostaje jak jest.** Widok jej używa
   (`KIND` w `d2_web.py`), ale pliki `.listing.json` z wcześniejszych odczytów nie mają tego pola.
   Autor świadomie to odłożył („zostawiamy jak jest”) — **nie dorabiać**.
3. **Brak pola w Traderie = wystawiamy bez tego statu.** Tak już działa: `unmatched` nie ustawia
   `needs_review` (`traderie_map.py`, `out["needs_review"] = bool(warnings or ocr.needs_review)`),
   więc przedmiot jest gotowy do wystawienia, a panel tylko informuje, czego w ofercie nie będzie
   (np. `Regenerate Mana 9%` na craftowanym pierścieniu). Nie dopisywać tego do opisu oferty.

### Znane ograniczenia

- **Crafty**: Traderie nie ma takiej rzadkości — wystawiane jako rare, oznaczane do sprawdzenia.
  Po obejrzeniu przedmiotu przycisk **„Sprawdzone - można wystawić”** w panelu zdejmuje `needs_review`
  (zapisuje `reviewed`), więc pozycja wraca do „gotowych”. Ponowny odczyt screena przywraca
  ostrzeżenie — to celowe, bo treść mogła się zmienić.
- Walidacja zakresów i „stałych wartości” z opisu Traderie dotyczy **tylko** unikatów/setów/runewordów.
  Przy magic/rare opis bazy to tabela wszystkich możliwych afiksów (`|Fine|1-3 max dmg & 10-20 AR|`),
  więc `map_item()` pomija tam walidację i ostrzeżenia o „nieodczytanych zmiennych statach” — inaczej
  każdy charm lądował w „do sprawdzenia” z kilkunastoma bezsensownymi ostrzeżeniami.
- Ponowny odczyt nadpisuje `.listing.json`, więc pola wpisane przez użytkownika (`KEEP_ON_REMAP`:
  `where`, `planned_price`, `sold`, `sold_via`, `removed`) są przenoszone ze starego pliku.
  Wystawione przedmioty (`posted`) nie są w ogóle przemapowywane.
- **Dane afiksów** pochodzą z plików LoD; afiksy dodane przez Reign of the Warlock mogą ich nie
  obejmować. Odświeżenie: `py -3.11 affixes_build.py`.
- **Tryb lokalny: pakiet `casc`** ma gotowe koło tylko dla Windows x64 + Python 3.11. Gdy go nie ma,
  `game_extract.py` przyjmuje katalog z już wypakowanym `data/` (CascView) — `game_casc.otworz()`
  rozpoznaje jedno i drugie, a `Katalog` nie wymaga żadnej biblioteki (dlatego testy go używają).
- **Tryb lokalny: linie spoza tabeli przedmiotu.** Definicja z plików gry dostaje własne staty
  **plus całą pulę statów** (`props.json` → `statowe`), bo tooltip pokazuje też runę w gnieździe
  i afiksy crafta. Kolejność ma znaczenie: `game_source.get_item()` daje najpierw staty tego
  przedmiotu, bo `map_item` bierze pierwszy pasujący szablon.
- **Tryb lokalny: brak numerów Traderie.** `property_id` to oznaczenia z ich bazy, których w grze
  nie ma, więc lokalnie są ujemne (poza 399/796/1855, traktowanymi w kodzie specjalnie).
  Listing ma wtedy `local: true`, a `traderie_post.build_payload()` odmawia wystawienia.
  Po wklejeniu tokenu trzeba odczytać screena ponownie.
- **Nazwy statów modowych** (np. `Sigil: Lethargy`) nie mają skrótów w `d2jsp_post.SHORT`.
- **Staty, których Traderie nie ma w definicji przedmiotu** (np. `Regenerate Mana 9%` na pierścieniu)
  zostają w `unmatched` i nie idą do oferty. Panel szczegółów pokazuje je jako „Nie trafi do oferty…”
  (tylko linie z liczbą — bez liczby to zwykle nazwy innych części setu z tooltipa).
- Pole liczbowe, którego wartość **nie pojawia się w tooltipie** (np. `Monster Lightning Immunity is
  Sundered` = 300), dostaje `default_value` z Traderie. Wartość w regexie jest opcjonalna tylko na
  końcu linii, żeby „Defense per Level 2” nie udawało samego „Defense”.
- **Lista kart** przy 100+ przedmiotach będzie cięższa niż tabela — przewidziane filtrowanie widokami.
- Tłumaczenia: nowy tekst UI trzeba dopisać do `lang/*.json` (brak = zostaje polski). Uwaga:
  `i18n._line()` obcina spacje przed szukaniem, więc klucz z sekcji `strings` zapisuj **bez**
  wiodących i końcowych spacji.
- **Jak sprawdzać braki tłumaczeń** — `py -3.11 i18n.py <kod>` porównuje tylko plik językowy
  z `en.json`, **nie** z kodem, więc nie wykryje tekstu, którego nigdzie nie wpisano. Szukanie po
  literałach `t("...")` też kłamie: `t()` w kilkunastu miejscach dostaje **zmienną**
  (`nav_button(label)`, etykiety licznika stanów, werdykty z `rare_eval`, ostrzeżenia z
  `traderie_map`), a tekst źródłowy leży w innym pliku. Jedyna rzetelna kontrola to podmiana
  `i18n._line` na wersję zapisującą każdy tekst, który wyszedł nieprzetłumaczony, i przejście
  po oknie (np. uruchomienie testów z wymuszonym `i18n.load("en")`).
- **Klucz tłumaczenia nie może być samą wstawką.** `{0}` w kluczu to w `_line()` wzorzec `.+?`,
  więc klucz w rodzaju `{0}-{1} z {2}` (stąd pochodziła etykieta stronicowania) pasował do
  dowolnego zdania z myślnikiem i słowem „z” i przechwytywał tłumaczenie **przed** sekcją
  `phrases` — np. ocena rare'a zostawała po polsku z podmienionym jednym słowem. Etykieta nazywa
  się teraz „Pozycje {0}-{1} z {2}”. Każdy nowy klucz musi mieć własny, rozpoznawalny tekst.
- Odnawianie: Traderie pozwala odnowić ofertę po ~20 h (`traderie_sync.RELIST_HOURS`); stan
  „do odnowienia” bierze się z `updated_at` pobranego przy „Sprawdź oferty”.
- **Stronicowanie dotyczy tylko tego, co widać.** „Wystaw zaznaczone”, „Zaznacz gotowe” i
  „Odnów wszystkie” działają na **wszystkich** pasujących przedmiotach, także spoza bieżącej strony
  — tak było przed zmianą i tak zostało.
- `ui.notify` działa tylko w kontekście żywego elementu strony; długie zadanie przebudowuje widok
  i element znika, więc komunikaty idą przez `d2_web.say()` (przy błędzie — do logu).
  **Zasada jest teraz pilnowana testem** (`test_app.py::test_dlugie_zadania_nie_wolaja_ui_notify`):
  w żadnej funkcji `async` w `d2_web.py` nie może być `ui.notify`. Reguła powstała po tym, jak
  po udanym wystawieniu ofert program wywalił się na ostatniej linii `do_post` —
  `RuntimeError: The parent element this slot belongs to has been deleted` (4 X 2026). Oferty
  poszły poprawnie, ale ślad wyjątku wyglądał, jakby coś się nie udało. Przy okazji poprawione
  zostało 13 innych takich wywołań.

### Dług techniczny

- `d2_web.py` ma ~1900 linii — warto rozdzielić na widoki, okna dialogowe i stan.
- `d2_gui.py` (stare okno tkinter) został przy starym wyglądzie — nowego motywu nie dostanie.
- `d2_gui.py` (tkinter, ~1800 linii) duplikuje logikę UI; nie ma nowych funkcji (odnawianie,
  pole „gdzie leży”) — usunąć, gdy nowe okno się sprawdzi.
- `traderie_post.py`: `post`, `_sell_call`, `set_visible` i `refresh_listing` powtarzają ten sam
  schemat żądania — warto wyciągnąć jedną funkcję pomocniczą.
- **Nazwy klas CSS muszą zaczynać się od `d2`** (`.d2row`, `.d2list`). Quasar ma własne `.row`,
  `.column`, `.list`, a NiceGUI nadaje je każdemu `ui.row()` / `ui.column()` — klasa o tej samej
  nazwie przemalowuje całe okno (kreska nad każdym rzędem, ciemnienie przy najechaniu).
- **Obwodka focusa na kontenerze.** Quasar nadaje `tabindex` m.in. oknu dialogowemu, a przeglądarka
  rysuje na nim własną obwodkę focusa — `outline` idzie **poza** obrys elementu, więc nachodzi na
  sąsiadów (kliknięcie w pole wyszukiwania w oknie ceny obrysowywało czarną ramką całą kartę).
  Gasi to `div:focus` w `HEAD`; pola i przyciski mają własne podświetlenie.
- **NiceGUI maluje każdy przycisk kolorem `primary`** (niebieski Quasara). Gasi to jeden blok
  w `HEAD` (`.q-btn.bg-primary`, `.q-btn.text-primary`), a wygląd dają klasy `.ghost`, `.primary`,
  `.lvl`, `.price`, `.navbtn` — zapisane jako `.q-btn.<klasa>`, żeby wygrać specyficznością.
- Teksty UI są w kodzie po polsku i służą jako klucze tłumaczeń — zmiana literału psuje tłumaczenie
  (sprawdzać `lang/*.json`).

---

## 11. Dane z gry (`game_casc.py`, `game_extract.py`, `game_source.py`)

Bez tokenu Traderie nie ma skąd wziąć definicji przedmiotu, a bez niej program nie wie, które
linie tooltipa są statami ani jakie mają zakresy. Te same dane leżą w plikach gry.

```
py -3.11 game_extract.py "C:\Program Files (x86)\Diablo II Resurrected"
```

Wynik w `game_data/` (przy danych, nie przy kodzie — jest w `paths.KEEP`, poza kopią zapasową
i poza repo):

| plik | zawartość |
|---|---|
| `props.json` | `{"list": [...], "statowe": [...]}` — wspólna pula właściwości (szablony linii tooltipa) |
| `items.json` | przedmioty: rodzaj, nazwa, aliasy, typ, tagi, `props`, `desc`, ikona |
| `meta.json` | skąd, kiedy, liczniki (pokazywane użytkownikowi) |
| `icons/*.png` | ikony HD (`.sprite` → PNG, przycięte do zawartości) |

Dwa źródła, jedno API (`game_casc.otworz()`): archiwum **CASC** zainstalowanej gry albo zwykły
katalog z wypakowanym `data/`. Nazwy plików podaje się w jednej postaci (`data/global/excel/armor.txt`).

### Pułapki, które już kosztowały czas

1. **Pakiet `_casc` ma nieoczywiste sygnatury.** `open_file` zwraca `(ok, uchwyt)`, `read_file`
   `(uchwyt, dane, ile)`. Przekazanie pary do `read_file` kończy się mylącym
   „Parameter must be a file reference" — wygląda jak zła nazwa pliku, a jest złym argumentem.
2. **Nazwa przedmiotu nie jest w kolumnie z nazwą.** Patrz sekcja 10 — zawsze przez `item-names`.
3. **Tag typu musi być w słowniku Traderie, nie gry.** `rare_eval.slot_of()` dopasowuje tagi,
   a gra nazywa Grand Charma „Large Charm". Tag wprost z `itemtypes.txt` wyceniłby skillera
   jak Large Charma. Stąd własna tabela `TAGI_TYPU`, od najbardziej szczegółowego typu.
4. **Tekst drzewka jest już całą linią.** `StrSklTabItem1` to `"%+d to Javelin and Spear Skills"`,
   więc doklejenie `"%+d to "` daje `"+{{value}} to +{{v2}} to ..."`. Pilnuje tego test.
5. **Opis `+X do umiejętności klasy` jest zawsze pierwszej klasy.** `itemstatcost` ma jeden wpis
   („Amazon"); o którą klasę chodzi, mówi kolumna `val` w `properties.txt`. Teksty per klasa są
   w `charstats` (`StrAllSkills`, `StrClassOnly`) — stamtąd też bierze się kod klasy, bo kolumny
   z nim nie ma: klucz `SorOnly` → `sor`, czyli to, co `skills.txt` ma w `charclass`.
6. **Staty zbiorcze to jedna linia, nie kilka.** `res-all` zmienia cztery odporności, ale gra
   pisze „All Resistances +30". Tak samo `all-stats` i obrażenia od trucizny. Teksty biorą się
   z plików językowych (`ZBIORCZE`, `TRUCIZNA`), nie z angielskich literałów w kodzie.
7. **Staty „per poziom" nie mają min/max.** Zakres liczy się z parametru: gra trzyma go w ósmych
   częściach punktu na poziom, więc `param/8` do `param*99/8`. Sprawdzone na opisach z Traderie
   (Harlequin Crest 1-148 życia, Enigma 0-74 siły, 1-99% MF).
8. **Afiksy podają umiejętność numerem, unikaty nazwą.** Numer to pozycja wiersza w `skills.txt`;
   nazwa idzie przez `skilldesc.txt` → `skills.json`. `game_extract.nazwy_umiejetnosci()` indeksuje
   po obu.

### Jak to sprawdzać

Najszybsza kontrola to przepuszczenie prawdziwych `screenshots/*.json` przez `map_item()` dwa razy
— raz z cache Traderie, raz z podmienionym `tm.load_auth` na `{}` i pustym `tm.CACHE` — i porównanie
wyników. Przy ostatnim przebiegu (20 odczytów) **żadna linia statu nie została niedopasowana**,
a wszystkie różnice to staty, których lokalnie jest **więcej** niż w Traderie (np. `Regenerate Mana`
na pierścieniu, rozbite obrażenia od ognia, `Required Level` na secie).

---

## 12. Styl kodu

- Python 3.11, biblioteka standardowa + `nicegui`, `pillow`, `ollama`, `keyboard`, `mss`, `pywebview`.
- Pliki `.py` bez polskich znaków diakrytycznych; komentarze po polsku, zwięzłe, tłumaczą **dlaczego**,
  a nie **co** (np. „kolor bywa źle rozpoznany, więc decyduje tekst”).
- Stałe konfiguracyjne na górze modułu, z komentarzem wyjaśniającym wartość.
- Kolory i promienie bierz ze stałych w bloku `# ---- wyglad ----` w `d2_web.py`; nowych literalnych kolorów w kodzie widoków nie dopisujemy.
- Zero zależności między modułami UI a logiką w drugą stronę: logika nie wie o oknie.
- Funkcje raczej krótkie, bez klas tam, gdzie wystarczy funkcja; jedyny większy obiekt stanu to
  `State` w `d2_web.py`.
- Komunikaty dla użytkownika mówią, **co zrobić**, nie tylko co się stało.
