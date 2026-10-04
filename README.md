# D2 Trade

Pomocnik do sprzedawania przedmiotow z **Diablo II: Resurrected**. Robisz zrzut ekranu
w grze, program odczytuje tooltip modelem wizyjnym, rozpoznaje przedmiot, ocenia jakosc
rzutu i przygotowuje ofere: na [Traderie](https://traderie.com/diablo2resurrected) albo
jako gotowy post BBCode na d2jsp.

```
F12 w grze  ->  odczyt tooltipa  ->  rozpoznanie przedmiotu  ->  ocena rzutu i cena
                                                              ->  oferta na Traderie
                                                              ->  post na d2jsp (BBCode)
```

Okno jest po polsku; dostepne tez angielskie, niemieckie i koreanskie
(Ustawienia -> Jezyk). Nazwy przedmiotow i statow zostaja po angielsku, bo tak nazywa
je gra.

---

## Czego program nie robi

To nie jest bot i nie ma byc.

- **Nie automatyzuje gry.** Czyta wylacznie zrzuty ekranu, ktore sam zrobisz skrotem F12.
  Nie wysyla do gry zadnych klawiszy ani klikniec, nie czyta jej pamieci, nie podmienia
  plikow.
- **Nie automatyzuje d2jsp.** Regulamin d2jsp (pkt 20) zabrania automatyzacji, wiec
  program tylko generuje BBCode do recznego wklejenia i otwiera watek w przegladarce.
- **Nie ustawia ceny za Ciebie.** Pokazuje poziomy z prawdziwych transakcji; cene
  zatwierdzasz Ty. Gdy danych jest za malo, program mowi wprost, ze ceny nie podaje -
  lepiej jej nie podac niz podac mylaca.

Traderie obslugujemy przez jego (nieoficjalne) API, z losowa przerwa 45-90 s miedzy
wystawieniami.

---

## Czego potrzebujesz

| | |
|---|---|
| System | Windows (globalny skrot F12 i zrzuty ekranu sa zrobione pod Windows) |
| Python | 3.11 (`py -3.11`) |
| Model do odczytu | **albo** lokalna [Ollama](https://ollama.com) na Twojej karcie, **albo** endpoint zgodny z OpenAI |
| Konto Traderie | **opcjonalne** - patrz "Trzy tryby pracy" |
| Diablo II: Resurrected na dysku | opcjonalne, ale bez tokenu Traderie to z tego biora sie dane o przedmiotach |

### Instalacja

```bat
git clone <adres-repozytorium> d2trade
cd d2trade
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Uruchomienie: dwuklik na **`D2 Trade.bat`**. Okno otwiera sie na
`http://127.0.0.1:8765` (w natywnym oknie, jesli jest `pywebview`).
`D2 Trade (z konsola).bat` robi to samo z widoczna konsola - do diagnozy.

Pliki `.bat` najpierw szukaja `.venv`, a gdy go nie ma, spadaja na `py -3.11`.
Katalog projektu moze byc dowolny i mozna go przenosic - wszystkie sciezki w kodzie
sa wzgledne.

---

## Trzy tryby pracy

Program dziala bez zadnych poswiadczen; im wiecej podasz, tym wiecej umie.

| | odczyt screenow | przedmioty, staty, ikony | ocena rzutu | ceny z transakcji | wystawianie | post d2jsp |
|---|---|---|---|---|---|---|
| **1. Nic nie podane** | lokalna Ollama | *brak* | - | - | - | - |
| **2. Katalog z gra** | lokalna Ollama | z plikow gry | tak | - | - | **tak** |
| **3. + token Traderie** | Ollama albo chmura | z Traderie | tak | **tak** | **tak** | tak |

**Tryb 2 to odpowiedz na pytanie "a skad statystyki i obrazki bez Traderie".**
Wszystko, co trzeba, lezy w plikach gry na Twoim dysku: nazwy przedmiotow, zakresy
statow unikatow, lista afiksow i ikony ekwipunku. Wystarczy raz je przeczytac.

### Jak zrobic baze z gry

Dwuklik na **`Wyciagnij dane z gry.bat`** albo:

```bat
py -3.11 game_extract.py "C:\Program Files (x86)\Diablo II Resurrected"
py -3.11 game_extract.py        REM szuka gry w typowych miejscach
```

Trwa to kilkadziesiat sekund i tworzy katalog `game_data/` (kilkanascie MB):
tabele przedmiotow, szablony linii tooltipa i ikony PNG. Potem program dziala bez sieci.
Po aktualizacji gry albo moda uruchom to ponownie - dojda nowe przedmioty.

Program **tylko czyta** pliki gry. Nie zmienia instalacji, nie uruchamia gry i niczego
nie wysyla - `game_data/` zostaje na Twoim dysku i jest w `.gitignore`.

Czytanie archiwum CASC wymaga pakietu `casc` (nakladka na CascLib):

```bat
py -3.11 -m pip install casc
```

Pakiet ma gotowe kolo tylko dla Windows x64 + Python 3.11. Jesli nie da sie go
zainstalowac, wypakuj z gry katalog `data` dowolnym narzedziem do CASC (np. CascView)
i wskaz `game_extract.py` ten katalog - reszta dziala tak samo.

### Co dokladnie dziala bez Traderie

- rozpoznanie przedmiotu po nazwie: bazy, unikaty, sety, runewordy, runy i klejnoty;
- rozbicie tooltipa na staty, razem z magic/rare i craftami;
- **ocena jakosci rzutu** - wartosc statu na tle maksimum, ktore da sie wylosowac
  (`affixes_data.json` jest w repozytorium, wiec to dziala od razu);
- ikona przedmiotu z gry zamiast z CDN Traderie;
- **post sprzedazowy na d2jsp** z cenami w runach i/lub FG;
- pole "gdzie lezy" (postac i skrzynia), filtrowanie, stronicowanie, motyw jasny/ciemny.

Czego nie ma bez tokenu: cen z transakcji i wystawiania ofert. W miejscu ceny program
pisze, dlaczego jej nie podaje. Przedmiot rozpoznany lokalnie ma w listingu znacznik
`local` i **nie da sie go wystawic** - numery wlasciwosci sa wtedy wlasne, nie z bazy
Traderie, wiec oferta bylaby bledna. Po wklejeniu tokenu odczytaj screena ponownie.

### Jak dodac token Traderie

Ustawienia -> Konto Traderie. Token to naglowek `Authorization` z DevTools przegladarki
(zakladka Siec, widok **Nieprzetworzone** - zwykly widok ucina go wielokropkiem).
Zapisuje sie do `secrets/traderie_auth.txt`. Tam tez trafia klucz API modelu w chmurze.
Caly katalog `secrets/` jest w `.gitignore` i **nigdy** nie wchodzi do `settings.json`
ani do kopii zapasowych.

---

## Model do odczytu

Domyslnie **lokalna Ollama** - nic nie trzeba podawac i nic nie wychodzi z komputera:

```bat
ollama pull qwen3-vl:4b-instruct
```

Model zmienisz w Ustawieniach -> Model. Alternatywa to dowolny endpoint zgodny
z OpenAI (program byl uzywany z OVH AI Endpoints): wybierz dostawce "openai", podaj
adres i klucz API. Licznik zuzycia tokenow jest w Ustawieniach, obok tego, co raportuje
dostawca - do kontroli rozliczen.

Kazdy zrzut czytany jest w dwoch skalach i wynik "glosuje"; przy rozbieznosci dochodzi
trzeci odczyt. Przedmiot z rozbieznym odczytem trafia do "do sprawdzenia", a nie do
wystawienia.

---

## Gdzie co lezy

Dane robocze powstaja obok skryptow (albo tam, gdzie wskaze zmienna `D2_DANE`):

```
screenshots/      zrzuty .png + odczyt .json + mapowanie .listing.json
cache/            definicje przedmiotow z Traderie, obrazki, wyniki price-check
game_data/        baza wyciagnieta z gry (game_extract.py)
logs/             log okna
secrets/          token Traderie i klucz API            [nie zagladac, nie commitowac]
settings.json     ustawienia (bez sekretow)
posted.json       rejestr wystawionych przedmiotow
backups/          kopie zapasowe danych (zip, bez secrets/)
sample_data/      wzorzec danych do testow (w repozytorium)
```

Ustawienia -> Strefa niebezpieczna -> "Wyczysc wszystkie dane" robi najpierw kopie
zapasowa, moze przy okazji zdjac Twoje oferty z Traderie i wymaga przepisania slowa
potwierdzenia. Sekrety, ustawienia, `cache/` i `game_data/` zostaja.

---

## Testy

```bat
.venv\Scripts\python -m pytest -q
```

88 testow, ok. 90 s. Symuluja uzytkownika w oknie (`nicegui.testing.User`), bez
przegladarki. **Nie ruszaja prawdziwych danych**: `conftest.py` przestawia `D2_DANE` na
katalog tymczasowy i rozpakowuje tam wzorzec z `sample_data/`, a Traderie i model sa
atrapami. Testy trybu lokalnego buduja sobie sztuczny zestaw tabel gry, wiec nie wymagaja
zainstalowanego D2R.

---

## Legalnosc

Czytanie plikow wlasnej, legalnie posiadanej kopii gry jest zwyklym odczytem danych
z dysku - program nie modyfikuje gry ani nie obchodzi zadnego zabezpieczenia. Ale
zawartosc gry (nazwy, tabele, grafiki) nalezy do Blizzarda, dlatego `game_data/` jest
w `.gitignore` i **nie wolno go rozpowszechniac** - kazdy robi go sobie z wlasnej
instalacji.

Traderie nie publikuje oficjalnego API; program korzysta z tego samego, co ich strona,
z opoznieniami i bez masowych zapytan. Jesli Traderie to zmieni, tryb z tokenem
przestanie dzialac - tryb lokalny nie.

---

## Licencja

Do ustalenia przez autora repozytorium. Bez pliku `LICENSE` obowiazuje domyslne
"wszystkie prawa zastrzezone", czyli formalnie nikt nie ma prawa kopiowac ani uzywac
kodu. Jesli projekt ma byc otwarty, dodaj `LICENSE` (np. MIT) i wpisz to tutaj.

---

## Dla programistow

Opis architektury, przeplyw danych, nieoficjalne API Traderie, pulapki i dlug techniczny
sa w [CLAUDE.md](CLAUDE.md).
