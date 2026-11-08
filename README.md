# Vampire Survivors Helper

A small desktop window that shows which weapon evolutions you can make with the weapons and
passive items you currently have, so you don't have to look them up mid-run.

It reads your inventory **automatically** from the running game. It only *reads* memory and
never changes anything in the game, so it gives no gameplay advantage.

## For friends: just run the exe

Download **VampireSurvivorsHelper.exe** from the
[latest release](https://github.com/Zephino/VampireSurvivorsHelper/releases/latest) and double-click
it. Nothing else to install. Windows may show "Windows protected your PC" because the exe isn't
signed: click **More info > Run anyway**. Some antivirus programs are wary of new exes that read
another program's memory; the helper only *reads* the game and never changes it.

The exe saves its settings and picture cache in `%LOCALAPPDATA%\VampireSurvivorsHelper`.
Settings > Updates updates the exe itself: *Check for updates* looks at the latest GitHub release,
*Update now* downloads the new exe and swaps it in (the old one is renamed to
`VampireSurvivorsHelper.old.exe` and deleted on the next start), then *Restart helper*. Only the
single exe stays in the folder. Settings > Troubleshooting >
**Create diagnose report** makes the report to send if detection doesn't work.

## Building the exe (for sharing)

- **Automatically:** whenever `VERSION` changes on `main`, the GitHub Actions workflow
  (`.github/workflows/build-exe.yml`) builds the exe on Windows, runs the tests and publishes it as
  a release. You can also start it by hand from the repository's **Actions** tab.
- **On your PC:** double-click **`Build Exe.bat`**. It installs PyInstaller (build tool only,
  `requirements-build.txt`) and writes `dist\VampireSurvivorsHelper.exe`, then opens that folder.
  The recipe is `VampireSurvivorsHelper.spec`.

## Requirements (running from source)

- Windows 10/11 (64-bit) with the Steam version of Vampire Survivors
- [Python 3.10 or newer](https://www.python.org/downloads/) (tick "Add python.exe to PATH" when
  installing; tkinter is included by default)

One extra package, **UnityPy**, is used to show item pictures (it also installs Pillow).
`Start Helper.bat` installs it automatically the first time. To install it by hand:

```bash
python -m pip install --user -r requirements.txt
```

Without it the helper still works, just without pictures.

## Running

Double-click **`Start Helper.bat`** in the project folder. It opens the helper window without a
console window; the helper then starts Vampire Survivors (see below).

Or, from a terminal in the project folder:

```bash
python -m vshelper
```

1. The helper starts Vampire Survivors through Steam when it opens (Settings > Game >
   *Start Vampire Survivors when the helper opens*, on by default), and the
   **▶ Launch Vampire Survivors** button at the right end of the tab row starts it any time. Begin a run.
2. The helper finds the game on its own. The first time after the game starts it searches memory
   for a few seconds; after that it updates about once per second.
3. The right side has three tabs:
   - **Overview**: what you're holding as item cards (picture, level, name; weapons, then
     passive items) and what is
     **ready to evolve**. Get the weapon to max level, then open a chest (usually after 10:00).
     Below that, **what your items evolve into**: one line per evolution of each held weapon,
     with the parts you have or still need.
   - **How to evolve**: each held item, what it evolves into, and the other parts it needs
     (green check mark = you have it, red cross = pick it up; READY / LEVEL UP tags).
   - **All evolutions**: every recipe in the game, grouped by expansion and type (evolutions,
     unions, gifts, morphs), with a search box. Items you hold are green; hidden expansions are
     left out. Each recipe says which characters start with its weapon, and the search box also
     finds character names (e.g. "Cornell" shows the recipes for his starting weapons).

## Updating

Open **Settings > Updates** and click **Check for updates**, then **Update now** and
**Restart helper**. By default the helper also checks when it starts and says so in the status
bar when an update is available. This uses Git (installed with Git for Windows), so it only works
for a copy that was downloaded with `git clone`; if packages in `requirements.txt` changed, they
are installed too. You can also update by hand with `git pull` in the project folder.

## Item pictures

The game's artwork isn't included in this project. The first time the helper finds your game
(through Steam, or from the running game), it copies the item pictures out of your installed game
files into `cache/icons/`. This takes up to a minute once; the bottom-right of the status bar shows
progress. It re-extracts automatically after a game update. To force a fresh extraction, delete the
`cache` folder.

During a run the helper also reads the game's own item catalogue from memory (the name and
picture of every item, DLC included) into `cache/game_catalog.json`, and then extracts the
pictures it was missing once more in the background.

Any item still without a picture is then downloaded from the wiki (`Sprite-<name>.png`, about a
minute for all of them; Settings > Detection > *Download missing item pictures from the wiki*,
on by default). This also works when the game isn't installed or found. Each item is only asked
about once a week; the record is kept in `cache/icons/wiki_icons.json`.

Items without a matching picture just show their name. The diagnose report lists which pictures
were found.

The status bar at the bottom says what the helper is doing ("Waiting for a run to start",
"Reading game: 4 item(s) detected", etc.).

**Tabs:** Overview, How to evolve, All evolutions and Settings sit in one row across the window.
Text and buttons wrap onto the next line when the window is made narrow.

**Detection (Settings):** *Auto-detect items from the game* is on by default. While it is on, the
item list on the left of **Overview** is hidden so the results use the full width (switch off
*Hide the item list while auto-detect is on* to keep it). Turn auto-detect off to tick your items
yourself in that list (with Clear and a Search box on top; it searches item and expansion names).

**Co-op:** when more than one player is in the game, a bar above the tabs shows
*Show items of: Player 1 (you) | Player 2 | ...*. Pick a friend to see their items, levels, what
they can evolve and what they still need on Overview and How to evolve. (Local co-op is read
from your PC's game; for online co-op it depends on what the game keeps of other players.)

**Planning ahead:** with auto-detect on and the list shown, tick items you *don't* have yet. They
appear as **planned** (blue border) on Overview and How to evolve, so you can see what they would
evolve into and what else you'd need; combos that rely on them are listed under "With your planned
items" with a PLANNED badge. Detected items stay ticked; Clear removes only planned items, and a
planned item you then pick up in the game simply becomes detected.

**Settings tab:** *Appearance* has the **Dark theme** switch (on by
default; changes apply instantly). *Main screen* switches parts of the results on or off:
Overview's You're holding and Ready to evolve, the How to evolve tab, items with no evolution,
item levels, details, game-file check marks and item pictures (all on by default). Under *Expansions*, untick any DLC you don't own to hide its
items and evolutions (all are on by default). Settings are saved to `settings.json` in
the project folder.

If Windows blocks access ("error 5"), run the helper from an administrator command prompt.

## If detection doesn't work

Detection finds the game's data by class and field *names*, not fixed addresses, so it should
survive most game updates. If it stops working or the status bar shows "Unrecognized" items:

1. Start a run in the game.
2. Double-click **`Diagnose.bat`** (or run `python -m vshelper diagnose`)
3. Share `vshelper-diagnose.txt`, which is saved on your Desktop. It contains the helper's setup (versions, game
   folder), the game's class layouts, your current items, the game's item data, which pictures are
   missing, and the wiki-vs-game check; no personal data apart from the game's install folder.
   Each part catches its own errors, so the report is written even if something fails.

Names used for detection live in `config/game_map.json`:

| Key | Meaning |
| --- | --- |
| `process_name` | Game executable name |
| `roots` | Class with a static field holding the game manager (tried in order) |
| `inventories` | Field-name path from that object to the weapon / passive lists (candidate names per step; `field[0]` means the first element of a list field, e.g. `_mainCharacters[0]` for player 1) |
| `name_paths` | Paths from an equipment object to its name (e.g. `_currentWeaponData` -> `name`); tried first |
| `type_field` | Field on each equipment object holding its item-type number (fallback) |
| `level_field`, `max_level_field` | Fields with the item's level and max level, shown as "Lv 5/8" |
| `enum_classes` | Enum(s) the item type field uses |
| `enum_aliases` | Game's internal item names -> item ids in the evolution database |
| `id_map` | Extra raw value -> item id overrides (e.g. `"#42": "garlic"`) |
| `search_depth`, `search_max_objects` | Limits for the automatic search used when a path doesn't match |

## Evolution data

Recipes and item names come from the [Vampire Survivors wiki](https://vampire.survivors.wiki/Evolution)
(CC BY-SA), covering the base game and all expansions: the Evolution page plus every weapon's own
page (some recipes, such as character morphs, are only listed there):

- A copy ships in `vshelper/data/evolutions.json`, so the helper works offline.
- About once a week the helper downloads the latest wiki data in the background to
  `cache/wiki_evolutions.json`; it's used from the next start. To update right away:
  `python -m vshelper update-data`
- The wiki is then **checked against your game files**: while extracting pictures, the helper also
  reads the game's own evolution data. Each recipe shows "✓ matches game files" or
  "⚠ game files say: ...". The diagnose report lists every mismatch.

**Items without a known recipe** (or that the helper doesn't recognise) are looked up on their own
wiki page automatically while you hold or plan them (Settings > Detection > *Look up items without
a known recipe on the wiki*, on by default). Found recipes are added straight away and listed
under "Found on the wiki" in All evolutions; answers are kept in `cache/wiki_lookups.json` for a
week. If the wiki has nothing either, How to evolve says so with an *Open wiki page* link.

A few wiki recipes have conditions that aren't items (e.g. Candybox needs max-level passives and
evolutions) and are left out; `update-data` prints them. Emerald Diorama evolutions that need a
Glimmer show "Also needs: <Glimmer>".

Developers: `python -m vshelper update-data --bundled` refreshes the bundled copy.

## Development

Run the tests (they use a simulated game memory layout, so they work on any OS):

```bash
python -m unittest -v
```

Project layout:

- `vshelper/data.py`: loads and validates the evolution database
- `vshelper/evolutions.py`: works out ready / nearly-ready evolutions
- `vshelper/memory/winapi.py`: read-only Windows process memory access
- `vshelper/memory/il2cpp.py`: finds Unity IL2CPP classes, fields and objects by name
- `vshelper/memory/game.py`: reads the inventory using `config/game_map.json`
- `vshelper/icons.py`: finds the game install and extracts item pictures (and the game's evolution data)
- `vshelper/wiki.py`: downloads and parses the wiki's Evolution page, item lists and single item pages
- `vshelper/lookups.py`: per-item wiki lookups (cache and adding found recipes)
- `vshelper/gamedata.py`: reads the game's evolution data and compares it with the wiki
- `vshelper/settings.py`: saved user settings
- `vshelper/updater.py`: checks for and installs updates (git from source, version check for the exe)
- `vshelper/paths.py`: where bundled files are read and user files are saved (source vs exe)
- `run_helper.py`, `VampireSurvivorsHelper.spec`: entry point and build recipe for the exe
- `vshelper/diagnose.py`: detection report
- `vshelper/ui.py`: the window
