# Changelog

## Version 00.09.00
Date: 11/07/2026
Time: 3:09 PM

### Changes
- Added a "Main screen" group to Settings with switches for what the results pane shows: You're holding, Ready to evolve, How to evolve your items, items with no evolution, item levels (Lv x/y, LEVEL UP and "level up first"), details (max level, notes), game-file check marks and item pictures (also in the item list). All on by default, applied instantly and saved in `settings.json`.
- The Settings tab now scrolls, so every group stays reachable as more settings are added.
- Settings loading now falls back to the default for each value that is missing or has the wrong type, instead of all-or-nothing.
- Added tests for the new settings; updated the README.

### Reason
User asked for a way in Settings to toggle what is shown on the main screen.

## Version 00.08.00
Date: 11/07/2026
Time: 3:07 PM

### Changes
- Added a dark theme, on by default, with a "Dark theme" switch under Settings > Appearance. It applies instantly and covers the tabs, item list, buttons, checkboxes, filter box, results pane (including the have / need / level colours), scrollbars and status bar. Turning it off restores the native Windows look.
- The choice is saved in `settings.json` (`dark_theme`); added tests for the default and saving it.
- README: documented the Appearance setting.

### Reason
User asked for a dark theme that can be toggled in Settings and is on by default.

## Version 00.07.01
Date: 11/07/2026
Time: 3:06 PM

### Changes
- Passive items now show even when you hold more than 12: inventory paths from the game map are trusted at any size. The 12-item limit only applies to lists found by the automatic search (item pools, pickups).
- Internal game names are worked out even when both parts of a recipe are unknown (the recipe's key is the base weapon, the rest is the passive). This resolves the last three false wiki "mismatches" (Emergency Meeting, Paranormal Scan, Rocket Science).
- Test lists can hold more items; added tests for both fixes.

### Reason
The user's latest diagnose report showed detection working for weapons, but all 17 held passives were dropped by the 12-item limit, and three recipes were still reported as mismatches.

## Version 00.07.00
Date: 11/07/2026
Time: 3:00 PM

### Changes
- The diagnose report now collects everything needed for troubleshooting in one file: setup (helper, Python, Windows, admin, UnityPy versions, game folder and build), settings and cache files, class layouts of the key game classes (characters, weapon/accessory managers, equipment, WeaponData and more), static fields, item enums, detection result with levels, every held item with all its fields and data objects, all candidate item lists, related metadata names, the game's internal item names with their mapping and picture names, and similar game sprite names for every item without a picture.
- Each report section catches its own errors and writes them into the report, so one failure no longer stops the report.
- `Diagnose.bat` now explains the steps, waits for a key press while you start a run, and opens the folder with the report selected.
- Picture extraction also saves the game's sprite names (`cache/icons/sprite_names.txt`) and the picture name of each item from the game data, and uses those to find more pictures. Existing installs extract once more after updating.

### Reason
User asked for Diagnose.bat to gather everything that might be needed, such as the full game structure and item data.

## Version 00.06.00
Date: 11/07/2026
Time: 2:55 PM

### Changes
- Items are now identified by name from the item's data object (`_currentWeaponData` / `CurrentAccessoryData`, field `name`), with a fallback that searches the item's *Data objects for any text naming a known item. The user's report showed the `WeaponType` enum values are not 0, 1, 2... (e.g. 1433), so enum numbers are only used when listed in `id_map` and are otherwise reported as `#number`.
- Reads each item's level and max level (`Level` / `LevelsNumber`). Held items show "Lv 5/8"; a recipe whose parts aren't maxed shows an orange LEVEL UP tag and "level up first: Knife 5/8" instead of READY.
- In auto-detect mode the results use exactly the detected items, including items that aren't part of any recipe.
- New `game_map.json` keys `name_paths`, `level_field` and `max_level_field`; `_equipmentType` added to `type_field`.
- The diagnose report shows each item's data object and its identified name and level.
- The test fake now models the real equipment objects (enum number, WeaponData name, levels); added tests.

### Reason
The user's second diagnose report showed the helper now reaches the player's real weapons and accessories but couldn't identify them, because the game's item-type numbers don't follow the enum's declaration order.

## Version 00.05.00
Date: 11/07/2026
Time: 2:47 PM

### Changes
- Fixed inventory detection using the user's diagnose report: the player is now found at `GM.Core._mainCharacters[0]` (namespace `VampireSurvivors.Framework`), then the weapon / accessory managers, then `ActiveEquipment`. Path steps can now index into lists (`field[0]`), and the automatic search looks inside lists of objects such as the players list.
- Item numbers are only translated with the `WeaponType` enum; `ItemType` (pickups like coins and gems) was causing wrong items.
- Lists under the game's cheat-code, stats, tileset and weighted-store objects are rejected as inventories.
- Internal game names without a display name (e.g. `C1_SHRINK_GUARDI`, `REVIVAL`) are worked out from recipes by elimination. This removes the false "mismatch" results and lets auto-detect recognise those items.
- The diagnose report no longer crashes at the end (a variable was reused), walks each inventory path step by step showing every object's fields and how each item was identified, and lists up to 3000 related names.
- The test fake now mirrors the real game layout; added tests for list-index paths, the players-list search, name elimination and an end-to-end diagnose run.

### Reason
The user's diagnose report showed the helper was reading a list from the game's cheat-code system instead of the player's inventory, and the diagnose script crashed at the end.

## Version 00.04.00
Date: 11/07/2026
Time: 2:39 PM

### Changes
- Results are now built around what you're holding: "YOU'RE HOLDING" (weapons, then passive items), "READY TO EVOLVE", then "HOW TO EVOLVE YOUR ITEMS", which lists each held item with its evolutions and the other parts needed (have or need). Replaces the "one item away" and "other evolutions" lists. The results pane now has a scrollbar.
- Memory detection is stricter about which list is your inventory: lists with more than 12 items are rejected (also while playing), list paths through names like pickup, drop, pool, available, chest or level-up are rejected, and paths through player, equipment, weapon or accessory names are preferred.
- The diagnose report lists every candidate list with its score and items, and shows the new results text.
- Added tests for the held-items view and inventory scoring; updated the README.

### Reason
User reported the helper was reading items on the ground rather than the items they hold, and wants it to show what they're holding first and then how to evolve those items.

## Version 00.03.00
Date: 11/07/2026
Time: 2:34 PM

### Changes
- Evolution data now comes from the Vampire Survivors wiki (vampire.survivors.wiki): 165 recipes covering the base game and every expansion (evolutions, unions and gifts), plus weapon and passive item names. It replaces the hand-written list in `vshelper/data/evolutions.json`.
- Added `python -m vshelper update-data`. The helper also refreshes the wiki data in the background about once a week into `cache/wiki_evolutions.json`, used from the next start.
- The wiki data is checked against the game files: the one-time picture extraction also reads the game's own evolution data (`cache/game_data.json`). Each recipe shows "matches game files" or what the game files say instead, and the diagnose report lists mismatches.
- Internal item names read from the game files are also used to recognise items during memory reading.
- Added a Settings tab with Expansions toggles (all on by default) that hide an expansion's items and evolutions; saved to `settings.json` (gitignored).
- The item list only shows items that take part in a recipe.
- Emerald Diorama evolutions that need a Glimmer show "Also needs: <Glimmer>". Three wiki recipes with non-item conditions (Candybox, Alucard Swords, Spirit Rings) are left out.
- Fixed the internal alias for Tirajisú (wiki spelling) and added tests for the wiki parser, game data comparison, settings and expansion filtering. Updated the README.

### Reason
User asked to pull all data from the wiki and compare it with the game files, to include all expansions with per-expansion toggles on by default, and to add a Settings tab for these and future settings.

## Version 00.02.00
Date: 11/07/2026
Time: 2:27 PM

### Changes
- Item pictures: on first start (and after a game update) the helper finds the game through Steam or the running process, extracts item sprites from the installed game files with UnityPy, and saves 32px PNGs to `cache/icons/` (gitignored).
- Results are now shown as `weapon + item = evolution` with pictures; owned items are green and missing items red. The item list shows small pictures too.
- Added `requirements.txt` (UnityPy). `Start Helper.bat` installs it once if it's missing; without it the helper still works, just without pictures.
- The diagnose report now includes the suggestions for detected items and which pictures were found.
- Window opens slightly larger (1000x620).
- Added tests for picture matching and extraction; updated the README.

### Reason
User asked for item pictures in the format weapon + augment = evolution. The game's artwork can't be shipped with the project, so it is extracted from the user's own installed game, as they chose.

## Version 00.01.02
Date: 11/07/2026
Time: 2:23 PM

### Changes
- Replaced the Weapons / Passives / Evolved tabs with one scrolling list: Weapons first, then Passive Items, then Evolved Weapons, each under a heading.
- The filter box now keeps that order (it previously moved re-shown items to the end of the list).

### Reason
User wants all weapons listed first, followed by items.

## Version 00.01.01
Date: 11/07/2026
Time: 2:21 PM

### Changes
- Added `Start Helper.bat`: checks for Python, starts Vampire Survivors through Steam if it isn't running, and opens the helper without a console window.
- Added `Diagnose.bat` to write the detection report with a double-click.
- Startup errors are now also shown in a popup, since the helper runs without a console.
- Added `.gitattributes` so `.bat` files keep Windows line endings.
- Updated README run instructions.

### Reason
User wants to start everything with a double-click instead of using PowerShell.

## Version 00.01.00
Date: 11/07/2026
Time: 2:15 PM

### Changes
- Added the Vampire Survivors Helper app (`python -m vshelper`): a window that lists evolutions that are ready, one item away, or possible with the current weapons and passive items.
- Added an evolution database (`vshelper/data/evolutions.json`) covering the base game, with some DLC recipes marked unverified.
- Added automatic inventory detection that reads game memory (read-only). It finds Unity IL2CPP classes and fields by name rather than fixed addresses, and searches the game's objects on its own if the configured names don't match (`config/game_map.json`).
- Added a manual mode (tick items yourself) and a `python -m vshelper diagnose` report for troubleshooting detection.
- Added unit tests that use a simulated game memory layout, plus README setup and usage instructions and a `.gitignore`.

### Reason
User wants a helper that automatically shows which evolutions are available during a run, without googling and without manual setup such as Cheat Engine.

## Version 00.00.02
Date: 11/07/2026
Time: 2:00 PM

### Changes
- Added `.cursor/rules/git-main-branch.mdc`: always commit and push to `main`, never create extra branches.
- Moved all work to `main` and deleted the extra `claude/compassionate-turing-6g0dqy` branch.

### Reason
User requested that all work go directly to the main branch with no extra branches.

## Version 00.00.01
Date: 11/07/2026
Time: 2:00 PM

### Changes
- Added Cursor project rules in `.cursor/rules/`: `changelog.mdc`, `check-performance-when-relevant.mdc`, `dependencies.mdc`, `documentation.mdc`, `handle-errors-clearly.mdc`.
- Added `VERSION` file (starting at `00.00.01`).
- Added this `CHANGELOG.md`.

### Reason
Establish project-wide working rules for changelog tracking, performance, dependencies, documentation, and error handling. `VERSION` and `CHANGELOG.md` are required by the changelog rule.
