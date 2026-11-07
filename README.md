# Vampire Survivors Helper

A small desktop window that shows which weapon evolutions you can make with the weapons and
passive items you currently have, so you don't have to look them up mid-run.

It reads your inventory **automatically** from the running game. It only *reads* memory and
never changes anything in the game, so it gives no gameplay advantage.

## Requirements

- Windows 10/11 (64-bit) with the Steam version of Vampire Survivors
- [Python 3.10 or newer](https://www.python.org/downloads/) (tick "Add python.exe to PATH" when
  installing; tkinter is included by default)

No extra packages are needed.

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
3. Evolutions are listed on the right:
   - **READY**: you have every part. Get the weapon to max level, then open a chest after 10:00.
   - **ONE ITEM AWAY**: what to pick up next.
   - **OTHER EVOLUTIONS FOR YOUR ITEMS**: longer-term options.

The status bar at the bottom says what the helper is doing ("Waiting for a run to start",
"Reading game: 4 item(s) detected", etc.).

**Manual mode:** untick *Auto-detect from game* to tick items yourself (useful if detection ever
breaks after a game update). The *Filter* box searches the item lists.

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
| `inventories` | Field-name path from that object to the weapon / passive lists (candidate names per step) |
| `type_field` | Field on each equipment object that identifies the item |
| `enum_classes` | Enum(s) the item type field uses |
| `enum_aliases` | Game's internal item names -> item ids in the evolution database |
| `id_map` | Extra raw value -> item id overrides (e.g. `"#42": "garlic"`) |
| `search_depth`, `search_max_objects` | Limits for the automatic search used when a path doesn't match |

## Evolution data

All recipes are in `vshelper/data/evolutions.json` and can be edited. Entries marked
`"verified": false` (mostly DLC) should be double-checked in game; the app labels them
"unverified".

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
- `vshelper/diagnose.py`: detection report
- `vshelper/ui.py`: the window
