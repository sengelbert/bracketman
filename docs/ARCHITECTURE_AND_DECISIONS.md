# Bracketman — Architecture & Decision Log

## 1. Project Overview

**Bracketman** is a wrestling tournament bracket generator and management system built for youth and scholastic tournaments. It automates roster ingestion from Google Spreadsheets, normalizes messy real-world data, generates optimal **Madison weight brackets** (4-person round-robin pods and below by default) using dynamic programming, handles walk-ins and scratches, and provides both a CLI and an interactive Streamlit Web UI with printable bout sheets.

---

## 2. Key Architectural Decisions & Rationale

### Decision 1: Direct Google Sheet Ingestion Without Cloud Credentials
- **Context**: Tournament directors frequently receive link-shared Google Spreadsheets with one tab per club/team. Setting up Google Cloud service account keys, OAuth credentials, or Google Cloud projects creates high friction for volunteers.
- **Decision**: Ingest public/link-shared spreadsheets directly by exporting them as `.xlsx` via `https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx`.
- **Implementation**: Pure-Python `.xlsx` reader ([xlsx.py](file:///home/simon/Code/personal/bracketman/src/bracketman/io/xlsx.py)) parsing OpenXML zip structures without external C libraries. Header rows are auto-detected (skipping instruction preambles) and empty template rows are ignored.

### Decision 2: Age Group & Skill Normalization
- **Context**: Roster spreadsheets contain inconsistent casing (`6u` vs `6U`), typos (`experianced`), and league-specific tier naming (`Novice` vs `Experienced`).
- **Decision**:
  - **Canonical Age Groups**: `4U`, `6U`, `8U`, `10U`, `12U`, and `15U`.
  - **14U & 15U Unified**: `14U` is mapped into `15U` by default (`age_group_aliases`), recognizing that scholastic/middle school age divisions frequently combine these two brackets.
  - **Skill Levels**: Normalized to `Beginner` and `Advanced`. `Novice` automatically maps to `Beginner`; `Experienced` / `experianced` / `Open` automatically maps to `Advanced`.
  - **Dual Division Entries**: Girls who elect to wrestle in both `Boys / COED Bracket` and `Girls only Bracket` are entered into both divisions as distinct entries linked with an `is_dual_entry` flag.

### Decision 3: Madison Weight Grouping via Dynamic Programming (DP)
- **Context**: Naive greedy slicing (e.g. chunking every 4 wrestlers) frequently leaves the heaviest wrestler stranded alone in a 1-man group or creates artificial weight mismatches across natural weight clusters.
- **Decision**: Implemented `partition_madison_dp` in [madison.py](file:///home/simon/Code/personal/bracketman/src/bracketman/grouping/madison.py).
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
  - **Unified Priority Hierarchy (`Division [Locked] > Weight > Age > Skill > Team`, `blend_skills_to_fill_brackets`)**:
    - When `blend_skills_to_fill_brackets=True` (enabled by default in `configs/default.yaml` and Web UI), `build_tournament_groups` pools wrestlers by `(division, age_group)` rather than walling off `Beginner` and `Advanced` into separate pre-DP buckets, and automatically enables post-DP solo-skill straggler fallback so the redundant `Auto-Merge Solo Skill Stragglers` checkbox could be removed from the Import & Sync UI.
    - `_slice_cost` enforces the strict priority order: **Division** (hard locked between `Girls` and `Coed`) > **Weight Spread & Avoiding 2-Man Pods** (`two_man_penalty = 180.0` + `min_group_size` penalty `350.0`) > **Age Group** (bucketed per age group) > **Skill Level** (`_count_skill_mix_cost = 140.0 + 25.0 * minority_count` so high-density weights stay pure `Beginner`/`Advanced` while sparse weights blend `Beginner` + `Advanced` to form 3–4 man brackets instead of 2-man brackets) > **Same Club** (`45.0` per pair + post-DP boundary swaps in `optimize_adjacent_teammate_swaps`).
    - Any pod containing blended skill levels is assigned its majority skill (`_dominant_skill_level`) and automatically tagged with `SKILL_MERGED` (`⚠ MERGED SKILL`).

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

### Decision 6: Scope-Wide & Targeted Rethinking Engine (`reoptimize_active_brackets`)
- **Context**: During tournament check-in, scratching no-shows and registering walk-ins leaves some brackets sparse or unbalanced. Re-importing from Google Sheets wipes walk-ins entered locally.
- **Decision**: Added `reoptimize_active_brackets` to [store.py](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py).
  - Collects all active wrestlers (includes walk-ins, excludes scratches) across whole tournament or selected division/age group.
  - Leaves locked/hand-tweaked brackets untouched when `preserve_locked=True`.
  - Re-partitions active pool using Madison dynamic programming.
  - Exposed via Web UI tab and CLI command `bracketman reoptimize <slug>`.

### Decision 7: Secure Local-Only Mode by Default & Headless Daemon Mode
- **Context**: At tournament venues on shared gym/school Wi-Fi, other devices on the network should not be able to discover the app or modify live brackets. Additionally, operators running over SSH, background services, or automated environments need a headless startup command that does not attempt to spawn a desktop browser window.
- **Decision**:
  - `bracketman ui` binds to `127.0.0.1` by default (`--port 8503`). Optional `--lan` flag binds to `0.0.0.0` when network access across home devices is explicitly desired.
  - Added `--headless` flag (`.venv/bin/bracketman ui --headless --port 8503 --host 127.0.0.1`), which passes `--server.headless true` to Streamlit. On Linux without `DISPLAY` or `WAYLAND_DISPLAY` set in the environment, `bracketman ui` also auto-enables headless mode.

### Decision 8: 1-Page Printable Bracket Redesign with Top Combined Awards, Tally Box & Symmetric Bracket Diagram
- **Context**: Sheets must fit on exactly 1 printed page for mat tables and display official tournament branding plus a visual bracket progression diagram without internal app alerts.
- **Decision**:
  - Header: Tournament Name, Date, Division, Age, Experience, Weight Range, and `MAT #: _____` (scorer removed).
  - Conflict Warnings: Teammate conflicts and straggler warning boxes removed entirely from printouts (kept inside Streamlit app only).
  - Top Section (Directly under Header):
    - For 3–4 wrestler pods: Clean, unboxed Symmetric SVG Bracket Diagram (`_render_visual_bracket_diagram` in [html.py](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L19-L130)) with two central Round 1 boxes, consolation arms extending left to `3RD PLACE`, and championship arms extending right to `1ST PLACE` (labels placed underneath the lines so advancing names are written on top of the lines).
    - For 2-wrestler pods (`size == 2`, `bracket_format == "best_of_3"`): Dedicated **BEST 2 OUT OF 3 SERIES** SVG Bracket Diagram showing `BOUT 1`, `BOUT 2`, and `BOUT 3* (IF SPLIT 1-1)` boxes in the center with `2ND PLACE` on the left and `1ST PLACE (2 OF 3)` on the right, plus all 3 bouts generated in `group.bouts` ([`generate_round_robin_bouts`](file:///home/simon/Code/personal/bracketman/src/bracketman/grouping/bouts.py#L21-L39)).
  - Upper-Middle Section: Combined Official Placement & Awards Box (`1ST PLACE`, `2ND PLACE`, `3RD PLACE`, `4TH PLACE`) directly above the Wrestler Win/Loss Tally Table.
  - Lower-Middle Section: Main 3-period unshaded Bout Score Table (`38px` double-height rows in Full mode, or `42px` rows in Bout-Sheet-Only mode) with a narrowed Wrestler Name column (`18.5%`) and `BOUT`/`WT` columns (`3.8%`/`4.7%`) so the 3 Period scoreboxes expand to `20.33%` each (**`61%` of total page width**) for hand-writing live takedowns (`T3`), escapes (`E1`), reversals (`R2`), and near-falls (`NF2`/`NF3`/`NF4`).
  - Bottom Section: Condensed 3-column micro-reference table (`_render_scoring_and_criteria_box`) combining **Match Scoring Points (Period Boxes)** (`T3=3pts`, `E1=1pt`, `R2=2pts`, `NF2=2s / NF3=3s / NF4=4s+`, `Penalty: Warn, 1pt, 1pt, 2pt, DQ`) on the left, **Advancement Points & Decision Spreads** in the middle, and **Round-Robin Tie-Breaker Criteria** on the far right without increasing vertical page height.
  - **Bout-Sheet-Only Mode (No Bracket Drawing — Larger Fonts & Taller Boxes, Zero Page Bleed)**: Added `include_bracket_diagram: bool = True` across [`export_printable_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L971), [`export_blank_bracket_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L901), [`render_single_bracket_preview_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L604), and [`render_blank_bracket_preview_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L619), plus `.bout-only-sheet` CSS rules and an interactive `Layout` dropdown in the printable HTML toolbar. Removing the `98px` top SVG bracket diagram frees vertical height on the US Letter page (`~960px` printable content area with default browser print margins); `.bout-only-sheet` redistributes `~86px` into larger typography (`10.5px–16px`), `20px` W/L tally rows, and `42px`-tall period scoreboxes (`84px` per bout pair) so a 4-man 6-bout sheet renders at `~900px` total height—well below the `960px` single-page threshold with zero page-2 bleed.
  - Blank Walk-In Bracket & Bout Sheets: Added [`export_blank_bracket_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L901) and [`render_blank_bracket_preview_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L619) generating 1-page hand-writable blank bracket & bout sheets (4-Man Round-Robin, 3-Man Round-Robin, and 2-Man Best 2-of-3 templates with seed pairing hints, in both Full and Bout-Sheet-Only layouts).
  - Print CSS enforcing `@page { size: letter portrait; margin: 0.25in 0.3in; }` and `.bracket-sheet { max-height: 9.9in; page-break-inside: avoid; break-inside: avoid-page; page-break-after: always; break-after: page; }` (without forcing a `10.45in` fixed height that overflows default browser print margins).

### Decision 9: Synthetic Demo Dataset & Privacy-Preserving Defaults
- **Context**: Real youth wrestlers' names, weights, and league identities must never be exposed or committed to public example documentation.
- **Decision**:
  - Built `scripts/generate_example_tournament.py` generating 290 synthetic youth wrestlers across 8 fictionalized club tabs with realistic age-weight curves, beginner/advanced tiers, and dual entries.
  - Stored in `data/example_tournament.xlsx`.
  - Configured `src/bracketman/web/app.py` to auto-initialize `Example Tournament` if local store is empty, ensuring zero exposure of private league data.

### Decision 10: Automated Documentation Visuals & Headless Selenium Capture
- **Context**: Coaches, table workers, and league directors require clear visual previews of all tabs and score sheets in the project documentation.
- **Decision**:
  - Created `scripts/take_screenshots.py` using Selenium and headless Firefox to capture all 6 Streamlit tabs (`01_brackets_explorer.png`, `02_wrestler_lookup.png`, `02_tweak_regenerate.png`, `03_sheet_import.png`, `04_print_export.png`, `05_audit_log.png`), the populated 1-page printable bracket sheet (`06_printable_bracket_sheet.png`), the 1-page blank walk-in bracket sheet (`07_blank_bracket_sheet.png`), and the 1-page Bout-Sheet-Only layout without the bracket drawing (`08_bout_sheet_only.png`) directly into `docs/images/`.
  - Embedded high-resolution screenshots into `README.md` alongside comprehensive walkthroughs of all features.

### Decision 11: Fedora Linux Localhost Deployment Readiness & Hardening
- **Context**: Deploying Bracketman to other Fedora Linux machines (kiosk laptops, gym mini-PCs, or head-table workstations) requires zero cloud setup, zero telemetry prompts, predictable localhost binding, SELinux compliance, and automated installation.
- **Decision**:
  - **Automated Fedora Setup**: Added [setup_fedora.sh](file:///home/simon/Code/personal/bracketman/scripts/setup_fedora.sh) to detect Fedora/RHEL, verify Python 3.10+, provision virtual environment `.venv`, install `.[dev]`, ensure example datasets exist, and run pytest verification.
  - **Zero-Prompt Streamlit Config**: Created [.streamlit/config.toml](file:///home/simon/Code/personal/bracketman/.streamlit/config.toml) and passed `--browser.gatherUsageStats false` in `bracketman ui` to permanently silence first-run email prompts and disable telemetry.
  - **Path Resilience**: Added `_find_file()` fallback logic in [app.py](file:///home/simon/Code/personal/bracketman/src/bracketman/web/app.py) and [cli.py](file:///home/simon/Code/personal/bracketman/src/bracketman/cli.py) so static assets (`assets/logo.jpg`), example spreadsheets (`data/example_tournament.xlsx`), and default configs (`configs/default.yaml`) resolve properly regardless of current working directory.
  - **Custom Storage Path**: Added `BRACKETMAN_DATA_DIR` environment variable support in [store.py](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py) (defaults to `data/tournaments`).
  - **Systemd User & System Service**: Provided [bracketman.service](file:///home/simon/Code/personal/bracketman/systemd/bracketman.service) supporting unprivileged systemd user daemon execution (`systemctl --user enable --now bracketman`).
  - **SELinux & Rootless Container Support**: Added [Containerfile](file:///home/simon/Code/personal/bracketman/Containerfile) and [compose.yaml](file:///home/simon/Code/personal/bracketman/compose.yaml) configured with `:Z` volume relabeling for Fedora's default rootless Podman runtime.
  - **Standardized Packaging**: Added `requirements.txt`, `requirements-dev.txt`, and updated `[project.optional-dependencies]` in `pyproject.toml`.

### Decision 12: Windows Desktop Compatibility & 1-Click Bootstrapping
- **Context**: Coaches and head-table staff frequently bring Windows laptops to tournaments. Installation must not assume Bash, systemd, or Linux display servers, and should require zero command-line expertise.
- **Decision**:
  - **1-Click Windows Launcher**: Added [run_bracketman.bat](file:///home/simon/Code/personal/bracketman/run_bracketman.bat) in repository root. Detects system `python` or `py -3`, bootstraps `.venv`, installs dependencies, generates example data if absent, and opens Streamlit in user browser. Sets `chcp 65001` and `PYTHONUTF8=1` for UTF-8 terminal output.
  - **Automated PowerShell Installer**: Added [setup_windows.ps1](file:///home/simon/Code/personal/bracketman/scripts/setup_windows.ps1) with strict error handling, virtual environment setup, and pytest verification.
  - **Platform-Aware Headless Detection**: In [cli.py](file:///home/simon/Code/personal/bracketman/src/bracketman/cli.py#L316), scoped `DISPLAY`/`WAYLAND_DISPLAY` headless fallback strictly to `sys.platform.startswith("linux")`. Prevents Windows and macOS desktop sessions from erroneously defaulting to headless mode without auto-opening a browser tab.
  - **Explicit File Encodings & Path Safety**: All file writes, reads, and CSV streams enforce explicit `utf-8` or `utf-8-sig` to prevent default Windows-1252 (cp1252) encoding crashes.

### Decision 13: macOS Support & Native vs. Container Strategy
- **Context**: Coaches use macOS (Apple Silicon and Intel) alongside Windows and Linux. Additionally, macOS ships a stub Xcode `/usr/bin/python3` at version 3.9, which is older than Bracketman's `>=3.10` requirement.
- **Decision**:
  - **macOS Automated Setup**: Added [setup_macos.sh](file:///home/simon/Code/personal/bracketman/scripts/setup_macos.sh) that searches `/opt/homebrew/bin/python3` (Apple Silicon), `/usr/local/bin/python3` (Intel Homebrew), and `/Library/Frameworks/Python.framework` before falling back to `PATH`, verifying `sys.version_info >= (3, 10)` so it never trips on Xcode Python 3.9.
  - **1-Click Finder Launcher**: Added [run_bracketman.command](file:///home/simon/Code/personal/bracketman/run_bracketman.command) (`chmod +x`), allowing macOS users to double-click directly in Finder to bootstrap `.venv` and open the browser.
  - **Native `.venv` vs. Docker/Podman Guidance**: Documented that **Native `.venv`** is preferred on Windows and macOS tournament laptops (zero Linux VM overhead, instant startup, minimal RAM/battery usage), whereas **Podman/Docker** and **Native `.venv`** are equally first-class on Linux/Fedora where containers run natively on the host kernel without a VM.

### Decision 14: Dedicated Wrestler Lookup, Mat-Side Quick Actions & UI Attribution Footer
- **Context**: At a live tournament table, parents, coaches, and table workers frequently ask about a specific wrestler ("What bracket is Mason in?", "Who does he wrestle?", "Why was he scratched?"). Filtering whole bracket cards or using an LLM chatbot introduces unnecessary latency or complexity when instant lookup + 1-click adjustment is needed. Additionally, operators need quick access to the GitHub repository and documentation from the UI.
- **Decision**:
  - Added [`search_tournament_wrestlers`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1003) to search both active and scratched wrestlers across name, club/school, weight, bracket ID, division, age group, skill level, and status (`Active`, `Scratched`, `Flagged`, `Dual-Entry`).
  - Added the **🔍 Wrestler Lookup** tab (`_render_wrestler_lookup_tab`) in [app.py](file:///home/simon/Code/personal/bracketman/src/bracketman/web/app.py), providing a directory summary table and expandable wrestler cards with pod context, scheduled bout matchups, printable score sheet preview, and inline quick actions (edit weight/name/club/division/age group/skill level, move bracket ranked by suitability fit score, scratch, or restore).
  - Added a persistent footer in both the sidebar (`_render_sidebar_footer`) and the bottom of the main pane (`main()`) crediting creator **Simon Engelbert** and linking directly to the [GitHub Repository](https://github.com/sengelbert/bracketman), [User Guide](https://github.com/sengelbert/bracketman#readme), and [Architecture Docs](https://github.com/sengelbert/bracketman/blob/main/docs/ARCHITECTURE_AND_DECISIONS.md).
  - Added contextual workflow guides (`st.expander`), skipped-rows diagnostics, printing layout guides, and `help=` widget tooltips across every Streamlit tab (`_render_sidebar`, `_render_import_tab`, `_render_explorer_tab`, `_render_wrestler_lookup_tab`, `_render_tweak_and_regenerate_tab`, `_render_print_and_export_tab`, `_render_history_tab`, and `main()`) so volunteer table workers and tournament directors understand every setting and action without external manuals.

### Decision 15: Pre-Session Mat / Scoring Table Count, Load-Balanced Assignment & Sticky/Locked Mat Preservation
- **Context**: Tournament directors need to assign brackets and kids to specific mats/scoring tables (`Mat 1 .. Mat N`) early before the session starts so parents, coaches, and table workers know which mat each bracket is on and head tables can print score sheet packets per mat. Once mats are assigned and locked, late walk-ins and scratches must not reshuffle existing brackets across mats.
- **Decision**:
  - **Model & Config Support**: Added `mat_number: int | None = None` and `mat_label` (`"Mat N"` or `"Unassigned"`) to [`BracketGroup`](file:///home/simon/Code/personal/bracketman/src/bracketman/models.py#L197), and `mat_count: int = 4` + `auto_assign_mats: bool = True` to [`TournamentConfig`](file:///home/simon/Code/personal/bracketman/src/bracketman/config.py#L99) and [`configs/default.yaml`](file:///home/simon/Code/personal/bracketman/configs/default.yaml#L66).
  - **Contiguous Weight-Block Mat Load Balancer**: Implemented [`assign_mats_to_groups()`](file:///home/simon/Code/personal/bracketman/src/bracketman/grouping/madison.py#L559) supporting five strategies:
    1. `"coed_by_age_girls_together"`: Pools all `Girls` brackets across all age groups into a single `"Girls"` group (since Girls brackets are wrestled simultaneously) and distributes them evenly across mats `1 .. N`, while distributing each `Coed` age group (`4U, 6U, 8U, 10U, 12U, 15U`) equally across mats `1 .. N` by bracket count.
    2. `"equal_age_group"`: Within each `(division, age_group)`, distributes an equal number of brackets (`n // mat_count`, `±1`) across all mats `1 .. N` and allocates any `+1` remainder brackets to the mats with the **fewest total brackets** (`(mat_brackets[m], mat_bouts[m], m)`), ensuring both per-age-group bracket counts and total brackets per mat are strictly equalized (`±1`).
    3. `"balanced"` *(default)*: Within each `(division, age_group)` session, splits brackets into contiguous weight blocks and allocates any `n % mat_count` remainder blocks to the **least-loaded mats by bout count first** (`least_loaded[:rem]`) before sorting those mats by mat number (`Mat 1 .. Mat N`). This prevents lower-numbered mats (`Mat 1`) from accumulating extra remainder brackets across multiple age groups when `n < mat_count` or `n % mat_count != 0`.
    4. `"contiguous_blocks"`: Partitions the entire bracket list across the tournament into `mat_count` contiguous age/weight blocks of equal bout load (`Mat 1` = youngest/lightest .. `Mat N` = oldest/heaviest/Girls).
    5. `"round_robin"`: Cycles brackets `1 .. N` across mats in order.
  - **Sticky / Locked Mat Preservation Across Walk-Ins, Scratches & Regeneration**:
    - **Walk-Ins ([`add_walkin_wrestler`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L819))**: Adding a walk-in to an existing bracket keeps its `mat_number` unchanged and marks `locked = True`. Spinning off a new pod (`__NEW__`) automatically inherits the `mat_number` of the closest-weight bracket in the same `(division, age_group)` so the kid goes to the exact mat where their age/weight is already wrestling.
    - **Scratches & Restores ([`scratch_wrestler`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L929) & [`restore_scratched_wrestler`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1053))**: Scratching a wrestler recalculates the bracket's bouts in-place (e.g., 4-man to 3-man round-robin or 3-man to 2-man Best 2-of-3) while keeping `mat_number` fixed and locking the bracket. Original mat assignments are saved in `scratched_wrestlers` so restoring a wrestler restores their original mat.
    - **Targeted & Scope-Wide Regeneration ([`regenerate_brackets_by_ids`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L540), [`reoptimize_active_brackets`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L681), [`_resolve_inherited_mat`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L524))**: Locked brackets are never modified when `preserve_locked=True`. Even for unlocked brackets that are re-grouped or merged, prior wrestler/bucket mat assignments are captured before re-partitioning and restored via modal inheritance so mats never unexpectedly reset to `Mat 1`.
    - **Same-Mat Straggler Merge Preference, Division Uniqueness Guardrail & `NO MATCH` Status ([`_find_best_merge_candidate`](file:///home/simon/Code/personal/bracketman/src/bracketman/grouping/madison.py#L349), [`enforce_max_one_bracket_per_division`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1467))**: Solo straggler merge recommendations prioritize candidate brackets on the **same mat** and within the **same division** (including adjacent age/skill before cross-division merges), and strictly forbid merging a solo wrestler into a division (`Coed` or `Girls`) where that wrestler already has an active entry in another bracket. Added [`find_duplicate_division_entries()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1443) and [`enforce_max_one_bracket_per_division()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1467) (plus guardrails in [`move_wrestler()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L360), [`merge_brackets()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L462), and [`load_wrestlers()`](file:///home/simon/Code/personal/bracketman/src/bracketman/io/loader.py#L220)) to guarantee every wrestler is in at most **1 Coed** and **1 Girls** bracket across the tournament. When an unmatched dual-entry wrestler has no compatible bracket within weight range in their native division (e.g., a heavy Girls entry with no Girls opponent within spread), the entry is recorded with `entry_status: "no_match"` and displayed as **`NO MATCH`** (`⚪ No Match`) rather than `Scratched` across Wrestler Lookup, Manual Tweaks, and the Master Wrestler & Mat Handout.
  - **Store, CLI & Web UI Integration**:
    - Added [`assign_brackets_to_mats()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1128) (`preserve_locked=False` default for explicit rebalancing, plus `lock_assigned` and `skill_level` scope filtering) and [`set_bracket_mat()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py#L1185) (`lock_bracket=True` default) in `store.py`.
    - Upgraded **🏟️ Mat / Table Assignment & Load Balancer** in [`app.py`](file:///home/simon/Code/personal/bracketman/src/bracketman/web/app.py#L1051) with 1-click **⚖️ Rebalance / Auto-Assign Brackets Across N Mat(s)** (defaulting `Skip Locked` to `False` so rebalancing immediately redistributes all brackets unless `Skip Locked` is checked), **🎯 Move Brackets Across Mats** with source Mat # and Age Group filters + **📌 Move Selected Bracket(s)** and **📦 Move All N Matching Filter** buttons, and synced `on_change` mat selectors in **🔎 Bracket Explorer** so stale Streamlit widget state never overwrites rebalanced mats.
    - Exposed `[Mat N]` labels on walk-in and move-wrestler candidate dropdowns, pre-printed `<span class="mat-badge">MAT {N}</span>` on HTML score sheets, and added `Mat #` columns/filters across all UI tabs and CSV/XLSX/console exports.
  - **Printable Master Wrestler & Mat Directory Handout ([`export_printable_roster_html`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py#L1639) & `Master_Roster` Excel Tab)**:
    - Generates a print-ready HTML tournament handout (`roster_directory.html`) with an interactive toolbar switching between **6 Handout Views**: **Alphabetical (A–Z All Wrestlers)**, **Check-In by Age Group & Club (`Age -> Club A–Z -> Wrestler A–Z`)** for age-group check-in tables, **Sorted by Bracket ID (All Brackets in Seed Order)**, **Grouped by Mat # (`Mat 1 .. Mat N`)**, **Grouped by School / Club**, and **Grouped by Division & Age Group**, plus a **Bracket Size** filter (`1-Man Solo`, `2-Man`, `3-Man`, `4-Man`, `≤2-Man`, `≤3-Man`, `No Match`), a dynamic **Sort Rows** selector (`Bracket ID`, `Wrestler Name`, `Mat #`, `Weight`, `Club`, `Bracket Size (Small → Large)`, `Bracket Size (Large → Small)`, `⚠ Warnings & Merges First`), a **⚠ Warnings/Merges Only** filter checkbox, a **1 Age/Mat/Club Per Page** page-break toggle, and **Save as PDF** / **Save HTML** buttons next to **Print** (across populated brackets, blank sheets, and roster handouts) that dynamically update `document.title` so browser native vector PDF exports and HTML downloads both use filesystem-safe underscore-delimited filenames matching the currently displayed layout and filters. Also added a **Filter Bracket Size** selector and filter-aware underscore filenames in the **🖨️ Print & Export** Streamlit tab.
    - Every row displays a check-in box (`☐`), Wrestler Name, School/Club, Scale Weight, Division/Age/Skill (with original registered age/skill noted when merged), bold **`MAT #`** badge, **`Bracket ID` & weight range**, prominent **`⚠` warning & allowed-merge pills** (`⚠ WT SPREAD`, `⚠ MERGED SKILL`, `⚠ MERGED AGE`, `⚠ MERGED DIV`, `⚠ SAME CLUB`, `⚠ SOLO WRESTLER`, `⚠ OVERSIZED`, `⚠ NO MATCH`), Seed/Format/Bout count, and **Pod Opponents** (and excludes `no_match` entries from the `SCRATCHED / NO-SHOW WRESTLERS` table).
    - Added a matching alphabetical `Master_Roster` tab (with `Warnings / Merges` column) to [`export_xlsx_workbook`](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/csv_xlsx.py#L200) and exposed download/preview controls in both **🖨️ Print & Export** and **🔍 Wrestler Lookup**.

### Decision 16: Consistent Printout Headers, View Toolbars & Full Bracket Coverage Verification
- **Context**:
  - The Master Wrestler & Mat Directory Handout featured a polished dark-slate sticky interactive toolbar and a crisp, bold 2-row page header (`{TOURNAMENT} • {DATE}` left, boxed doc subtitle badge right, metadata strip below, 2.5px solid bottom border).
  - The Bracket & Bout Sheet printouts (`brackets.html`, `bout_sheets_only.html`, `blank_sheets.html`, and Streamlit sheet previews) previously used an older plain white-border toolbar and header layout without a matching subtitle badge or search/size controls.
  - On the **🛠️ Tweak & Regenerate by ID** tab, verification was limited to checking max 1 Coed / 1 Girls bracket uniqueness, without verifying that every registered/active wrestler actually had a bracket assignment or highlighting unbracketed, `NO MATCH`, or 1-man solo wrestlers.
- **Decision**:
  - **Unified Printout Header & View/Toolbar**:
    - Updated `_build_printable_html_document`, `_render_bout_and_tally_sheet`, `_render_blank_sheet_body`, and `_wrap_preview_html` in [html.py](file:///home/simon/Code/personal/bracketman/src/bracketman/exporters/html.py) to match the Master Wrestler Handout toolbar and header design:
      - Sticky dark slate `#1e293b` toolbar with screen backdrop `#eef2f6` (pure `#fff` on print media).
      - Action buttons styled consistently (`Refresh` slate `#475569`, `Save as PDF` teal `#0f766e`, `Save HTML` slate `#475569`, `Print` blue `#2563eb`), plus a **🔄 Refresh** button in **🖨️ Print & Export** to regenerate previews/exports from latest bracket state.
      - Defaulted Master Roster Handout `Sort Rows` (`#r-sort`) to **Bracket ID (`A–Z → Seed`)**, and defaulted bracket printouts & previews (`export_printable_html`, `export_blank_bracket_html`, `render_single_bracket_preview_html`, `render_blank_bracket_preview_html`, and Streamlit Print/Explorer views) to **Bout Sheet Only (No Bracket Drawing)** (`include_bracket_diagram=False`).
      - Added real-time **Search: Name or Bracket...** input (`f-search`) and **Bracket Size** filter (`f-size`) to the Bracket & Bout Sheet toolbar.
      - Standardized `.sheet-header` top row to `{TOURNAMENT} • {DATE}` (`font-size: 17px; font-weight: 900;`) on left, with boxed subtitle badge (`OFFICIAL BRACKET & BOUT SHEET` / `OFFICIAL BOUT SHEET` / `BLANK WRITE-IN ...`) and `MAT {N}` badge on right, separated by a clean `2.5px solid #000` bottom border while strictly preserving the single-page portrait height budget (< 960px).
  - **Full Bracket Coverage & Integrity Verification**:
    - Added [`verify_tournament_roster_and_brackets()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py) to check:
      1. Division entry uniqueness (max 1 Coed and max 1 Girls bracket per wrestler).
      2. Unbracketed registered wrestlers (wrestlers present in `tournament.result.wrestlers` but missing from `tournament.result.groups`).
      3. `NO MATCH` records in `scratched_wrestlers` (`entry_status == "no_match"`).
      4. Solo 1-wrestler pods (`g.size == 1`, 0 opponents/bouts scheduled).
    - Upgraded the top verification banner and button on **🛠️ Tweak & Regenerate by ID** (`_render_tweak_and_regenerate_tab` in [app.py](file:///home/simon/Code/personal/bracketman/src/bracketman/web/app.py)):
      - Displays green success if 100% of active wrestlers are placed in multi-wrestler brackets without duplicates.
      - Displays warning alert and detailed highlight cards for Division Duplicates, Unbracketed Registered Wrestlers, NO MATCH Entries, and 1-Man Solo Brackets with direct quick actions.
  - **Multi-Bracket Merge (2+ Brackets) & `NO MATCH` Target Placement**:
    - Added [`merge_multiple_brackets()`](file:///home/simon/Code/personal/bracketman/src/bracketman/store.py) to atomically validate division uniqueness and fold 1, 2, or more source brackets into a single target bracket. Updated **🔗 Merge Brackets (2 or More)** on **🛠️ Tweak & Regenerate by ID** (`app.py`) to use `st.multiselect` for source brackets with a live combined wrestler count indicator.
    - Updated `NO MATCH` and scratched wrestler placement controls in both **🔍 Wrestler Lookup** and **🛠️ Tweak & Regenerate by ID** (`app.py`) with a **Target Bracket** selector (same-division brackets ranked first by weight proximity) passing `target_group_id` to `restore_scratched_wrestler()`, and guarded `restore_scratched_wrestler()` in `store.py` so `"NO MATCH"` is never reused as a new bracket ID.


---

## 3. Repository Structure

```text
bracketman/
├── AGENTS.md                   # Agent directives: tests, docs, caveman token saving
├── pyproject.toml              # Build & dependency metadata (CLI + Streamlit + optional deps)
├── requirements.txt            # Core requirements specification
├── requirements-dev.txt        # Development and testing requirements
├── Containerfile               # Rootless container specification (Podman / Docker)
├── compose.yaml                # Localhost container compose definition (:Z SELinux volumes)
├── run_bracketman.bat          # 1-click Windows launcher & auto-bootstrapper
├── run_bracketman.command      # 1-click macOS Finder / Linux launcher & auto-bootstrapper
├── README.md                   # Quick start, usage, deployment, and CLI reference
├── .streamlit/
│   └── config.toml             # Streamlit localhost defaults & telemetry silencing
├── systemd/
│   └── bracketman.service      # Systemd user/system unit template for auto-boot
├── docs/
│   └── ARCHITECTURE_AND_DECISIONS.md  # Architectural specifications & decision log
├── configs/
│   └── default.yaml            # Tournament rules, divisions, age/skill aliases
├── scripts/
│   ├── setup_fedora.sh         # Turnkey Fedora Linux installer & verifier
│   ├── setup_macos.sh          # Turnkey macOS (Apple Silicon & Intel) installer & verifier
│   ├── setup_windows.ps1       # Automated Windows PowerShell installer & verifier
│   ├── generate_example_tournament.py # Synthetic tournament spreadsheet generator
│   └── take_screenshots.py    # Headless Selenium documentation screenshot taker
├── src/bracketman/
│   ├── models.py               # Wrestler, GroupRuleConfig, BracketGroup, Bout, TournamentResult
│   ├── config.py               # YAML config loader & hierarchical rule resolution
│   ├── store.py                # Tournament storage, walk-ins, scratches, manual tweaks, regeneration
│   ├── cli.py                  # CLI commands: inspect, build, ui, regenerate, reoptimize, init-config
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
