# Changelog

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
