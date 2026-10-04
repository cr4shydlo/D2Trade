# D2 Trade

A selling assistant for **Diablo II: Resurrected**. You take a screenshot in game, the tool
reads the tooltip with a vision model, identifies the item, rates how well it rolled and
prepares the offer: either on [Traderie](https://traderie.com/diablo2resurrected) or as a
ready-to-paste BBCode post for d2jsp.

```
F12 in game  ->  read the tooltip  ->  identify the item  ->  roll quality and price
                                                           ->  listing on Traderie
                                                           ->  d2jsp post (BBCode)
```

The interface ships in Polish, English, German and Korean (Settings -> Language). Item and
stat names stay in English, because that is what the game and Traderie call them.

---

## What this tool does not do

It is not a bot, and it is not meant to become one.

- **It does not automate the game.** It only reads screenshots that you take yourself with
  F12. It sends no keystrokes or clicks to the game, does not read its memory and does not
  touch its files.
- **It does not automate d2jsp.** The d2jsp rules (section 20) forbid automation, so the tool
  only generates BBCode for you to paste and opens the thread in your browser.
- **It never sets a price for you.** It shows levels taken from real trades; you approve the
  price. When there is not enough data it says so instead of guessing - a missing price is
  better than a misleading one.

Traderie is accessed through the same (unofficial) API its own website uses, with a random
45-90 s pause between listings.

---

## What you need

| | |
|---|---|
| OS | Windows (the global F12 hotkey and screen capture are Windows-only) |
| Python | 3.11 (`py -3.11`) |
| Vision model | **either** a local [Ollama](https://ollama.com) on your own GPU, **or** an OpenAI-compatible endpoint |
| Traderie account | **optional** - see "Three ways to run it" |
| D2R installed | optional, but without a Traderie token this is where item data comes from |

### Install

```bat
git clone <repository-url> d2trade
cd d2trade
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

To run it, double-click **`D2 Trade.bat`**. The window opens at `http://127.0.0.1:8765`
(as a native window if `pywebview` is installed). `D2 Trade (z konsola).bat` does the same
with a visible console, for diagnostics.

The `.bat` files prefer the project's `.venv` and fall back to `py -3.11`. The project
directory can live anywhere and can be moved - every path in the code is relative.

---

## Three ways to run it

The tool works with no credentials at all; the more you give it, the more it can do.

| | reading screenshots | items, stats, icons | roll quality | prices from trades | listing on Traderie | d2jsp post |
|---|---|---|---|---|---|---|
| **1. Nothing configured** | local Ollama | *none* | - | - | - | - |
| **2. Game folder** | local Ollama | from game files | yes | - | - | **yes** |
| **3. + Traderie token** | Ollama or cloud | from Traderie | yes | **yes** | **yes** | yes |

**Mode 2 answers the obvious question: where do stats and images come from without Traderie?**
Everything needed is already in the game files on your disk - item names, unique item ranges,
the affix tables and the inventory icons. They only have to be read once.

### Building the local database

Double-click **`Wyciagnij dane z gry.bat`** ("extract game data") or run:

```bat
py -3.11 game_extract.py "C:\Program Files (x86)\Diablo II Resurrected"
py -3.11 game_extract.py        REM looks for the game in the usual places
```

It takes a few seconds and creates a `game_data/` folder (about 15 MB) with item tables,
tooltip line templates and PNG icons. After that the tool works with no network access at
all. Run it again after a game or mod update to pick up new items.

The tool **only reads** the game files. It does not modify your installation, does not launch
the game and sends nothing anywhere - `game_data/` stays on your disk and is in `.gitignore`.

Reading the CASC archive needs the `casc` package (a CascLib wrapper):

```bat
py -3.11 -m pip install casc
```

That package only ships a prebuilt wheel for Windows x64 + Python 3.11. If you cannot install
it, extract the game's `data` folder with any CASC tool (CascView, for example) and point
`game_extract.py` at that folder instead - everything else works the same.

### What exactly works without Traderie

- identifying items by name: bases, uniques, set items, runewords, runes and gems;
- splitting a tooltip into stats, including magic/rare items and crafts;
- **roll quality** - each value against the highest that stat can roll (`affixes_data.json`
  is in the repository, so this works out of the box);
- the item icon taken from the game instead of Traderie's CDN;
- the **d2jsp sale post**, with prices in runes and/or FG;
- the "where is it" field (character and stash tab), filtering, paging, light/dark theme.

What you do not get without a token: prices from trades, and listing items. Where a price
would go, the tool explains why there is none. An item identified locally is marked `local`
in its listing and **cannot be listed** - its property ids are generated locally rather than
taken from Traderie's database, so the offer would be wrong. Paste a token and re-read the
screenshot to list it.

### Adding a Traderie token

Settings -> Traderie account. The token is the `Authorization` header from your browser's
DevTools (Network tab, **Raw** view - the formatted view truncates it with an ellipsis).
It is stored in `secrets/traderie_auth.txt`, together with the cloud model's API key. The
whole `secrets/` folder is in `.gitignore` and **never** ends up in `settings.json` or in a
backup.

---

## The vision model

By default it uses **local Ollama** - nothing to configure and nothing leaves your machine:

```bat
ollama pull qwen3-vl:4b-instruct
```

You can change the model in Settings -> Model. The alternative is any OpenAI-compatible
endpoint (this has been used with OVH AI Endpoints): pick the "openai" provider, then give it
a URL and an API key. Token usage is tracked in Settings next to what the provider reports,
so you can check the billing.

Every screenshot is read at two scales and the results vote; on disagreement a third read
breaks the tie. An item with a disputed read goes to "needs review" rather than straight to
listing.

---

## Where things live

Working data is created next to the scripts, or wherever the `D2_DANE` environment variable
points:

```
screenshots/      .png captures + .json reads + .listing.json mappings
cache/            item definitions from Traderie, images, price-check results
game_data/        the database extracted from the game (game_extract.py)
logs/             window log
secrets/          Traderie token and API key          [do not open, do not commit]
settings.json     settings (no secrets)
posted.json       register of listed items
backups/          data backups (zip, without secrets/)
sample_data/      the test fixture (in the repository)
```

Settings -> Danger zone -> "Wipe all data" takes a backup first, can optionally pull your
offers from Traderie on the way out, and refuses to run until you type a confirmation word.
Secrets, settings, `cache/` and `game_data/` are kept.

---

## Tests

```bat
.venv\Scripts\python -m pytest -q
```

91 tests, about 90 s. They drive the real UI through `nicegui.testing.User`, without a
browser. They **never touch real data**: `conftest.py` points `D2_DANE` at a temporary
directory and unpacks the `sample_data/` fixture there, and both Traderie and the model are
stubbed out. The local-mode tests build their own synthetic game tables, so they do not need
D2R installed.

---

## Legal notes

Reading the files of your own, legally owned copy of the game is an ordinary disk read - the
tool does not modify the game and does not circumvent any protection. The game's content
(names, tables, artwork) belongs to Blizzard, which is why `game_data/` is in `.gitignore`
and **must not be redistributed** - everyone generates it from their own installation.

Traderie publishes no official API; this tool uses the same endpoints its website does, with
delays and without bulk querying. If Traderie changes that, the token mode stops working -
the local mode does not.

---

## License

To be decided by the repository owner. With no `LICENSE` file the default is "all rights
reserved", which formally means nobody may copy or use the code. If this is meant to be open
source, add a `LICENSE` (MIT, for example) and say so here.

---

## For developers

The architecture, data flow, the unofficial Traderie API, the traps worth knowing and the
technical debt are documented in [CLAUDE.md](CLAUDE.md). That file is in Polish, like the code
comments - it is the working notebook for this project rather than user-facing documentation.
