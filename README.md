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

How its work : https://www.youtube.com/watch?v=Xi_YYSxKrT0

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
   py -3.11 -c "import sys, platform; print(sys.version, platform.machine())"
   ```

   You want to see `3.11.something` and `AMD64`. If you see an error instead, the installer
   step was missed - run it again and make sure the PATH box is ticked.

   **Why 3.11 and not something newer:** reading the game archive relies on a package that
   was built for Python 3.11 (64-bit) only. Everything else in the tool works on other
   versions too, but on those you would have to extract the game data by hand - see
   [Trouble with the game archive](#trouble-with-the-game-archive).

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

Reading the game archive needs the `casc` package, and step 3 of the install already pulled
it in - **as long as your Python is 3.11, 64-bit**. That package exists as a single prebuilt
file for exactly that combination and nothing else, so on Python 3.10 or 3.12 it is silently
skipped and this is the one thing that will not work. See
[Trouble with the game archive](#trouble-with-the-game-archive) - there is a way round it
that does not need 3.11.

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

Two environment variables change how it starts, if you need them: `D2_PORT` picks a port
other than 8765 (useful when something else has it, or when you want two copies side by
side), and `D2_BEZ_OKNA=1` skips the native window and leaves only the server, so you can
open it in your own browser. `D2_DANE` points the data folder somewhere else.

| file | what it does |
|---|---|
| `D2 Trade.bat` | normal start, no console window |
| `D2 Trade (console).bat` | the same with a visible console, for diagnostics |
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
py -3.11 src\game_extract.py "C:\Program Files (x86)\Diablo II Resurrected"
py -3.11 src\game_extract.py        REM looks for the game in the usual places
```

It takes a few seconds and creates `data/game_data/` (about 15 MB) with item tables,
tooltip line templates and PNG icons. After that the tool works with no network access at
all. Run it again after a game or mod update to pick up new items.

The tool **only reads** the game files. It does not modify your installation, does not launch
the game and sends nothing anywhere - `data/game_data/` stays on your disk and is in
`.gitignore`.

### Trouble with the game archive

Reading the CASC archive needs the `casc` package (a CascLib wrapper). On PyPI it exists as
**one single file**, built for Windows x64 + Python 3.11, with no source to compile from.
So:

- **on Python 3.11 (64-bit)** it installs with everything else and you need to do nothing;
- **on any other version** pip answers `No matching distribution found for casc` - which
  looks like the package does not exist, but it only means it was not built for your Python.

Check what you have:

```bat
.venv\Scripts\python -c "import sys, platform; print(sys.version, platform.machine())"
```

You want `3.11.x` and `AMD64`. If you have something else, you have two ways out, and both
work:

1. Install Python 3.11 (64-bit), delete the `.venv` folder and redo step 3 of the install.
2. Keep the Python you have and extract the game data yourself: open the game folder with
   [CascView](http://www.zezula.net/en/casc/main.html), extract the `data` folder anywhere,
   and in Settings point **Game data** at the folder that *contains* `data` instead of at the
   game. Everything else behaves exactly the same - the program reads either source.

### What exactly works without Traderie

- identifying items by name: bases, uniques, set items, runewords, runes and gems;
- splitting a tooltip into stats, including magic/rare items and crafts;
- **roll quality** - each value against the highest that stat can roll (a copy of the affix
  table ships with the repository, and extracting your own game replaces it with one that
  also knows the affixes your mod adds);
- the item icon taken from the game instead of Traderie's CDN;
- the **d2jsp sale post**, with prices in runes and/or FG;
- the "where is it" field (character and stash tab), filtering, paging, light/dark theme.

What you do not get without a token: prices from trades, and listing items. Where a price
would go, the tool explains why there is none. An item identified locally is marked `local`
in its listing and **cannot be listed** - its property ids are generated locally rather than
taken from Traderie's database, so the offer would be wrong. Paste a token and re-read the
screenshot to list it.

## Where things live

The repository holds three folders and the launchers:

```
D2 Trade.bat              start the window
D2 Trade (console).bat    the same with a console, for diagnostics
Extract game data.bat     build the local database from the game files

src/        the program: modules, lang/ (translations), affixes_data.json
tests/      the test suite and sample_data/ (the fixture it runs against)
docs/       CLAUDE.md (developer notes) and the theme mockup
```

**`data/` is not in the repository** - it does not exist until you run the program,
and then it holds everything the program makes. That is your stash, your offers and
your token, so it is in `.gitignore` and never gets pushed anywhere:

```
data/
  screenshots/      .png captures + .json reads + .listing.json mappings   [on start]
  cache/            item definitions from Traderie, images, price-check    [on start]
  logs/             window log                                             [on start]
  secrets/          Traderie token and API key                             [on start]
  game_data/        the database extracted from the game       [after Extract game data]
  backups/          data backups (zip, without secrets/)       [at the first backup]
  settings.json     settings (no secrets)                      [when you press Save]
  posted.json       register of listed items                   [at the first listing]
```

The four marked `[on start]` are created the moment you launch the program, even before
you do anything - so you can see straight away where your screenshots will land. The rest
appear when they are first needed.

Everything you care about is in that one folder, so backing the tool up means copying
`data/`. Set the `D2_DANE` environment variable to put it somewhere else - that is how
the tests get their own throwaway copy. If you are upgrading from an older version where
these files sat loose in the project folder, the program moves them into `data/` on the
next start.

Settings -> Danger zone -> "Clear all data" takes a backup first, can optionally pull your
offers from Traderie on the way out, and refuses to run until you type a confirmation word.
Secrets, settings, `cache/` and `game_data/` are kept.

## Tests

```bat
.venv\Scripts\python -m pytest -q
```

97 tests, about 100 s. They drive the real UI through `nicegui.testing.User`, without a
browser, plus one that launches the program the way the .bat does and waits for it to
answer - importing a module is not the same as starting it. They **never touch real data**: `conftest.py` points `D2_DANE` at a temporary
directory and unpacks the `tests/sample_data/` fixture there, and both Traderie and the model are
stubbed out. The local-mode tests build their own synthetic game tables, so they do not need
D2R installed.

---

## Legal notes

Reading the files of your own, legally owned copy of the game is an ordinary disk read - the
tool does not modify the game and does not circumvent any protection. The game's content
(names, tables, artwork) belongs to Blizzard, which is why `data/` is in `.gitignore`
and **must not be redistributed** - everyone generates it into their own `data/` folder.

Traderie publishes no official API; this tool uses the same endpoints its website does, with
delays and without bulk querying. If Traderie changes that, the token mode stops working -
the local mode does not.

## License

[MIT](LICENSE) - you may use, modify and redistribute this code, including commercially, as
long as the copyright notice stays in place.

The licence covers the source code of D2 Trade only. Diablo II: Resurrected and all of its
content - item names, data tables and artwork - belong to Blizzard Entertainment. This project
neither contains nor redistributes any of it: `game_data/` is generated on each user's own
machine from their own copy of the game and is excluded from version control.
