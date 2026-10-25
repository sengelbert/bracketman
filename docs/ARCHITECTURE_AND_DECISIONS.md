# Bracketman — Architecture & Decision Log

## 1. Project Overview

**Bracketman** is a wrestling tournament bracket generator and management system built for youth and scholastic tournaments. It automates roster ingestion from Google Spreadsheets, normalizes messy real-world data, generates optimal **Madison weight brackets** (4-person round-robin pods and below by default) using dynamic programming, handles walk-ins and scratches, and provides both a CLI and an interactive Streamlit Web UI with printable bout sheets.

---

## 2. Key Architectural Decisions & Rationale

### Decision 1: Direct Google Sheet Ingestion Without Cloud Credentials
- **Context**: Tournament directors frequently receive link-shared Google Spreadsheets with one tab per club/team. Setting up Google Cloud service account keys, OAuth credentials, or Google Cloud projects creates high friction for volunteers.
- **Decision**: Ingest public/link-shared spreadsheets directly by exporting them as `.xlsx` via `https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx`.
- **Implementation**: Pure-Python `.xlsx` reader ([xlsx.py](file:///home/simon/Code/Personal/bracketman/src/bracketman/io/xlsx.py)) parsing OpenXML zip structures without external C libraries. Header rows are auto-detected (skipping instruction preambles) and empty template rows are ignored.

### Decision 2: Age Group & Skill Normalization
- **Context**: Roster spreadsheets contain inconsistent casing (`6u` vs `6U`), typos (`experianced`), and league-specific tier naming (`Novice` vs `Experienced`).
- **Decision**:
  - **Canonical Age Groups**: `4U`, `6U`, `8U`, `10U`, `12U`, and `15U`.
  - **14U & 15U Unified**: `14U` is mapped into `15U` by default (`age_group_aliases`), recognizing that scholastic/middle school age divisions frequently combine these two brackets.
  - **Skill Levels**: Normalized to `Beginner` and `Advanced`. `Novice` automatically maps to `Beginner`; `Experienced` / `experianced` / `Open` automatically maps to `Advanced`.
  - **Dual Division Entries**: Girls who elect to wrestle in both `Boys / COED Bracket` and `Girls only Bracket` are entered into both divisions as distinct entries linked with an `is_dual_entry` flag.

### Decision 3: Madison Weight Grouping via Dynamic Programming (DP)
- **Context**: Naive greedy slicing (e.g. chunking every 4 wrestlers) frequently leaves the heaviest wrestler stranded alone in a 1-man group or creates artificial weight mismatches across natural weight clusters.
- **Decision**: Implemented `partition_madison_dp` in [madison.py](file:///home/simon/Code/Personal/bracketman/src/bracketman/grouping/madison.py).
  - Evaluates candidate partition costs across group sizes (targeting 4-man pods, min 2, max 4).
  - Quadratic penalty on group size deviations from target size (`4`).
  - Heavy penalty on 1-man groups to prevent stragglers when safe grouping is possible.
  - **Progressive Weight Spread**: Allowed weight spread scales up as wrestler weight increases:
    - `< 50 lbs`: up to `10.0%` (`~3.0–4.9 lbs`)
    - `50–74.9 lbs`: up to `11.0%` (`~5.5–8.2 lbs`)
    - `75–104.9 lbs`: up to `12.0%` (`~9.0–12.5 lbs`)
    - `105–134.9 lbs`: up to `13.5%` (`~14.2–18.2 lbs`)
    - `135+ lbs`: up to `15.0%` (`~20.3–25+ lbs`)
    - *Girls division includes an additional `+2.0%` base spread buffer to accommodate sparser upper weights.*
  - **Teammate Separation**: Boundary wrestlers of near-identical weight between adjacent pods are swapped if doing so eliminates a same-club collision without violating weight spread limits.

### Decision 4: Printable Bout Sheet & Table Reference Layout
- **Context**: Mat table workers need an easy-to-read, pencil-friendly score sheet that prints cleanly with zero toner waste, plus an immediate reference for round-robin tiebreaker rules.
- **Decision**:
  - **Unshaded 3-Period Bout Table**: `BOUT` | `WT` | `WRESTLERS NAME` | `1ST PERIOD` | `PTS` | `2ND PERIOD` | `PTS` | `3RD PERIOD` | `PTS`.
  - Pure white background (`#ffffff`) with crisp black borders (`#000`), using a thicker `2.2px` solid black border between 2-row bout pairs to eliminate the need for grey shading.
  - **Wrestler Win / Loss Tally Area**: `#` | `WT` | `WRESTLERS NAME` | `SCHOOL / CLUB` | `WINS` | `LOSSES` | `TIEBREAKER / PTS` | `PLACE`.
  - **Tie-Breaker & Activity Points Reference**: Printed directly on the sheet with explicit victory margin rules:
    - `Decision (DEC)`: **3 pts** (1 to 7 point victory spread)
    - `Major Decision (MD)`: **4 pts** (8 to 14 point victory spread)
    - `Technical Fall (TF)`: **5 pts** (15+ point victory spread)
    - `Fall / Forfeit / Default / DQ`: **6 pts**

### Decision 5: Tournament Persistence & State Management
- **Context**: Tournament directors need to make day-of adjustments (walk-in registrations, scratches, manual moves, partial bracket regenerations) without losing work if the app reloads or if a new roster spreadsheet is re-synced.
- **Decision**:
  - Saved tournaments stored in `data/tournaments/<slug>/tournament.json`.
  - Brackets support `locked` and `manually_modified` state.
  - **Two Import Modes**:
    - `Full Overwrite`: Rebuilds all brackets from scratch.
    - `Preserve Locked`: Preserves all locked or manually adjusted brackets, updates wrestler weights, and only regroups unlocked wrestlers.
  - **Targeted Regeneration**: Directors can select specific Bracket IDs (e.g. `COED-8U-BEG-01, COED-8U-BEG-02`) and re-run Madison partitioning with custom size or spread overrides on just those brackets.
  - **Walk-Ins & Scratches**:
    - Walk-in engine ranks candidate brackets by suitability and weight spread.
    - Scratches remove wrestlers from active brackets and store them in `scratched_wrestlers` with a 1-click restore mechanism.

---

## 3. Repository Structure

```text
bracketman/
├── pyproject.toml              # Build & dependency metadata (CLI + Streamlit)
├── README.md                   # Quick start, usage, and CLI reference
├── docs/
│   └── ARCHITECTURE_AND_DECISIONS.md  # Architectural specifications & decision log
├── configs/
│   └── default.yaml            # Tournament rules, divisions, age/skill aliases
├── src/bracketman/
│   ├── models.py               # Wrestler, GroupRuleConfig, BracketGroup, Bout, TournamentResult
│   ├── config.py               # YAML config loader & hierarchical rule resolution
│   ├── store.py                # Tournament storage, walk-ins, scratches, manual tweaks, regeneration
│   ├── cli.py                  # CLI commands: inspect, build, ui, regenerate, init-config
│   ├── io/
│   │   ├── xlsx.py             # OpenXML reader/writer (zero external C dependencies)
│   │   └── loader.py           # Sheet downloader, auto-header detection, data normalizer
│   ├── grouping/
│   │   ├── madison.py          # Dynamic programming Madison weight grouping & teammate separation
│   │   └── bouts.py            # Round-robin bout generation & bracket trees
│   ├── exporters/
│   │   ├── console.py          # Rich terminal summary & director alert report
│   │   ├── csv_xlsx.py         # CSV exporter & multi-tab Excel/Sheets workbook generator
│   │   └── html.py             # Printable unshaded bout sheets & tie-breaker reference
│   └── web/
│       └── app.py              # Streamlit Web UI (port 8503)
└── tests/
    ├── test_loader.py          # Header detection, normalization, XLSX read/write tests
    ├── test_grouping.py        # Madison DP, teammate separation, straggler handling tests
    ├── test_exporters.py       # Console, CSV, XLSX, and HTML exporter tests
    └── test_store.py           # Tournament lifecycle, manual tweaks, walk-ins, scratches tests
```
