# Fantasy UFC — setup

You don't need to understand any of the code. You need to get Python
installed, put these files in a folder, and run two commands.

## 1. Install Python

**Mac** — open Terminal (Cmd+Space, type "Terminal") and run:

    python3 --version

If it prints something like `Python 3.11.x` you already have it. If not,
download it from python.org and run the installer.

**Windows** — install Python from the Microsoft Store, or from python.org.
If you use the python.org installer, **tick "Add Python to PATH"** on the
first screen. Then open PowerShell and run `python --version` to confirm.

Below, Mac users type `python3` and Windows users type `python`.

## 2. Put the files somewhere

Make a folder called `ufc-fantasy` (Desktop is fine) and put everything in
it, keeping the `sources` folder as its own folder inside:

    ufc-fantasy/
      check_sources.py
      scoring.py
      names.py
      load_season.py
      schema.sql
      test_names.py
      sources/
        __init__.py
        http.py
        ufc.py
        mmadec.py

## 3. Open a terminal in that folder

**Mac** — right-click the folder, "New Terminal at Folder". Or type `cd `
(with the space) in Terminal and drag the folder onto the window, then Enter.

**Windows** — open the folder, click the address bar, type `powershell`,
press Enter.

## 4. Install the two libraries

    python3 -m pip install requests beautifulsoup4

(Windows: `python -m pip install requests beautifulsoup4`)

## 5. Run the check

    python3 check_sources.py

This visits UFC.com and MMA Decisions, saves what it downloads into a
`cache` folder, and tells you whether the parsers understood the pages.

## What you should see

Lines starting with `[  OK  ]` mean that part works. You want to see bouts
listed under UFC.com, and a set of judges with round scores under MMA
Decisions.

`[ FAIL ]` or `[ WARN ]` lines name a file inside `cache/`. **Send me that
file.** I wrote these parsers without being able to see the real pages, so
the first run is genuinely a test — if something doesn't parse, the saved
HTML is exactly what I need to fix it, and it's a quick fix rather than a
redesign.

Nothing here writes to the internet or logs into anything. It only reads
public pages, and it waits 1.5 seconds between requests so we're a polite
visitor.

## Optional: re-run the 2025 verification

    python3 load_season.py

This needs `verified.json` and `league.json`, which are built from your
spreadsheet. It reproduces the season we already checked. Not required —
it's just there so you can see the standings come out of the database
rather than take my word for it.
