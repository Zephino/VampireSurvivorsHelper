# Vampire Survivors Helper

A small desktop window that shows which weapon evolutions you can make with the weapons and
passive items you currently have, so you don't have to look them up mid-run.

It reads your inventory **automatically** from the running game. It only *reads* memory and
never changes anything in the game, so it gives no gameplay advantage.

## Requirements

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

Double-click **`Start Helper.bat`** in the project folder. It starts Vampire Survivors through
Steam (unless it's already running) and opens the helper window without a console window.

Or, from a terminal in the project folder:

```bash
python -m vshelper
```

1. Begin a run in Vampire Survivors. The game and the helper can be started in either order.
2. The helper finds the game on its own. The first time after the game starts it searches memory
   for a few seconds; after that it updates about once per second.
3. The right side shows, in order:
   - **YOU'RE HOLDING**: your weapons, then your passive items.
   - **READY TO EVOLVE**: recipes you have every part for. Get the weapon to max level, then
     open a chest (usually after 10:00).
   - **HOW TO EVOLVE YOUR ITEMS**: each held item, what it evolves into, and the other parts
     it needs (green check mark = you have it, red cross = pick it up).

## Item pictures

The game's artwork isn't included in this project. The first time the helper finds your game
(through Steam, or from the running game), it copies the item pictures out of your installed game
files into `cache/icons/`. This takes up to a minute once; the bottom-right of the status bar shows
progress. It re-extracts automatically after a game update. To force a fresh extraction, delete the
`cache` folder.

Items without a matching picture just show their name. The diagnose report lists which pictures
were found.

The status bar at the bottom says what the helper is doing ("Waiting for a run to start",
"Reading game: 4 item(s) detected", etc.).

**Manual mode:** untick *Auto-detect from game* to tick items yourself (useful if detection ever
breaks after a game update). The *Filter* box searches the item list.

**Settings tab:** next to the *Items* tab. Under *Expansions*, untick any DLC you don't own to
hide its items and evolutions (all are on by default). Settings are saved to `settings.json` in
the project folder.

If Windows blocks access ("error 5"), run the helper from an administrator command prompt.

## If detection doesn't work

Detection finds the game's data by class and field *names*, not fixed addresses, so it should
survive most game updates. If it stops working or the status bar shows "Unrecognized" items:

1. Start a run in the game.
2. Double-click **`Diagnose.bat`** (or run `python -m vshelper diagnose`)
3. Share the generated `vshelper-diagnose.txt` (it contains only game class/field/item names).

Names used for detection live in `config/game_map.json`:

| Key | Meaning |
| --- | --- |
| `process_name` | Game executable name |
| `roots` | Class with a static field holding the game manager (tried in order) |
| `inventories` | Field-name path from that object to the weapon / passive lists (candidate names per step; `field[0]` means the first element of a list field, e.g. `_mainCharacters[0]` for player 1) |
| `type_field` | Field on each equipment object that identifies the item |
| `enum_classes` | Enum(s) the item type field uses |
| `enum_aliases` | Game's internal item names -> item ids in the evolution database |
| `id_map` | Extra raw value -> item id overrides (e.g. `"#42": "garlic"`) |
| `search_depth`, `search_max_objects` | Limits for the automatic search used when a path doesn't match |

## Evolution data

Recipes and item names come from the [Vampire Survivors wiki](https://vampire.survivors.wiki/Evolution)
(CC BY-SA), covering the base game and all expansions:

- A copy ships in `vshelper/data/evolutions.json`, so the helper works offline.
- About once a week the helper downloads the latest wiki data in the background to
  `cache/wiki_evolutions.json`; it's used from the next start. To update right away:
  `python -m vshelper update-data`
- The wiki is then **checked against your game files**: while extracting pictures, the helper also
  reads the game's own evolution data. Each recipe shows "✓ matches game files" or
  "⚠ game files say: ...". The diagnose report lists every mismatch.

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
- `vshelper/wiki.py`: downloads and parses the wiki's Evolution page and item lists
- `vshelper/gamedata.py`: reads the game's evolution data and compares it with the wiki
- `vshelper/settings.py`: saved user settings
- `vshelper/diagnose.py`: detection report
- `vshelper/ui.py`: the window
