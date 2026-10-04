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

# Getting started (no experience needed)

If you have never run a Python program before, follow these steps in order. It takes about
fifteen minutes, most of which is downloading. You need Windows and a copy of
Diablo II: Resurrected.

## Step 1 - install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/release/python-3119/) and
   download **Python 3.11** for Windows (the "Windows installer (64-bit)" file).
   Version 3.11 matters - newer versions are not supported by all the libraries used here.
2. Run the installer. On the first screen tick **"Add python.exe to PATH"** at the bottom,
   then click "Install Now".
3. To check it worked, press `Win + R`, type `cmd`, press Enter, and in the black window type:

   ```
   py -3.11 --version
   ```

   You should see `Python 3.11.something`. If you see an error, the installer step was
   missed - run it again and make sure the PATH box is ticked.

## Step 2 - download this project

**Easiest way:** on the project page click the green **Code** button -> **Download ZIP**.
Unpack it anywhere, for example `C:\D2Trade`. Avoid folders synced by OneDrive - the tool
writes files constantly and syncing slows it down.

**If you have git:**

```bat
git clone <repository-url> C:\D2Trade
```

## Step 3 - install the libraries

Open the folder you unpacked, click the address bar at the top of the window, type `cmd` and
press Enter. A black window opens, already in the right folder. Paste this and press Enter:

```bat
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

The first line creates a private Python environment inside the project folder, so nothing is
installed system-wide. The second downloads the libraries - a few minutes.

## Step 4 - install the model that reads screenshots

The tool needs a vision model to read item tooltips. The simplest option runs on your own
graphics card and costs nothing:

1. Download and install [Ollama](https://ollama.com/download).
2. In the black window type:

   ```bat
   ollama pull qwen3-vl:4b-instruct
   ```

   That downloads about 3 GB. You need a graphics card with roughly 6 GB of memory. **Close
   the game while reading screenshots** - the game and the model compete for the same card.

If your card is too small, you can use a cloud provider instead (Settings -> Model -> provider
"openai", then paste the endpoint URL and your API key). That costs money per image.

## Step 5 - first run

Double-click **`D2 Trade.bat`**. A window opens. It is empty - that is expected.

Now tell it where your game is, so it can recognise items:

1. Click **Settings** in the left sidebar.
2. Find the **Game data** section. The folder is usually filled in already; if not, paste the
   path to your installation, for example `C:\Program Files (x86)\Diablo II Resurrected`.
3. Click **Extract game data** and wait a few seconds. You should see
   *"database ready: 1355 items, 375 icons"*.
4. Click **Save**.

Reading the game archive needs one extra package. If step 3 complains about it, type this in
the black window and try again:

```bat
.venv\Scripts\python -m pip install casc
```

If that package will not install on your machine, see
[Trouble with the game archive](#trouble-with-the-game-archive) below.

## Step 6 - sell something

1. Start the game, hover the mouse over an item in your stash and press **F12**. Nothing
   visible happens - the tool saved a screenshot in the background. Do this for every item
   you want to sell.
2. **Close the game** (the model needs the graphics card).
3. In the D2 Trade window click **Read screenshots**. Each item appears in the list with its
   stats and a rating of how well it rolled.
4. Switch to the **d2jsp post** view and click **Copy sales post**. Paste it into your d2jsp
   thread.

That is the whole loop. Everything above works without any account anywhere.

## Step 7 (optional) - connect Traderie

Only needed if you want **prices from real trades** and **listing items automatically**.

1. Log in to [traderie.com](https://traderie.com/diablo2resurrected) in your browser.
2. Press `F12` in the browser to open developer tools, go to the **Network** tab and reload
   the page.
3. Click any request to `traderie.com`, find the **Authorization** header and switch the view
   to **Raw** - the formatted view cuts the value off with "...".
4. Copy the whole line and paste it into Settings -> Traderie account -> Token.
5. Paste your account id into the field above it. You will find it in the address of your own
   listings page, after `seller=`.
6. Click **Test connection**. It should say how many active offers you have.

The token expires every few days; when it does, repeat these steps.

---

# Reference

## What you need

| | |
|---|---|
| OS | Windows (the global F12 hotkey and screen capture are Windows-only) |
| Python | 3.11 (`py -3.11`) |
| Vision model | **either** a local [Ollama](https://ollama.com) on your own GPU, **or** an OpenAI-compatible endpoint |
| Traderie account | **optional** - see below |
| D2R installed | optional, but without a Traderie token this is where item data comes from |

The `.bat` files prefer the project's `.venv` and fall back to `py -3.11`. The project folder
can live anywhere and can be moved - every path in the code is relative.

| file | what it does |
|---|---|
| `D2 Trade.bat` | normal start, no console window |
| `D2 Trade (console).bat` | the same with a visible console, for diagnostics |
| `D2 Trade (old window).bat` | the older tkinter window, kept as a fallback |
| `Extract game data.bat` | builds the local database from the game files |

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

## Building the local database

Settings -> Game data -> **Extract game data**, or from the command line:

```bat
py -3.11 game_extract.py "C:\Program Files (x86)\Diablo II Resurrected"
py -3.11 game_extract.py        REM looks for the game in the usual places
```

It takes a few seconds and creates a `game_data/` folder (about 15 MB) with item tables,
tooltip line templates and PNG icons. After that the tool works with no network access at
all. Run it again after a game or mod update to pick up new items.

The tool **only reads** the game files. It does not modify your installation, does not launch
the game and sends nothing anywhere - `game_data/` stays on your disk and is in `.gitignore`.

### Trouble with the game archive

Reading the CASC archive needs the `casc` package (a CascLib wrapper), which only ships a
prebuilt wheel for Windows x64 + Python 3.11. If it will not install, extract the game's
`data` folder with any CASC tool ([CascView](http://www.zezula.net/en/casc/main.html), for
example) and point the tool at **that** folder instead - everything else works the same.

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

Settings -> Danger zone -> "Clear all data" takes a backup first, can optionally pull your
offers from Traderie on the way out, and refuses to run until you type a confirmation word.
Secrets, settings, `cache/` and `game_data/` are kept.

## Tests

```bat
.venv\Scripts\python -m pytest -q
```

95 tests, about 100 s. They drive the real UI through `nicegui.testing.User`, without a
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

## License

[MIT](LICENSE) - you may use, modify and redistribute this code, including commercially, as
long as the copyright notice stays in place.

## For developers

The architecture, data flow, the unofficial Traderie API, the traps worth knowing and the
technical debt are documented in [CLAUDE.md](CLAUDE.md). That file is in Polish, like the code
comments - it is the working notebook for this project rather than user-facing documentation.
