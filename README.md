# Bracketman

A Python library, CLI tool, and **Streamlit Web UI** that reads multi-tab wrestling team rosters directly from a Google Spreadsheet (or local `.xlsx` / `.csv` files), normalizes divisions (`Coed` / `Girls`), age groups (`4U`, `6U`, `8U`, `10U`, `12U`, `15U` with `14U` unified into `15U`), and skill levels (`Beginner` / `Advanced`), and builds optimal **Madison weight groups** and **printable brackets**.

## Features

- **Interactive Streamlit Web Application (`bracketman ui`)**:
  - **Multi-Tournament Management**: Create, switch between, and persist named tournaments (`data/tournaments/<slug>/tournament.json`).
  - **Paste Google Sheet URL or Upload `.xlsx`/`.csv`**:
    - **Full Overwrite Mode**: Rebuild all brackets from scratch.
    - **Sync & Preserve Locked/Tweaked Mode**: Keep manually tweaked or locked brackets intact while regrouping remaining unlocked wrestlers.
  - **Manual Bracket Tweaking**:
    - Move a wrestler between brackets (or spin off a new bracket).
    - Swap two wrestlers between brackets.
    - Merge two brackets (including one-click **"Merge"** buttons on solo straggler recommendations).
    - Edit wrestler scale weight, name, or team in place.
    - Lock/unlock individual brackets.
  - **Targeted Regeneration by Bracket ID(s)**:
    - Select or paste one or more Bracket IDs (e.g. `COED-8U-BEG-01, COED-8U-BEG-02`) and re-run Madison grouping on just those brackets (with optional custom size or weight-spread overrides, or pooling across skills/ages).
  - **Live Printable Bracket Preview & Exports**:
    - Filter by Division, Age Group, Skill, or specific Bracket IDs and print/download `brackets.html`, multi-tab `brackets_workbook.xlsx`, or `.csv` schedules.

## Quick Start

```bash
# Activate the virtual environment
source .venv/bin/activate

# Launch the interactive Streamlit Web UI
bracketman ui
# (or: streamlit run src/bracketman/web/app.py)
```

### CLI Commands

```bash
# 1. Inspect a Google Spreadsheet's tabs, wrestler counts, and divisions
bracketman inspect "https://docs.google.com/spreadsheets/d/1VWSHOuqCDildUjOL7BdS7CQ4OdJ6K78m8Osr3RjqoLY/edit?usp=drivesdk"

# 2. Build Madison groups and printable brackets from CLI
bracketman build "https://docs.google.com/spreadsheets/d/1VWSHOuqCDildUjOL7BdS7CQ4OdJ6K78m8Osr3RjqoLY/edit?usp=drivesdk" --show-rosters

# 3. Regenerate specific bracket IDs in a saved tournament
bracketman regenerate sswl-example-tournament COED-8U-BEG-01 COED-8U-BEG-02 --max-size 4
```
