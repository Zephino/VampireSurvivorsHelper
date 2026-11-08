# Changelog

## Version 00.00.43
Date: 11/08/2026
Time: 3:27 AM

### Changes
- Fewer antivirus false alarms for the exe:
  - The GitHub build compiles PyInstaller's starter program (bootloader) from source instead of using the prebuilt one shared by every PyInstaller program.
  - The exe now has file details (product name, description, version, copyright) in Properties > Details.
  - Each release also includes a folder version, `VampireSurvivorsHelper-folder.zip` (the exe plus its files, not packed into one file), which antivirus programs flag far less often.
- The folder version knows it can't replace itself: its update button opens the download page instead. The diagnose report says which build is running (folder version / standalone exe / Python source).
- Build recipe: `VSH_ONEDIR=1` builds the folder version. README updated.

### Reason
A friend's PC kept saying the app is a virus; user chose the free build changes to reduce false positives.

## Version 00.00.42
Date: 11/08/2026
Time: 3:14 AM

### Changes
- All evolutions now shows which characters start with each recipe's weapon(s), e.g. "Starting weapon of - Knife: Gennaro Belpaese, Zephyr".
- The All evolutions search box also matches character names: searching "Cornell" lists the recipes that use his starting weapons.
- The wiki data download reads every character page (238) for their starting weapons; 212 weapons have at least one character. Stored per item as `characters` in the data.

### Reason
User wants to see which character has each weapon, to help choose characters.

## Version 00.00.41
Date: 11/08/2026
Time: 2:55 AM

### Changes
- Fixed items that the game stores with an internal code instead of a name (e.g. Legacy of the Bloodmoon's FireBall is "BMN011_FIRE2_BALL") showing as "Unrecognized". The wiki data download now also reads the passive item pages and saves each item's game code from the wiki infobox ("id"); 408 of 434 items have one. The helper recognises held items by that code, and uses it to match pictures from the game's item catalogue.
- Codes found by single-item wiki lookups are used too. Tests for both.

### Reason
User's diagnose report showed FireBall as "Unrecognized: BMN011_FIRE2_BALL", so nothing was listed for it.

## Version 00.00.40
Date: 11/08/2026
Time: 2:54 AM

### Changes
- The wiki data download now also reads every weapon's own wiki page (about 400 pages, a few seconds) and adds recipes the Evolution page doesn't list: 5 new ones (Mart-Hello + Parm Aegis = Hammer-Dah, and the character morphs of Bone, Carréllo, Celestial Dusting and Cherry Bomb). Bundled data: 165 -> 170 recipes.
- Morphs are labelled as such ("needs the character at level 80 with this relic") and get their own "Morphs" heading in All evolutions.
- Fixed reading wiki infoboxes that put several fields on one line (e.g. Globus, Optical Shot); this also improves single-item lookups.
- Item-page recipes are skipped when their result is a passive item or when the Evolution page lists non-item conditions for it (e.g. Alucard Shield's "6 passives + 6 evolutions"), so they can't show as ready too early.
- The helper now uses whichever copy of the wiki data is newer (bundled or last week's download), so updates with fresher data take effect immediately.
- Tests for the infobox parsing and choosing the newer data. README updated.

### Reason
User keeps finding recipes the helper doesn't know and asked to pull all recipes from the wiki.

## Version 00.00.39
Date: 11/08/2026
Time: 2:14 AM

### Changes
- Fixed the helper showing items you aren't holding (e.g. 8 base-game weapons and Spinach, all without levels): it had fallen back to searching memory for any list of known items and picked up a list of item data. Now that search only runs when the known path to your inventory can't be found at all this session, and it only accepts lists of items that have a level (held equipment), never plain item data.
- A searched-for list is replaced as soon as the known inventory path works again.
- Tests for both cases.

### Reason
User reported the helper listed many items while they were holding only one.

## Version 00.00.38
Date: 11/08/2026
Time: 2:05 AM

### Changes
- The "Launch Vampire Survivors" / "Game running" button now sits at the right end of the tab row (level with Overview, All evolutions and Settings) instead of on its own row, and is slimmer to match the tabs. The extra row above the tabs only appears for the co-op player switch.

### Reason
User wanted the launch button on the same level as the tabs to reclaim the unused space.

## Version 00.00.37
Date: 11/08/2026
Time: 2:02 AM

### Changes
- Diagnose reports (Settings > Troubleshooting and `Diagnose.bat`) are now saved on the Desktop (the real Desktop folder, also when Windows has moved it into OneDrive), falling back to the helper's own folder only if there is no Desktop.
- Creating a report no longer opens a folder afterwards; it just says where the file was saved.
- README updated; test for the report location.

### Reason
User asked for diagnose reports to go on the Desktop and for no folder to be opened after creating one.

## Version 00.00.36
Date: 11/08/2026
Time: 2:01 AM

### Changes
- Added a "Launch Vampire Survivors" button at the top right (and in Settings > Game) that starts the game through Steam. It shows "Game running" and is greyed out while the game is open.
- New setting Settings > Game > "Start Vampire Survivors when the helper opens" (on by default); it only launches the game if it isn't already running. Works for the exe too.
- `Start Helper.bat` no longer starts the game itself (the helper does, so the setting controls it and the game isn't started twice).
- New `vshelper/game_launcher.py` with tests; README updated.

### Reason
User asked for a toggle to open Vampire Survivors automatically and a button to open it.

## Version 00.00.35
Date: 11/07/2026
Time: 5:21 PM

### Changes
- The standalone exe now updates itself: Settings > Updates checks the latest GitHub release (only versions whose exe was actually built), "Update now" downloads the new exe next to the running one, checks it's a real program, renames the running exe to `VampireSurvivorsHelper.old.exe` and moves the new one into place; "Restart helper" starts it and the old file is deleted on the next start. If anything fails the old exe is kept; an "Open download page" button appears.
- Fixed the GitHub build: one test (button rows wrapping) failed on GitHub's Windows machine because a hidden window doesn't report its size there, so no exe release had been published since 00.15.02 (now 00.00.24). The test now passes the width directly.
- Removed the old VERSION-file check for the exe; tests for the release check and the exe swap. README updated.

### Reason
User asked for a way to push new exe versions to friends without them rebuilding anything, leaving only the files needed.

## Version 00.00.34
Date: 11/07/2026
Time: 5:14 PM

### Changes
- Renumbered every version so they count up by 00.00.01 per changelog entry, oldest first (33 entries: 00.00.01 to 00.00.33; this change is 00.00.34). Old -> new:
  - 00.00.01 -> 00.00.01
  - 00.00.02 -> 00.00.02
  - 00.01.00 -> 00.00.03
  - 00.01.01 -> 00.00.04
  - 00.01.02 -> 00.00.05
  - 00.02.00 -> 00.00.06
  - 00.03.00 -> 00.00.07
  - 00.04.00 -> 00.00.08
  - 00.05.00 -> 00.00.09
  - 00.06.00 -> 00.00.10
  - 00.07.00 -> 00.00.11
  - 00.07.01 -> 00.00.12
  - 00.08.00 -> 00.00.13
  - 00.09.00 -> 00.00.14
  - 00.10.00 -> 00.00.15
  - 00.11.00 -> 00.00.16
  - 00.12.00 -> 00.00.17
  - 00.13.00 -> 00.00.18
  - 00.13.01 -> 00.00.19
  - 00.14.00 -> 00.00.20
  - 00.15.00 -> 00.00.21
  - 00.15.01 -> 00.00.22
  - 00.15.02 -> 00.00.23
  - 00.16.00 -> 00.00.24
  - 00.17.00 -> 00.00.25
  - 00.18.00 -> 00.00.26
  - 00.18.01 -> 00.00.27
  - 00.18.02 -> 00.00.28
  - 00.18.03 -> 00.00.29
  - 00.19.00 -> 00.00.30
  - 00.20.00 -> 00.00.31
  - 00.20.01 -> 00.00.32
  - 00.20.02 -> 00.00.33
- The standalone exe's update check now offers any version that differs from the installed one (it used to require a higher number, which would have hidden all updates after the renumbering). The git-based updater compares commits and is unaffected.
- Changelog rule updated with the new numbering examples.

### Reason
User asked to fix the version numbers based on the changelog so they count by 00.00.01.

## Version 00.00.33
Date: 11/07/2026
Time: 5:13 PM

### Changes
- Changelog rule (`.cursor/rules/changelog.mdc`): every change now raises the version by exactly 00.00.01, rolling over at 99; versions are never lowered or renumbered because the updater only offers higher versions. Existing version numbers are kept as they are.

### Reason
User expected the version to count up by 00.00.01 per change; earlier changes had raised the middle number for larger features because the rule didn't say which part to raise.

## Version 00.00.32
Date: 11/07/2026
Time: 5:06 PM

### Changes
- Recipe cards now show each part's level (e.g. "Lv 8/8") instead of only "have". A part the recipe needs at max level that isn't maxed yet gets an orange border and orange level; levels of parts that don't need to be maxed are shown in grey.
- Overview splits "Ready to evolve" into READY TO EVOLVE (every part at the level it needs: just open a chest) and ALL PARTS - LEVEL UP FIRST (you have everything but something still needs levelling). In manual mode, where levels are unknown, the hint still says to max the weapon first.

### Reason
User asked whether levels matter for evolving; they do (usually the weapon, sometimes also the passive, must be at max level), but the recipe cards didn't show it.

## Version 00.00.31
Date: 11/07/2026
Time: 5:00 PM

### Changes
- Co-op: the helper now reads every player in the game (up to 4) from the game's player list, with their items, levels and character name (e.g. "Player 2 (Bill)").
- When more than one player is in the game, a "Show items of: Player 1 - you | Player 2 | ..." bar appears above the tabs. Choosing a friend switches Overview and How to evolve to their items, so you can tell them what they can evolve and what they still need. Hidden when playing alone or with auto-detect off; planning (ticking items) applies to player 1.
- The status bar mentions how many players are in the game. README updated; tests for reading co-op players.

### Reason
User wants to see what their friends hold so they can tell them what they need to evolve.

## Version 00.00.30
Date: 11/07/2026
Time: 4:44 PM

### Changes
- Item pictures the game files didn't provide are now downloaded from the wiki (`Sprite-<name>.png`) in the background and resized like the others. In a test with an empty cache, 425 of 430 items got a picture in about a minute, including Keremet Bubbles/Morbus and all Custos weapons. Works without the game installed; each item is asked about at most once a week (`cache/icons/wiki_icons.json`), and items added by wiki recipe lookups get pictures too.
- New setting: Settings > Detection > "Download missing item pictures from the wiki" (on by default).
- Overview: "What your items evolve into" now comes after "Ready to evolve", and a union of two held weapons is listed once instead of once per weapon.
- The "start the game once so the helper can find it" picture message no longer appears when pictures are already available.
- Tests for the wiki picture download.

### Reason
User suggested pulling all pictures from the wiki, since some items (e.g. Keremet and the Custos weapons) still had none.

## Version 00.00.29
Date: 11/07/2026
Time: 4:30 PM

### Changes
- Fixed held items whose game name differs slightly from the wiki's being reported as a number (e.g. "#1438"): the name read from the game is now kept when neither it nor the item number matches exactly, so near-identical spellings are recognised ("Sinistro Custos" in game = Sinestro Custos on the wiki).
- The item catalogue is now read from all of the game's item tables (`AllWeaponData`, `_weaponData`, `_dlcWeaponData`) and merged, and tables whose values are lists, arrays or single data objects are all handled.
- Picture names are also taken from each item you hold (its own data object), so items you've had get their picture even if the full catalogue can't be read. Background picture extraction runs again at most every 10 minutes to keep the game smooth.
- The diagnose report shows the structure of the item tables (fields, first entry bytes, readable item data) to fix catalogue reading if it still fails.
- Tests for the spelling case and picture names from held items.

### Reason
The user's diagnose report showed their second Custos weapon reported as "#1438" (the game spells it "Sinistro Custos") and the item catalogue not found, which kept Keremet and Custos weapons without pictures.

## Version 00.00.28
Date: 11/07/2026
Time: 4:19 PM

### Changes
- Held items whose game name is spelled almost the same as the wiki's (e.g. one letter different) are now still recognised (close-match, only for items read from your inventory).
- Items the helper finds in your inventory but can't identify at all are no longer skipped silently: the status bar says how many couldn't be identified and asks for a diagnose report.
- Tests for both.

### Reason
User holds two of the three Custos weapons but the helper listed only Dextro Custos, so it said both Sinestro and Centralis Custos were still needed.

## Version 00.00.27
Date: 11/07/2026
Time: 4:04 PM

### Changes
- Overview has a new "What your items evolve into" section under Ready to evolve: one compact line per evolution of each held weapon that still needs parts (e.g. Dextro Custos -> Trinum Custodem, needs Centralis Custos and Sinestro Custos, union), with have / need marks. Recipes already under Ready to evolve aren't repeated.
- New switch in Settings > Main screen: "Overview: What your items evolve into" (on by default). README updated.

### Reason
User expected to see Dextro Custos' recipe on Overview, which only listed evolutions that were already ready.

## Version 00.00.26
Date: 11/07/2026
Time: 3:51 PM

### Changes
- Items you hold or plan that have no known recipe, and items the helper doesn't recognise, are now looked up on their own wiki page in the background. The page's infobox (evolution / evolution-item / union / requires) is read and the recipe added immediately (e.g. Bone + Chaos Malachite = Anima of Mortaccio). While searching, How to evolve says so; if the wiki has nothing either, it says "No evolution found on the wiki" with an "Open wiki page" link.
- Answers are cached in `cache/wiki_lookups.json` for a week; redirects to non-item pages (e.g. arcana cards) are ignored. New items found this way can be recognised by auto-detect, and their recipes are listed under "Found on the wiki" in All evolutions.
- New setting: Settings > Detection > "Look up items without a known recipe on the wiki" (on by default).
- The item list's "Filter" box is now labelled "Search" and also matches expansion names.
- New `vshelper/lookups.py`; tests for item-page parsing, the lookup cache and adding recipes.

### Reason
User asked for the helper to search the internet when it doesn't have a recipe, and for a search box on the Overview item list.

## Version 00.00.25
Date: 11/07/2026
Time: 3:46 PM

### Changes
- The helper now reads the game's own item catalogue from memory during a run (`DataManager.AllWeaponData`): the name, picture name and evolution of every weapon and passive, including DLC items such as the Ode to Castlevania weapons, whose data couldn't be read from the game files. It is saved to `cache/game_catalog.json` once per game session.
- Picture extraction uses those picture names first (e.g. Keremet Bubbles is `-05-TP_ACID1`) and runs again in the background when the catalogue adds new ones, so most of the ~200 items that showed without a picture should get one.
- New reader for the game's dictionaries (`Il2Cpp.dictionary_items`) and `catalog_path` in `config/game_map.json`.
- The diagnose report shows the catalogue (game name -> helper item, picture, evolves into) and saves it.
- Tests for the catalogue, its picture names and the dictionary reader.

### Reason
User asked why the helper didn't seem to know how to evolve some items (e.g. Keremet Bubbles). Their report showed the recipe was known (Keremet Bubbles + Armor = Keremet Morbus) but those items had no picture, because their picture names weren't in the data read from the game files; the game's memory does contain them.

## Version 00.00.24
Date: 11/07/2026
Time: 3:38 PM

### Changes
- The item list can be ticked while auto-detect is on, to plan ahead: items you tick but don't hold are added as "planned". They show with a blue border and "planned" on the item cards, combos that need them get a PLANNED badge on How to evolve and their own "With your planned items" section on Overview, so real READY results stay accurate.
- Detected items stay ticked (they can't be unticked while held); Clear removes only planned items in auto-detect mode; a planned item you pick up in the game becomes a normal detected item. Switching auto-detect back on turns hand-ticked items that aren't detected into planned items.
- Updated Settings > Detection text and the README.

### Reason
User wants to toggle items they don't have to see what they would need.

## Version 00.00.23
Date: 11/07/2026
Time: 3:36 PM

### Changes
- Made the wrapping button rows (used for Settings > Updates, the item list's Clear / Filter, the search bar and the status bar) independent of how Tk reports widget sizes. They read their height and padding back from Tk, which newer Tk versions (e.g. Tk 9 with recent Python) return in a different form; that could stop the rows from being laid out, leaving buttons such as "Check for updates" / "Update now" invisible.
- Added tests for the wrapping rows (run where a display is available, e.g. the Windows build).

### Reason
User reported the update button had disappeared.

## Version 00.00.22
Date: 11/07/2026
Time: 3:34 PM

### Changes
- The item list is back on the Overview tab, on the left beside your results, instead of a separate Items tab. "Hide the item list while auto-detect is on" (Settings > Detection) hides it there, so Overview uses the full width while the game is being read.
- Updated the waiting message and Settings text to match; README updated.

### Reason
User wants the items on the Overview page.

## Version 00.00.21
Date: 11/07/2026
Time: 3:32 PM

### Changes
- All tabs are now in one row across the window: Overview, How to evolve, All evolutions, Items, Settings. The separate left panel and its Hide list / Show list button are gone.
- New Settings > Detection group: "Auto-detect items from the game" (moved here from the top bar, now remembered between runs) and "Hide the Items tab while auto-detect is on" (on by default), which hides the manual weapon list automatically while the game is being read.
- Clear and Filter moved to the top of the Items tab.
- Text and buttons now wrap instead of being cut off when the window or panel is narrow: item names in the list, all Settings text and switches, the Settings button rows, the All evolutions search bar and the status bar (new `vshelper/widgets.py` FlowFrame). The minimum window size is smaller (480x320).
- Settings `show_side_panel` replaced by `auto_detect` and `hide_items_when_auto`. README updated.

### Reason
User reported that narrowing the list hid words and buttons, then asked for all tabs in one row, for the weapon list to hide automatically (toggleable in Settings), and for auto-detect to move into Settings.

## Version 00.00.20
Date: 11/07/2026
Time: 3:27 PM

### Changes
- The helper can be built into a single `VampireSurvivorsHelper.exe` that friends can run without Python or Git: `Build Exe.bat` (uses PyInstaller, a build-only tool in `requirements-build.txt`), recipe `VampireSurvivorsHelper.spec`, entry point `run_helper.py`.
- Added a GitHub Actions workflow that builds the exe on Windows, runs the tests and publishes it as a GitHub Release whenever `VERSION` changes on main (or when started by hand).
- New `vshelper/paths.py`: as an exe, bundled data is read from inside the exe and settings, cache and reports are saved in `%LOCALAPPDATA%\VampireSurvivorsHelper`. Running from source is unchanged.
- Settings > Updates in the exe checks the version on GitHub and offers a "Download page" button (an exe can't replace itself); Restart works for the exe too.
- Added Settings > Troubleshooting > "Create diagnose report" (runs in the background, then opens the folder with the report selected), so exe users don't need Diagnose.bat.
- README: "For friends" and "Building the exe" sections. Tests for the online version check.

### Reason
User wants an easy way to give the app to friends as an exe they can just run, and is making the repository public so friends can download it.

## Version 00.00.19
Date: 11/07/2026
Time: 3:22 PM

### Changes
- The window title now shows the version, e.g. "Vampire Survivors Helper v00.13.01" (read from `VERSION`).

### Reason
User asked for the version to be shown in the title.

## Version 00.00.18
Date: 11/07/2026
Time: 3:21 PM

### Changes
- Added a "Hide list" / "Show list" button at the top left. It hides the item list and Settings panel so the results use the whole window, and hides the Clear and Filter controls with it. The choice is saved (`show_side_panel` in `settings.json`).
- Fixed the status bar being pushed off the bottom of the window when there wasn't enough height (since the results tabs were added).
- README updated.

### Reason
User asked for a way to hide the weapon list.

## Version 00.00.17
Date: 11/07/2026
Time: 3:18 PM

### Changes
- Added Settings > Updates: shows the installed version, "Check for updates" (fetches from GitHub and lists what changed), "Update now" (git pull, plus installing packages if `requirements.txt` changed) and "Restart helper".
- "Check for updates when the helper starts" (on by default) checks quietly in the background and shows "Update available" in the status bar.
- Clear messages when Git is missing, the copy wasn't downloaded with git (with an "Open GitHub page" button), the network is slow, or local file edits block the update. Git runs in the background without flashing a console window.
- New `vshelper/updater.py` with tests against a local test repository; README "Updating" section.

### Reason
User asked for an update function in Settings.

## Version 00.00.16
Date: 11/07/2026
Time: 3:16 PM

### Changes
- Items on the Overview and How to evolve tabs are now shown as cards in the user's layout: picture top-left, level top-right, name along the bottom. All cards are the same size so they line up in rows.
- Overview: "You're holding" shows weapon cards, then passive item cards; Ready to evolve shows card + card = card.
- How to evolve: the held item's card, then for each evolution the result card and the cards of the parts it needs.
- Card borders and the level corner show status: Lv x/y (orange until maxed, green when maxed) for held items, "have" with a green border, "need" with a red border.
- READY / LEVEL UP are now small badges instead of tall blocks.
- Cards follow the dark/light theme and the picture / level / details settings; the mouse wheel scrolls over cards. The All evolutions guide keeps its compact text lines.

### Reason
User asked for the main screen to use their card layout (icon, level, name) because it is easier to see.

## Version 00.00.15
Date: 11/07/2026
Time: 3:11 PM

### Changes
- The results area now has three tabs: **Overview** (You're holding and Ready to evolve), **How to evolve** (each held item, what it evolves into and what's still needed), and the new **All evolutions** guide.
- All evolutions lists every recipe grouped by expansion and by type (evolutions, unions, gifts), with pictures, details and game-file checks. Held items are highlighted, hidden expansions are left out, and a search box filters by weapon, item or evolution name.
- Settings > Main screen: "How to evolve tab" now shows or hides that tab, and the Overview switches are labelled as such. All tabs follow the dark/light theme.
- README updated.

### Reason
User asked for a separate tab for how to evolve weapons, and chose both splitting the main screen into Overview / How to evolve and adding an All evolutions guide.

## Version 00.00.14
Date: 11/07/2026
Time: 3:09 PM

### Changes
- Added a "Main screen" group to Settings with switches for what the results pane shows: You're holding, Ready to evolve, How to evolve your items, items with no evolution, item levels (Lv x/y, LEVEL UP and "level up first"), details (max level, notes), game-file check marks and item pictures (also in the item list). All on by default, applied instantly and saved in `settings.json`.
- The Settings tab now scrolls, so every group stays reachable as more settings are added.
- Settings loading now falls back to the default for each value that is missing or has the wrong type, instead of all-or-nothing.
- Added tests for the new settings; updated the README.

### Reason
User asked for a way in Settings to toggle what is shown on the main screen.

## Version 00.00.13
Date: 11/07/2026
Time: 3:07 PM

### Changes
- Added a dark theme, on by default, with a "Dark theme" switch under Settings > Appearance. It applies instantly and covers the tabs, item list, buttons, checkboxes, filter box, results pane (including the have / need / level colours), scrollbars and status bar. Turning it off restores the native Windows look.
- The choice is saved in `settings.json` (`dark_theme`); added tests for the default and saving it.
- README: documented the Appearance setting.

### Reason
User asked for a dark theme that can be toggled in Settings and is on by default.

## Version 00.00.12
Date: 11/07/2026
Time: 3:06 PM

### Changes
- Passive items now show even when you hold more than 12: inventory paths from the game map are trusted at any size. The 12-item limit only applies to lists found by the automatic search (item pools, pickups).
- Internal game names are worked out even when both parts of a recipe are unknown (the recipe's key is the base weapon, the rest is the passive). This resolves the last three false wiki "mismatches" (Emergency Meeting, Paranormal Scan, Rocket Science).
- Test lists can hold more items; added tests for both fixes.

### Reason
The user's latest diagnose report showed detection working for weapons, but all 17 held passives were dropped by the 12-item limit, and three recipes were still reported as mismatches.

## Version 00.00.11
Date: 11/07/2026
Time: 3:00 PM

### Changes
- The diagnose report now collects everything needed for troubleshooting in one file: setup (helper, Python, Windows, admin, UnityPy versions, game folder and build), settings and cache files, class layouts of the key game classes (characters, weapon/accessory managers, equipment, WeaponData and more), static fields, item enums, detection result with levels, every held item with all its fields and data objects, all candidate item lists, related metadata names, the game's internal item names with their mapping and picture names, and similar game sprite names for every item without a picture.
- Each report section catches its own errors and writes them into the report, so one failure no longer stops the report.
- `Diagnose.bat` now explains the steps, waits for a key press while you start a run, and opens the folder with the report selected.
- Picture extraction also saves the game's sprite names (`cache/icons/sprite_names.txt`) and the picture name of each item from the game data, and uses those to find more pictures. Existing installs extract once more after updating.

### Reason
User asked for Diagnose.bat to gather everything that might be needed, such as the full game structure and item data.

## Version 00.00.10
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

## Version 00.00.09
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

## Version 00.00.08
Date: 11/07/2026
Time: 2:39 PM

### Changes
- Results are now built around what you're holding: "YOU'RE HOLDING" (weapons, then passive items), "READY TO EVOLVE", then "HOW TO EVOLVE YOUR ITEMS", which lists each held item with its evolutions and the other parts needed (have or need). Replaces the "one item away" and "other evolutions" lists. The results pane now has a scrollbar.
- Memory detection is stricter about which list is your inventory: lists with more than 12 items are rejected (also while playing), list paths through names like pickup, drop, pool, available, chest or level-up are rejected, and paths through player, equipment, weapon or accessory names are preferred.
- The diagnose report lists every candidate list with its score and items, and shows the new results text.
- Added tests for the held-items view and inventory scoring; updated the README.

### Reason
User reported the helper was reading items on the ground rather than the items they hold, and wants it to show what they're holding first and then how to evolve those items.

## Version 00.00.07
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

## Version 00.00.06
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

## Version 00.00.05
Date: 11/07/2026
Time: 2:23 PM

### Changes
- Replaced the Weapons / Passives / Evolved tabs with one scrolling list: Weapons first, then Passive Items, then Evolved Weapons, each under a heading.
- The filter box now keeps that order (it previously moved re-shown items to the end of the list).

### Reason
User wants all weapons listed first, followed by items.

## Version 00.00.04
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

## Version 00.00.03
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
