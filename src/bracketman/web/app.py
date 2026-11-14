"""Streamlit web UI for managing wrestling tournaments, tweaking brackets, and printing."""

from __future__ import annotations

from datetime import datetime
import re
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from bracketman.exporters.csv_xlsx import export_csv_files, export_xlsx_workbook
from bracketman.exporters.html import (
    export_blank_bracket_html,
    export_printable_html,
    export_printable_roster_html,
    render_blank_bracket_preview_html,
    render_single_bracket_preview_html,
)
from bracketman.models import BracketGroup, TournamentResult
from bracketman.store import (
    DEFAULT_STORE_DIR,
    SavedTournament,
    add_walkin_wrestler,
    assign_brackets_to_mats,
    create_tournament,
    delete_tournament,
    enforce_max_one_bracket_per_division,
    find_candidate_brackets_for_walkin,
    find_duplicate_division_entries,
    import_spreadsheet_to_tournament,
    list_tournaments,
    load_tournament,
    merge_brackets,
    merge_multiple_brackets,
    move_wrestler,
    regenerate_brackets_by_ids,
    reoptimize_active_brackets,
    restore_scratched_wrestler,
    save_tournament,
    scratch_wrestler,
    search_tournament_wrestlers,
    set_bracket_mat,
    swap_wrestlers,
    toggle_bracket_lock,
    update_wrestler_in_bracket,
    verify_tournament_roster_and_brackets,
)


def _find_file(rel_path: str | Path) -> Path:
    p = Path(rel_path)
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parents[3]
    candidate = repo_root / rel_path
    if candidate.exists():
        return candidate
    return p


DEFAULT_EXAMPLE_XLSX = _find_file("data/example_tournament.xlsx")
MERGE_ID_RE = re.compile(r"Merge into ([A-Z0-9-]+)")


def _extract_suggested_group_id(suggestion: str | None) -> str:
    if not suggestion:
        return None
    m = MERGE_ID_RE.search(suggestion)
    return m.group(1) if m else None


def _group_summary_label(g: BracketGroup) -> str:
    lock_icon = "🔒 " if g.locked else ""
    warn_icon = "⚠️ " if g.has_warnings else ""
    mat_tag = f"[Mat {g.mat_number}] " if g.mat_number is not None else "[Unassigned] "
    return (
        f"{lock_icon}{warn_icon}{mat_tag}{g.group_id} | {g.division} {g.age_group} {g.skill_level} | "
        f"{g.size} wrestlers ({g.weight_label}, spread {g.weight_spread_lbs:g}lb / {g.weight_spread_pct:.1f}%)"
    )


def _render_sidebar_footer() -> None:
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Created by **Simon Engelbert**  \n"
        "📦 [GitHub Repository](https://github.com/sengelbert/bracketman)  \n"
        "📖 [User Guide](https://github.com/sengelbert/bracketman#readme) • "
        "[Architecture Docs](https://github.com/sengelbert/bracketman/blob/main/docs/ARCHITECTURE_AND_DECISIONS.md)"
    )


def _render_sidebar() -> SavedTournament | None:
    logo_path = _find_file("assets/logo.jpg")
    if logo_path.exists():
        st.sidebar.image(str(logo_path), use_container_width=True)
    st.sidebar.title("Bracketman")
    st.sidebar.caption("Tournament Grouping & Bracket Manager")

    with st.sidebar.expander("🧭 Tournament Day Quick Guide", expanded=False):
        st.markdown(
            "1. **📥 Import Roster**: Paste a Google Sheet link or upload an `.xlsx`/`.csv` file in **Sheet Import & Sync** and set your **Mat Count**.\n"
            "2. **🏆 Review Pods & Mats**: Inspect brackets, check mat assignments, and resolve any `⚠️ Flagged` or `🧍 Solo` pods in **Brackets Explorer**.\n"
            "3. **🔍 Check-In & Lookup**: Use **Wrestler Lookup** or **Tweak & Regenerate** to see a wrestler's assigned **Mat #**, scratch no-shows, or add walk-ins.\n"
            "4. **🔄 Re-Balance**: Lock finalized brackets (`🔒`), then run **Rethink & Re-Optimize** or **Mat Load Balancer** to balance bouts across mats.\n"
            "5. **🖨️ Print Sheets**: Go to **Print & Export** to print 1-page mat score sheets (all at once or filtered by **Mat #**)."
        )

    tournaments = list_tournaments()
    if not tournaments and DEFAULT_EXAMPLE_XLSX.exists():
        t = create_tournament(name="Example Tournament")
        import_spreadsheet_to_tournament(t, DEFAULT_EXAMPLE_XLSX, mode="full_overwrite")
        tournaments = [t]

    slug_map = {t.slug: t for t in tournaments}

    with st.sidebar.expander("➕ Create New Tournament", expanded=not bool(tournaments)):
        st.caption("Start a separate tournament workspace. Each tournament saves its own brackets, mat assignments, walk-ins, scratches, and audit log.")
        with st.form("create_tournament_form", clear_on_submit=True):
            new_name = st.text_input(
                "Tournament Name",
                placeholder="e.g. Example Tournament",
                help="Official title printed at the top of every bracket score sheet.",
            )
            new_url = st.text_input(
                "Google Sheet URL (optional)",
                value="",
                placeholder="https://docs.google.com/spreadsheets/d/...",
                help="Paste any public or link-shared Google Sheet URL. You can also upload a local file later.",
            )
            new_mats = st.number_input(
                "Number of Mats / Scoring Tables",
                min_value=1,
                max_value=24,
                value=4,
                help="How many mats/tables you are running. Brackets and wrestlers will be automatically assigned across these mats.",
            )
            import_now = st.checkbox(
                "Import & build brackets immediately",
                value=True,
                help="If checked and a Google Sheet URL is provided, Bracketman downloads all team tabs and generates brackets right away.",
            )
            submitted = st.form_submit_button("Create Tournament", type="primary")
            if submitted:
                if not new_name.strip():
                    st.error("Please enter a tournament name.")
                else:
                    t = create_tournament(name=new_name.strip(), sheet_url=new_url.strip())
                    t.config.mat_count = int(new_mats)
                    save_tournament(t)
                    if import_now and new_url.strip():
                        try:
                            with st.spinner("Downloading Google Sheet and building brackets..."):
                                import_spreadsheet_to_tournament(
                                    t, new_url.strip(), mode="full_overwrite"
                                )
                        except Exception as exc:
                            st.error(f"Created tournament, but sheet import failed: {exc}")
                    st.session_state["active_tournament_slug"] = t.slug
                    st.rerun()

    if not tournaments:
        st.sidebar.info("Create a tournament above to get started.")
        _render_sidebar_footer()
        return None

    slugs = [t.slug for t in tournaments]
    default_idx = 0
    current_slug = st.session_state.get("active_tournament_slug")
    if current_slug in slugs:
        default_idx = slugs.index(current_slug)

    selected_slug = st.sidebar.selectbox(
        "Active Tournament",
        options=slugs,
        index=default_idx,
        format_func=lambda s: f"{slug_map[s].name} ({len(slug_map[s].result.groups)} brackets)",
        help="Switch between saved tournaments stored on this machine.",
    )
    st.session_state["active_tournament_slug"] = selected_slug
    active = load_tournament(selected_slug)

    actual_scratches_cnt = sum(1 for r in active.scratched_wrestlers if r.get("entry_status") != "no_match")
    no_match_cnt = sum(1 for r in active.scratched_wrestlers if r.get("entry_status") == "no_match")
    no_match_txt = f" | No Match: `{no_match_cnt}`" if no_match_cnt else ""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"**Entries:** `{len(active.result.wrestlers)}` *(Scratched: `{actual_scratches_cnt}`{no_match_txt})*  \n"
        f"**Brackets:** `{len(active.result.groups)}` &nbsp;|&nbsp; **Mats:** `{active.config.mat_count}`  \n"
        f"**Locked/Tweaked:** `{sum(1 for g in active.result.groups if g.locked or g.manually_modified)}`  \n"
        f"**Flagged:** `{sum(1 for g in active.result.groups if g.has_warnings)}`  \n"
        f"**Updated:** `{active.updated_at}`"
    )

    with st.sidebar.expander("🗑️ Delete Tournament"):
        st.warning(f"Delete **{active.name}** permanently from disk?")
        if st.button("Confirm Delete Tournament", key=f"del_{active.slug}"):
            delete_tournament(active.slug)
            st.session_state.pop("active_tournament_slug", None)
            st.rerun()

    _render_sidebar_footer()
    return active


def _render_import_tab(tournament: SavedTournament) -> None:
    st.subheader("📥 Spreadsheet Import, Grouping & Mat Settings")
    st.markdown(
        "Paste a **Google Sheet link** (all team tabs will be read automatically) or **upload an `.xlsx`/`.csv` file**."
    )

    with st.expander("ℹ️ Expected Spreadsheet Format & Automatic Normalization Rules", expanded=False):
        st.markdown(
            "- **Multi-Tab Support**: Each sheet/tab in your workbook is treated as a team/club tab (instruction preamble rows and blank template rows are skipped automatically).\n"
            "- **Recognized Columns**: `Weight`, `Wrestlers Name`, `Age Group` (`4U`, `6U`, `8U`, `10U`, `12U`, `14U`/`15U`), `School` / `Club`, `Ability` (`Novice`/`Beginner` or `Experienced`/`Advanced`), and optional `Boys / COED Bracket` & `Girls only Bracket` columns.\n"
            "- **Dual Entries**: Wrestlers marked with an `X` in both `Boys / COED Bracket` and `Girls only Bracket` are automatically entered into both divisions and flagged with `🔁 Dual-Entry`.\n"
            "- **Early Mat / Table Assignment**: Set your **Mat Count** below so brackets and kids are automatically balanced across `Mat 1 .. Mat N` as soon as you build brackets.\n"
            "- **Google Sheets Sharing**: Ensure your Google Sheet is set to *\"Anyone with the link can view\"* so Bracketman can download it without requiring Google Cloud credentials."
        )

    col_src1, col_src2 = st.columns([3, 2])
    with col_src1:
        sheet_url = st.text_input(
            "Google Spreadsheet URL",
            value=tournament.sheet_url or "",
            placeholder="https://docs.google.com/spreadsheets/d/.../edit",
            help="Paste the full Google Sheet URL or spreadsheet ID. All team tabs are imported automatically.",
        )
    with col_src2:
        uploaded_file = st.file_uploader(
            "Or Upload Local Spreadsheet (.xlsx / .csv)",
            type=["xlsx", "csv"],
            help="Upload a local Excel (.xlsx) workbook with one or more team tabs, or a flat CSV roster.",
        )

    st.markdown("#### Grouping Rules, Mat Count & Import Mode")
    st.caption(
        "Configure how the **Madison Dynamic Programming Engine** partitions wrestlers into weight-matched pods and assigns them to scoring tables/mats."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    cfg = tournament.config
    with c1:
        target_sz = st.number_input(
            "Target Bracket Size",
            min_value=2,
            max_value=8,
            value=int(cfg.default_rule.target_group_size),
            help="Ideal number of wrestlers per round-robin pod (standard is 4 wrestlers = 3 rounds / 6 bouts).",
        )
    with c2:
        max_sz = st.number_input(
            "Max Bracket Size",
            min_value=2,
            max_value=8,
            value=int(cfg.default_rule.max_group_size),
            help="Hard upper limit on wrestlers placed into a single bracket during automated grouping.",
        )
    with c3:
        min_sz = st.number_input(
            "Min Desired Size",
            min_value=2,
            max_value=6,
            value=int(cfg.default_rule.min_group_size),
            help="Minimum preferred bracket size. The DP algorithm heavily penalizes 1-man solo stragglers.",
        )
    with c4:
        base_spread_pct = st.number_input(
            "Base Max Spread % (<50 lbs)",
            min_value=3.0,
            max_value=25.0,
            value=float(cfg.default_rule.max_weight_spread_pct),
            step=0.5,
            help="Maximum allowed weight difference (%) between lightest and heaviest wrestler in a pod for light weights (<50 lbs).",
        )
    with c5:
        mat_count_val = st.number_input(
            "Mat Count (Tables / Mats)",
            min_value=1,
            max_value=24,
            value=int(getattr(cfg, "mat_count", 4) or 4),
            help="Number of mats/scoring tables in your gym. Brackets are assigned across Mat 1..N so kids, parents, and table workers know their mat early.",
        )

    o1, o2, o3, o4, o5 = st.columns(5)
    with o1:
        blend_skills_opt = st.checkbox(
            "Blend Beginner & Advanced (Avoid 1-Man & 2-Man Pods)",
            value=bool(getattr(cfg, "blend_skills_to_fill_brackets", True)),
            help="Priority order: Division (Locked) > Weight > Age > Skill > Team. Keeps pure Beginner/Advanced pods when numbers allow, and blends Beginner + Advanced of the same age/weight to fill 3–4 man brackets instead of leaving 1-man solo stragglers or 2-man brackets.",
        )
    with o2:
        prog_spread = st.checkbox(
            "Progressive Weight Spread",
            value=bool(cfg.default_rule.progressive_spread),
            help="Automatically scales allowed weight spread % slightly higher for upper weight brackets (50-75 lbs: +1%, 75-105 lbs: +2%, 105-135 lbs: +3.5%, 135+ lbs: +5%).",
        )
    with o3:
        sep_teams = st.checkbox(
            "Separate Teammates Across Pods",
            value=bool(cfg.default_rule.separate_teammates),
            help="Swaps boundary wrestlers of similar weight between adjacent pods to prevent teammates from wrestling each other.",
        )
    with o4:
        merge_ages = st.checkbox(
            "Auto-Merge Solo Age Stragglers",
            value=bool(cfg.allow_age_merge_for_stragglers),
            help="If a wrestler is still stranded alone in their age group, fold them into an adjacent age group if within safe weight limits.",
        )
    with o5:
        auto_mats = st.checkbox(
            "Auto-Assign Brackets to Mats",
            value=bool(getattr(cfg, "auto_assign_mats", True)),
            help="Automatically distribute brackets across Mat 1..N (keeping contiguous weights in each age group together while balancing total bouts per mat).",
        )
    merge_skills = bool(blend_skills_opt)

    locked_count = sum(1 for g in tournament.result.groups if g.locked or g.manually_modified)
    mode_options = ["full_overwrite", "preserve_locked"]
    mode_labels = {
        "full_overwrite": "🔄 Full Overwrite — Rebuild all brackets from scratch (discards manual moves & locks)",
        "preserve_locked": (
            f"🔒 Sync & Keep Locked/Tweaked Brackets ({locked_count} currently locked) — "
            "Update weights & only regroup unlocked wrestlers"
        ),
    }
    import_mode = st.radio(
        "When importing from spreadsheet:",
        options=mode_options,
        format_func=lambda m: mode_labels[m],
        horizontal=False,
        help="Use 'Full Overwrite' for initial setup, or 'Sync & Keep Locked' when pulling updated sheet rows after you have already hand-tweaked or locked brackets.",
    )

    btn_c1, btn_c2 = st.columns([1.6, 1.4])
    with btn_c1:
        do_import = st.button("🚀 Import Spreadsheet & Build Brackets", type="primary", use_container_width=True)
    with btn_c2:
        do_update_mats_only = st.button(
            f"🏟️ Save Mat Count ({int(mat_count_val)} Mats) & Re-Assign Existing Brackets",
            type="secondary",
            use_container_width=True,
            disabled=not bool(tournament.result.groups),
            help="Update the tournament's Mat Count and redistribute current brackets across Mat 1..N without re-importing the spreadsheet.",
        )

    if do_update_mats_only:
        cfg.mat_count = int(mat_count_val)
        cfg.auto_assign_mats = bool(auto_mats)
        assign_brackets_to_mats(
            tournament,
            mat_count=int(mat_count_val),
            strategy="balanced",
            preserve_locked=False,
        )
        st.success(f"Updated tournament to {int(mat_count_val)} mats and assigned all {len(tournament.result.groups)} brackets!")
        st.rerun()

    if do_import:
        # Persist updated rule settings onto tournament config
        cfg.default_rule.target_group_size = int(target_sz)
        cfg.default_rule.max_group_size = int(max_sz)
        cfg.default_rule.min_group_size = int(min_sz)
        cfg.default_rule.max_weight_spread_pct = float(base_spread_pct)
        cfg.default_rule.progressive_spread = bool(prog_spread)
        cfg.default_rule.separate_teammates = bool(sep_teams)
        cfg.blend_skills_to_fill_brackets = bool(blend_skills_opt)
        cfg.mat_count = int(mat_count_val)
        cfg.auto_assign_mats = bool(auto_mats)
        for ag_cfg in cfg.age_group_overrides.values():
            ag_cfg["target_group_size"] = int(target_sz)
            ag_cfg["max_group_size"] = int(max_sz)
            ag_cfg["max_weight_spread_pct"] = float(base_spread_pct)
            for sk_cfg in ag_cfg.get("skills", {}).values():
                sk_cfg["target_group_size"] = int(target_sz)
                sk_cfg["max_group_size"] = int(max_sz)

        try:
            with st.spinner("Reading tabs, building Madison weight brackets, and assigning mats..."):
                if uploaded_file is not None:
                    suffix = Path(uploaded_file.name).suffix or ".xlsx"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = Path(tmp.name)
                    import_spreadsheet_to_tournament(
                        tournament,
                        tmp_path,
                        mode=import_mode,
                        merge_skills=merge_skills,
                        merge_ages=merge_ages,
                    )
                    tmp_path.unlink(missing_ok=True)
                elif sheet_url.strip():
                    import_spreadsheet_to_tournament(
                        tournament,
                        sheet_url.strip(),
                        mode=import_mode,
                        merge_skills=merge_skills,
                        merge_ages=merge_ages,
                    )
                else:
                    st.error("Please provide a Google Sheet URL or upload a spreadsheet file.")
                    return
            st.success(
                f"Built {len(tournament.result.groups)} brackets across "
                f"{len(tournament.result.wrestlers)} wrestler entries on {cfg.mat_count} mats!"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to import spreadsheet: {exc}")

    if tournament.result.skipped_rows:
        with st.expander(f"⚠️ Skipped Spreadsheet Rows ({len(tournament.result.skipped_rows)}) — Click to Inspect", expanded=True):
            st.caption(
                "These rows had a wrestler name or data entered, but were skipped (usually due to a missing scale weight). "
                "Fill in their weight on the spreadsheet and re-sync, or add them via **➕ Add Walk-In Wrestler**."
            )
            st.dataframe(tournament.result.skipped_rows, use_container_width=True, hide_index=True)


def _render_explorer_tab(tournament: SavedTournament) -> None:
    groups = tournament.result.groups
    if not groups:
        st.info("No brackets built yet. Go to **📥 Sheet Import & Sync** to load a Google Sheet or Excel file.")
        return

    cfg = tournament.config
    mat_count = max(1, int(getattr(cfg, "mat_count", 4) or 4))

    st.subheader("🏆 Tournament Brackets Explorer")
    st.caption(
        "Browse all generated weight brackets, inspect live printable score sheets, assign or filter by **Mat #**, "
        "resolve flagged warnings, and lock finalized brackets (`🔒`) so future re-optimizations leave them untouched."
    )

    # KPI Row
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric(
        "Wrestler Entries",
        len(tournament.result.wrestlers),
        help="Total active wrestler entries across all divisions (dual-division wrestlers count once per division).",
    )
    k2.metric(
        "Total Brackets",
        len(groups),
        help="Total number of pods/weight brackets currently active in the tournament.",
    )
    k3.metric(
        "Total Bouts",
        sum(len(g.bouts) for g in groups),
        help="Total scheduled matches across all brackets.",
    )
    k4.metric(
        "Mats / Tables",
        mat_count,
        help="Configured number of mats/tables for this tournament.",
    )
    k5.metric(
        "4-Man / 3-Man / 2-Man",
        f"{sum(1 for g in groups if g.size==4)} / {sum(1 for g in groups if g.size==3)} / {sum(1 for g in groups if g.size==2)}",
        help="Breakdown of pod sizes: 4-man (6 bouts), 3-man (3 bouts), and 2-man Best-of-3 (2-3 bouts).",
    )
    k6.metric(
        "Solo / Flagged",
        f"{sum(1 for g in groups if g.size==1)} / {sum(1 for g in groups if g.has_warnings)}",
        help="Solo (1-wrestler) pods and brackets flagged for exceeding progressive weight spread thresholds.",
    )

    # Division / Age / Skill Summary Table & Mat Distribution
    with st.expander("📊 Division / Age Group / Skill & Mat Load Summary Breakdown", expanded=True):
        st.caption("High-level summary of wrestler counts, bracket counts, mat assignments, and average weight spreads.")
        buckets: dict[tuple[str, str, str], list[BracketGroup]] = {}
        for g in groups:
            buckets.setdefault((g.division, g.age_group, g.skill_level), []).append(g)

        summary_rows = []
        for (div, age, skill), grps in buckets.items():
            multi = [g for g in grps if g.size > 1]
            avg_pct = sum(g.weight_spread_pct for g in multi) / len(multi) if multi else 0.0
            avg_lbs = sum(g.weight_spread_lbs for g in multi) / len(multi) if multi else 0.0
            mats_used = sorted({g.mat_number for g in grps if g.mat_number is not None})
            mats_str = ", ".join(f"Mat {m}" for m in mats_used) if mats_used else "Unassigned"
            summary_rows.append(
                {
                    "Division": div,
                    "Age Group": age,
                    "Skill Level": skill,
                    "Wrestlers": sum(g.size for g in grps),
                    "Brackets": len(grps),
                    "Assigned Mats": mats_str,
                    "Weight Range": f"{min(g.min_weight for g in grps):g}–{max(g.max_weight for g in grps):g} lbs",
                    "Avg Spread (lbs)": f"{avg_lbs:.1f} lbs",
                    "Avg Spread (%)": f"{avg_pct:.1f}%",
                    "Solo / Warnings": sum(1 for g in grps if g.has_warnings),
                }
            )
        st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    # Filter Bar
    f1, f2, f3, f4, f5, f6 = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 2.0])
    divisions = ["All"] + list(dict.fromkeys(g.division for g in groups))
    ages = ["All"] + list(dict.fromkeys(g.age_group for g in groups))
    skills = ["All"] + list(dict.fromkeys(g.skill_level for g in groups))
    mat_nums_present = sorted({g.mat_number for g in groups if g.mat_number is not None} | set(range(1, mat_count + 1)))
    mat_filter_opts = ["All"] + [f"Mat {m}" for m in mat_nums_present]
    if any(g.mat_number is None for g in groups):
        mat_filter_opts.append("Unassigned")

    with f1:
        sel_div = st.selectbox("Division", divisions, key="exp_div", help="Filter brackets by division (Coed or Girls).")
    with f2:
        sel_age = st.selectbox("Age Group", ages, key="exp_age", help="Filter brackets by age group (e.g. 6U, 8U, 10U, 12U, 15U).")
    with f3:
        sel_skill = st.selectbox("Skill Level", skills, key="exp_skill", help="Filter brackets by experience tier (Beginner or Advanced).")
    with f4:
        sel_mat = st.selectbox("Mat #", mat_filter_opts, key="exp_mat", help="Filter brackets assigned to a specific mat/scoring table.")
    with f5:
        sel_status = st.selectbox(
            "Filter Status",
            ["All Brackets", "⚠️ Flagged / Warnings Only", "🧍 Solo Wrestlers Only", "🔒 Locked / Tweaked Only"],
            key="exp_status",
            help="Quickly isolate brackets that need director review (Flagged/Solo) or brackets you've already locked.",
        )
    with f6:
        search_q = st.text_input(
            "Search Bracket ID, Wrestler, or Club",
            key="exp_search",
            placeholder="e.g. COED-8U-BEG-01, Smith, Mat 1...",
            help="Filter bracket cards to those containing a matching bracket ID, wrestler name, club, or mat.",
        ).strip().lower()

    filtered: list[BracketGroup] = []
    for g in groups:
        if sel_div != "All" and g.division != sel_div:
            continue
        if sel_age != "All" and g.age_group != sel_age:
            continue
        if sel_skill != "All" and g.skill_level != sel_skill:
            continue
        if sel_mat != "All":
            if sel_mat == "Unassigned" and g.mat_number is not None:
                continue
            elif sel_mat.startswith("Mat ") and g.mat_number != int(sel_mat.split()[1]):
                continue
        if sel_status == "⚠️ Flagged / Warnings Only" and not g.has_warnings:
            continue
        if sel_status == "🧍 Solo Wrestlers Only" and g.size != 1:
            continue
        if sel_status == "🔒 Locked / Tweaked Only" and not (g.locked or g.manually_modified):
            continue
        if search_q:
            haystack = " ".join(
                [g.group_id, g.mat_label] + [f"{w.name} {w.team} {w.team_tab}" for w in g.wrestlers]
            ).lower()
            if search_q not in haystack:
                continue
        filtered.append(g)

    exp_c1, exp_c2 = st.columns([3.2, 1.8])
    with exp_c1:
        st.caption(
            f"Showing **{len(filtered)}** of **{len(groups)}** brackets &nbsp;&bull;&nbsp; "
            "💡 *Tip: Click any bracket below to view its 1-page printable score sheet, change its **Mat #**, merge solo stragglers, or lock (`🔒`) the pod.*"
        )
    with exp_c2:
        explorer_show_diagram = st.checkbox(
            "Include Top Bracket Drawing on Sheet Preview",
            value=False,
            key="exp_show_bracket_diagram",
            help="Check to include the top bracket drawing, or leave unchecked for the default 'Bout Sheet Only' layout (larger fonts & period scoreboxes).",
        )

    mat_assign_choices = [None] + list(range(1, max(mat_count, max(mat_nums_present, default=1)) + 1))

    def _on_explorer_mat_change(tourney: SavedTournament, gid: str, s_key: str) -> None:
        chosen_mat = st.session_state.get(s_key)
        set_bracket_mat(tourney, [gid], mat_number=chosen_mat, lock_bracket=True)

    for g in filtered:
        with st.expander(_group_summary_label(g), expanded=(len(filtered) <= 6 or g.has_warnings)):
            top_l, top_m, top_r = st.columns([3.3, 1.1, 0.9])
            with top_l:
                fmt_display = "best_of_3 (Best 2 out of 3)" if g.size == 2 or g.bracket_format == "best_of_3" else g.bracket_format
                st.markdown(
                    f"**Bracket ID:** `{g.group_id}` &nbsp;|&nbsp; "
                    f"**Assigned Mat:** `{g.mat_label}` &nbsp;|&nbsp; "
                    f"**Format:** `{fmt_display}` &nbsp;|&nbsp; "
                    f"**Spread:** `{g.weight_spread_lbs:g} lbs ({g.weight_spread_pct:.1f}%)` "
                    f"*(Max `<= {g.allowed_spread_lbs:g} lbs / {g.allowed_spread_pct:.1f}%`)*"
                )
            with top_m:
                sel_key = f"exp_mat_sel_{g.group_id}"
                st.session_state[sel_key] = g.mat_number if g.mat_number in mat_assign_choices else None
                st.selectbox(
                    "Assign Mat / Table",
                    options=mat_assign_choices,
                    format_func=lambda m: f"🏟️ Mat {m}" if m is not None else "Unassigned",
                    key=sel_key,
                    label_visibility="collapsed",
                    on_change=_on_explorer_mat_change,
                    args=(tournament, g.group_id, sel_key),
                    help="Assign or move this bracket to a specific mat/table.",
                )
            with top_r:
                lock_label = "🔓 Unlock" if g.locked else "🔒 Lock Bracket"
                if st.button(
                    lock_label,
                    key=f"lock_btn_{g.group_id}",
                    use_container_width=True,
                    help="Locked brackets are protected from automated 'Rethink & Re-Optimize' runs and 'Sync & Keep Locked' imports.",
                ):
                    toggle_bracket_lock(tournament, [g.group_id], locked=not g.locked)
                    st.rerun()

            if g.flags:
                for fl_idx, fl in enumerate(g.flags):
                    if fl.severity == "warning":
                        st.warning(f"**[{fl.code}]** {fl.message}")
                    else:
                        st.info(f"**[{fl.code}]** {fl.message}")
                    if fl.suggestion:
                        target_gid = _extract_suggested_group_id(fl.suggestion)
                        sc1, sc2 = st.columns([3, 1])
                        sc1.markdown(f"💡 **Recommendation:** {fl.suggestion}")
                        if target_gid and sc2.button(
                            f"Merge into {target_gid}",
                            key=f"quick_merge_{g.group_id}_{fl_idx}",
                            type="primary",
                            help=f"Immediately fold {g.group_id} into {target_gid} and recalculate bouts.",
                        ):
                            try:
                                merge_brackets(tournament, g.group_id, target_gid)
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

            bout_count = len(g.bouts) if g.bouts else 1
            base_h = 560 if explorer_show_diagram else 490
            row_h = 82 if explorer_show_diagram else 98
            card_height = max(680, base_h + bout_count * row_h + g.size * 24)
            components.html(
                render_single_bracket_preview_html(
                    g,
                    tournament_name=tournament.name,
                    include_bracket_diagram=explorer_show_diagram,
                ),
                height=card_height,
                scrolling=False,
            )

            with st.expander(f"❌ Scratch a No-Show from {g.group_id}", expanded=False):
                st.caption("Remove a no-show wrestler from this bracket and recalculate bouts for the remaining pod.")
                w_scratch_opts = {w.id: f"{w.name} ({w.weight:g} lbs, {w.display_team})" for w in g.wrestlers}
                c_sw1, c_sw2 = st.columns([3, 1])
                sw_wid = c_sw1.selectbox(
                    "Wrestler to scratch",
                    options=list(w_scratch_opts.keys()),
                    format_func=lambda wid: w_scratch_opts[wid],
                    key=f"qscratch_sel_{g.group_id}",
                )
                if c_sw2.button("Confirm Scratch", key=f"qscratch_btn_{g.group_id}", type="secondary"):
                    scratch_wrestler(tournament, sw_wid, group_id=g.group_id)
                    st.success("Wrestler scratched and bracket updated!")
                    st.rerun()


def _render_tweak_and_regenerate_tab(tournament: SavedTournament) -> None:
    groups = tournament.result.groups
    if not groups:
        st.info("No brackets available yet. Go to **📥 Sheet Import & Sync** to import a spreadsheet first.")
        return

    cfg = tournament.config
    all_gids = [g.group_id for g in groups]
    gid_map = {g.group_id: g for g in groups}

    with st.expander("💡 How to Handle Walk-Ins, Scratches, Mat Assignments & Re-Optimization", expanded=False):
        st.markdown(
            """
            1. **➕ Walk-In Registration**: Enter a late registrant's name, scale weight, school/club, and division/age/skill. The **Target Placement** dropdown ranks existing brackets by weight proximity, open capacity, and teammate avoidance, or lets you spin off a brand-new bracket.
            2. **❌ No-Show Scratches & Restore**: Remove a wrestler who didn't make weight or didn't show up. Bouts for the remaining pod are recalculated immediately. Made a mistake? Click **↩️ Restore** to put them right back.
            3. **🔄 Refresh & Rethink (Madison DP Engine)**:
               - **By Division / Age Group**: Pools all active wrestlers in that scope (excluding scratches, including walk-ins) and re-runs the dynamic programming optimizer. Any bracket marked **🔒 Locked** is preserved untouched unless you uncheck *Preserve Locked Brackets*.
               - **Targeted by Bracket ID(s)**: Re-runs the optimizer on *only* the 1–3 specific brackets you select (with optional cross-skill/age pooling for solo wrestlers).
            4. **🏟️ Mat / Table Assignment & Load Balancer**: Configure your gym's **Mat Count** and auto-balance all brackets (or a specific age session) across `Mat 1 .. Mat N`, or manually assign specific brackets to a table.
            5. **➡️ Manual Move / 🔀 Swap / 🔗 Merge / ✏️ Edit**: Surgical overrides automatically mark the affected bracket(s) as **🔒 Locked** so future bulk re-optimizations won't overwrite your hand-crafted adjustments.
            """
        )

    # Roster & Bracket Placement Integrity Verification
    verification = verify_tournament_roster_and_brackets(tournament)
    dup_div_entries = verification["dup_div_entries"]
    unbracketed_wrestlers = verification["unbracketed_wrestlers"]
    no_match_entries = verification["no_match_entries"]
    solo_brackets = verification["solo_brackets"]
    has_placement_issues = bool(dup_div_entries or unbracketed_wrestlers or no_match_entries or solo_brackets)

    with st.container(border=True):
        v_col1, v_col2 = st.columns([3, 1.3])
        with v_col1:
            if not has_placement_issues:
                st.success(
                    f"✅ **Roster & Bracket Integrity Verified:** All **{verification['total_active_wrestlers']}** active wrestlers are placed in brackets. "
                    f"No unbracketed or NO MATCH wrestlers, no 1-man solo brackets, and max 1 Coed / 1 Girls bracket enforced."
                )
            else:
                issue_summary = []
                if dup_div_entries:
                    issue_summary.append(f"**{len(dup_div_entries)}** division duplicate(s)")
                if unbracketed_wrestlers:
                    issue_summary.append(f"**{len(unbracketed_wrestlers)}** unbracketed wrestler(s)")
                if no_match_entries:
                    issue_summary.append(f"**{len(no_match_entries)}** NO MATCH entry(ies)")
                if solo_brackets:
                    issue_summary.append(f"**{len(solo_brackets)}** 1-man solo bracket(s)")
                st.warning(
                    f"⚠️ **Roster & Bracket Placement Alert:** Found {', '.join(issue_summary)}. Review details below."
                )
        with v_col2:
            if st.button(
                "🛡️ Verify Roster & Brackets",
                key="btn_reverify_roster_and_brackets",
                use_container_width=True,
                help="Scan all active wrestlers, verify placement in brackets, check for unbracketed or NO MATCH entries, and enforce max 1 Coed / 1 Girls bracket.",
            ):
                _, fix_actions = enforce_max_one_bracket_per_division(tournament)
                fresh_ver = verify_tournament_roster_and_brackets(tournament)
                if fix_actions:
                    for act in fix_actions:
                        st.success(act)
                if fresh_ver["all_clear"]:
                    st.toast("Verified: All wrestlers are placed in brackets and division rules satisfied!", icon="✅")
                else:
                    st.toast(
                        f"Found {len(fresh_ver['unbracketed_wrestlers'])} unbracketed, "
                        f"{len(fresh_ver['no_match_entries'])} NO MATCH, "
                        f"{len(fresh_ver['solo_brackets'])} solo, "
                        f"{len(fresh_ver['dup_div_entries'])} duplicates.",
                        icon="⚠️",
                    )
                st.rerun()

        # Detailed Highlights for Issues Found
        if dup_div_entries:
            st.markdown(f"##### 🚨 Division Duplicate Entries ({len(dup_div_entries)})")
            for d_item in dup_div_entries:
                br_str = ", ".join(
                    f"`{g.group_id}` (reg: {w.division}, {w.weight:g} lbs)"
                    for g, w in d_item["entries"]
                )
                st.markdown(f"- **{d_item['name']}** ({d_item['team_key']}) in {len(d_item['entries'])} **{d_item['bracket_division']}** brackets: {br_str}")
            if st.button(
                "🛡️ Enforce Max 1 Coed & 1 Girls Bracket Per Wrestler Now",
                type="primary",
                key="btn_enforce_div_unique_inline",
                use_container_width=True,
                help="Removes duplicate same-division entries and re-homes misplaced dual-entry Girls entries into a compatible Girls bracket (or retires redundant duplicate).",
            ):
                _, fix_actions = enforce_max_one_bracket_per_division(tournament)
                for act in fix_actions:
                    st.success(act)
                st.rerun()

        if unbracketed_wrestlers:
            st.markdown(f"##### ⚠️ Unbracketed Registered Wrestlers ({len(unbracketed_wrestlers)})")
            st.caption("These registered wrestlers are in the tournament roster but not currently assigned to any active bracket.")
            for uw in unbracketed_wrestlers:
                st.markdown(
                    f"- **{uw.name}** ({uw.weight:g} lbs, {uw.display_team}) &mdash; "
                    f"**{uw.division}** {uw.age_group} {uw.skill_level} (ID: `{uw.id}`)"
                )

        if no_match_entries:
            st.markdown(f"##### ⚪ NO MATCH Entries ({len(no_match_entries)})")
            st.caption("Wrestlers without a suitable opponent within weight spread in their division.")
            for sc_rec in no_match_entries:
                st.markdown(
                    f"- **{sc_rec.get('name')}** ({sc_rec.get('weight', 0):g} lbs, {sc_rec.get('team')}) &mdash; "
                    f"**{sc_rec.get('division')}** {sc_rec.get('age_group')} {sc_rec.get('skill_level')} "
                    f"&bull; *{sc_rec.get('reason', 'No opponent within weight range')}*"
                )

        if solo_brackets:
            st.markdown(f"##### ⚠️ 1-Man Solo Brackets ({len(solo_brackets)})")
            st.caption("Brackets with only 1 wrestler (0 opponents / 0 bouts scheduled).")
            for sg in solo_brackets:
                sw = sg.wrestlers[0]
                st.markdown(
                    f"- Bracket **`{sg.group_id}`** &mdash; **{sw.name}** ({sw.weight:g} lbs, {sw.display_team}) &bull; "
                    f"*{sg.division} {sg.age_group} {sg.skill_level}*"
                )

    # 1. Walk-Ins & Scratches Section
    st.subheader("⚡ Walk-In Registration & No-Show Scratches")
    st.caption("Quickly handle wrestlers who show up unannounced at weigh-ins, or scratch wrestlers who didn't show up.")

    col_walkin, col_scratch = st.columns(2)

    with col_walkin:
        with st.container(border=True):
            st.markdown("#### ➕ Add Walk-In Wrestler")
            st.caption("Evaluates all brackets in the selected bucket and recommends the safest weight & club fit.")
            w_name = st.text_input(
                "Wrestler Name",
                key="wi_name",
                placeholder="e.g. John Doe",
                help="Full name of the walk-in wrestler.",
            )
            w_c1, w_c2 = st.columns(2)
            w_wt = w_c1.number_input(
                "Scale Weight (lbs)",
                min_value=20.0,
                max_value=285.0,
                value=55.0,
                step=0.1,
                key="wi_wt",
                help="Exact weight from the scale in pounds.",
            )
            w_team = w_c2.text_input(
                "School / Club",
                value="Unattached",
                key="wi_team",
                help="Used to check for same-club teammate collisions in candidate brackets.",
            )

            w_c3, w_c4, w_c5 = st.columns(3)
            cfg = tournament.config
            div_opts = list(cfg.divisions)
            age_opts = list(cfg.age_groups)
            skill_opts = list(cfg.skill_levels)

            w_div = w_c3.selectbox("Division", div_opts, key="wi_div", help="Coed or Girls division.")
            w_age = w_c4.selectbox("Age Group", age_opts, index=min(1, len(age_opts)-1), key="wi_age", help="Age group bucket.")
            w_skill = w_c5.selectbox("Skill Level", skill_opts, key="wi_skill", help="Experience / skill level.")

            # Look up candidate brackets
            candidates = find_candidate_brackets_for_walkin(
                tournament,
                weight=float(w_wt),
                division=w_div,
                age_group=w_age,
                skill_level=w_skill,
                team=w_team,
            )

            target_options = ["AUTO", "__NEW__"] + [c["group_id"] for c in candidates]
            def _format_target(opt: str) -> str:
                if opt == "AUTO":
                    best = next((c for c in candidates if c["current_size"] < c["max_size"]), None)
                    if best:
                        return f"🎯 Auto-Place into Best Bracket ([{best['mat_label']}] {best['group_id']}: {best['current_weights']}, size {best['current_size']}->{best['current_size']+1})"
                    return "🎯 Auto-Place (Will create new bracket on same age group's mat if none fits)"
                if opt == "__NEW__":
                    return f"➕ Create New Bracket in {w_div} {w_age} {w_skill} (Inherits age group's mat)"
                cand = next((c for c in candidates if c["group_id"] == opt), None)
                if cand:
                    fit_badge = "✅" if cand["fits_spread"] else "⚠️"
                    tm_badge = " [Teammate in pod!]" if cand["has_teammate"] else ""
                    return f"{fit_badge} [{cand['mat_label']}] {opt} ({cand['current_weights']}, size {cand['current_size']}/{cand['max_size']}, spread {cand['new_spread_lbs']:g}lb / {cand['new_spread_pct']:.1f}%){tm_badge}"
                return opt

            target_choice = st.selectbox(
                "Target Placement",
                options=target_options,
                format_func=_format_target,
                key="wi_target",
                help="✅ indicates the bracket stays within the allowed weight spread %. ⚠️ indicates adding this wrestler exceeds the spread limit or pod capacity.",
            )

            if st.button(
                "Add Walk-In to Bracket",
                type="primary",
                key="btn_add_walkin",
                help="Insert the walk-in wrestler into the chosen bracket and regenerate its round-robin bouts.",
            ):
                if not w_name.strip():
                    st.error("Please enter a wrestler name.")
                else:
                    try:
                        _, new_w, placed_in = add_walkin_wrestler(
                            tournament,
                            name=w_name.strip(),
                            weight=float(w_wt),
                            team=w_team.strip(),
                            division=w_div,
                            age_group=w_age,
                            skill_level=w_skill,
                            target_group_id=target_choice,
                        )
                        st.success(f"Added {new_w.name} ({new_w.weight:g} lbs) to {placed_in}!")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    with col_scratch:
        with st.container(border=True):
            st.markdown("#### ❌ Scratch No-Show Wrestler")
            st.caption("Removes a wrestler from their pod, recalculates remaining bouts, and keeps a restorable record.")
            # Build active wrestler lookup
            all_active_wrestlers = []
            for g in groups:
                for w in g.wrestlers:
                    all_active_wrestlers.append((w, g.group_id))

            all_active_wrestlers.sort(key=lambda item: (item[0].name.lower(), item[0].weight))
            w_lookup = {f"{item[0].id}_{item[1]}": item for item in all_active_wrestlers}

            if not all_active_wrestlers:
                st.info("No active wrestlers found.")
            else:
                sel_w_key = st.selectbox(
                    "Search & Select Wrestler to Scratch",
                    options=list(w_lookup.keys()),
                    format_func=lambda k: f"{w_lookup[k][0].name} ({w_lookup[k][0].weight:g} lbs, {w_lookup[k][0].team}) &mdash; {w_lookup[k][1]}",
                    key="scratch_select",
                    help="Start typing a wrestler's name to filter the dropdown.",
                )
                sc_reason = st.text_input(
                    "Scratch Reason",
                    value="No-show",
                    key="sc_reason",
                    help="Recorded in the audit log and scratch history (e.g., No-show, Injury, Illness).",
                )
                sc_all = st.checkbox(
                    "Scratch from both Coed & Girls (if dual entry)",
                    value=True,
                    key="sc_all",
                    help="If a girl is entered in both Girls and Coed divisions, scratching her removes both entries at once.",
                )

                if st.button(
                    "Confirm Scratch Wrestler",
                    type="secondary",
                    key="btn_confirm_scratch",
                    help="Remove the wrestler and immediately update the bracket's bouts.",
                ):
                    w_obj, g_id = w_lookup[sel_w_key]
                    try:
                        _, scratched_gids = scratch_wrestler(
                            tournament,
                            wrestler_id=w_obj.id,
                            group_id=g_id if not sc_all else None,
                            scratch_all_divisions=sc_all,
                            reason=sc_reason.strip(),
                        )
                        st.success(f"Scratched {w_obj.name} from {', '.join(scratched_gids)}!")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            actual_scratch_items = [
                (s_idx, sc_rec)
                for s_idx, sc_rec in enumerate(tournament.scratched_wrestlers)
                if sc_rec.get("entry_status") != "no_match"
            ]
            no_match_items = [
                (s_idx, sc_rec)
                for s_idx, sc_rec in enumerate(tournament.scratched_wrestlers)
                if sc_rec.get("entry_status") == "no_match"
            ]
            if actual_scratch_items:
                st.markdown("---")
                st.markdown(f"**Recently Scratched ({len(actual_scratch_items)}):**")
                for s_idx, sc_rec in actual_scratch_items:
                    sc_col1, sc_col2 = st.columns([3, 1])
                    sc_col1.caption(
                        f"• **{sc_rec['name']}** ({sc_rec['weight']:g} lbs, {sc_rec['team']}) &mdash; "
                        f"From {', '.join(sc_rec.get('original_groups', []))} ({sc_rec.get('reason', 'No-show')})"
                    )
                    if sc_col2.button(
                        "↩️ Restore",
                        key=f"btn_restore_{s_idx}",
                        help="Put this wrestler back into their original bracket (or best available pod).",
                    ):
                        try:
                            restore_scratched_wrestler(tournament, scratch_index=s_idx)
                            st.success(f"Restored {sc_rec['name']}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

            if no_match_items:
                st.markdown("---")
                st.markdown(f"**⚪ No-Match Entries ({len(no_match_items)}):**")
                for s_idx, sc_rec in no_match_items:
                    nm_div = str(sc_rec.get("division", "Girls"))
                    nm_wt = float(sc_rec.get("weight", 0.0))
                    same_div_gids = [
                        g.group_id
                        for g in sorted(
                            [grp for grp in groups if grp.division == nm_div],
                            key=lambda grp: abs(((grp.min_weight + grp.max_weight) / 2.0) - nm_wt),
                        )
                    ]
                    other_gids = [g.group_id for g in groups if g.division != nm_div]
                    nm_opts = same_div_gids + ["__NEW__"] + other_gids
                    st.caption(
                        f"• **{sc_rec['name']}** ({nm_wt:g} lbs, {sc_rec['team']}, "
                        f"{nm_div} {sc_rec.get('age_group', '')} {sc_rec.get('skill_level', '')}) &mdash; "
                        f"**NO MATCH** ({sc_rec.get('reason', 'No opponent within weight range')})"
                    )
                    nm_c1, nm_c2 = st.columns([2.6, 1])
                    nm_target = nm_c1.selectbox(
                        "Target Bracket",
                        options=nm_opts,
                        format_func=lambda opt, _div=nm_div: (
                            f"➕ Create New {_div} Bracket" if opt == "__NEW__" else _group_summary_label(gid_map[opt])
                        ),
                        key=f"sel_nomatch_target_{s_idx}",
                        label_visibility="collapsed",
                    )
                    if nm_c2.button(
                        "↩️ Place",
                        key=f"btn_restore_nomatch_{s_idx}",
                        use_container_width=True,
                        help="Place this NO MATCH entry into the selected bracket without changing their other division bracket.",
                    ):
                        try:
                            _, placed_gid = restore_scratched_wrestler(
                                tournament, scratch_index=s_idx, target_group_id=nm_target
                            )
                            st.success(f"Placed {sc_rec['name']} into {placed_gid}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

    st.markdown("---")

    # 2. Refresh & Rethink Brackets (Scope or Targeted by IDs)
    st.subheader("🔄 Refresh & Rethink Brackets (Madison DP Engine)")
    st.caption(
        "After scratches and walk-ins leave 2-man or 5-man pods, re-run the Madison grouping engine to re-balance weights, "
        "group sizes, and teammate separations. Scratched wrestlers stay excluded and walk-ins stay included."
    )

    rethink_mode = st.radio(
        "How would you like to rethink the brackets?",
        options=[
            "By Division / Age Group (or Whole Tournament)",
            "Targeted Selection by Specific Bracket ID(s)",
        ],
        horizontal=True,
        key="rethink_mode",
        help="Choose 'By Division / Age Group' to re-balance an entire age division, or 'Targeted Selection' to re-group only specific Bracket IDs.",
    )

    if rethink_mode == "By Division / Age Group (or Whole Tournament)":
        with st.container(border=True):
            st.markdown("##### 🌐 Re-Optimize Active Wrestler Pools")
            st.caption(
                "Pool all active (non-scratched + walk-in) wrestlers in the selected scope and re-partition into optimal brackets. "
                "Any locked brackets (🔒) will remain untouched unless you uncheck 'Preserve Locked / Hand-Tweaked Brackets'."
            )
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                div_choices = ["ALL (Both Coed & Girls)"] + list(cfg.divisions)
                sel_re_div = st.selectbox(
                    "Division Scope",
                    div_choices,
                    key="re_div",
                    help="Limit re-optimization to Coed, Girls, or run across both divisions.",
                )
                re_div_val = None if sel_re_div.startswith("ALL") else sel_re_div
            with sc2:
                age_choices = ["ALL Age Groups"] + list(cfg.age_groups)
                sel_re_age = st.selectbox(
                    "Age Group Scope",
                    age_choices,
                    key="re_age",
                    help="Limit re-optimization to a single age group (e.g. 8U) or all age groups.",
                )
                re_age_val = None if sel_re_age.startswith("ALL") else sel_re_age
            with sc3:
                preserve_lk = st.checkbox(
                    "Preserve Locked / Hand-Tweaked Brackets",
                    value=True,
                    help="Keep brackets you have manually locked (🔒) or hand-edited intact while re-optimizing the remaining unlocked brackets.",
                    key="re_pres_lk",
                )

            ro1, ro2, ro3, ro4 = st.columns([1, 1, 1, 1.5])
            with ro1:
                re_target_sz = st.number_input(
                    "Target Size",
                    min_value=2,
                    max_value=8,
                    value=int(cfg.default_rule.target_group_size),
                    key="re_tsz",
                    help="Ideal number of wrestlers per bracket (typically 4).",
                )
            with ro2:
                re_max_sz = st.number_input(
                    "Max Size",
                    min_value=2,
                    max_value=8,
                    value=int(cfg.default_rule.max_group_size),
                    key="re_msz",
                    help="Maximum wrestlers allowed in a single bracket.",
                )
            with ro3:
                re_spread = st.number_input(
                    "Base Max Spread %",
                    min_value=3.0,
                    max_value=30.0,
                    value=float(cfg.default_rule.max_weight_spread_pct),
                    step=0.5,
                    key="re_sp",
                    help="Maximum weight spread percentage before soft-overflow penalties apply.",
                )
            with ro4:
                re_blend_skills = st.checkbox(
                    "Blend Beginner & Advanced to Avoid 2-Man Pods (Weight > Age > Skill > Team)",
                    value=bool(getattr(cfg, "blend_skills_to_fill_brackets", True)),
                    key="re_blend_sk",
                    help="Keep pure Beginner/Advanced pods when density allows, and blend Beginner + Advanced of the same age/weight to fill 3–4 man brackets instead of leaving 2-man pods.",
                )

            if st.button(
                "⚡ Rethink & Re-Optimize Brackets",
                type="primary",
                key="btn_reoptimize_scope",
                help="Re-run the Madison DP partitioner on the selected scope.",
            ):
                try:
                    _, orig_c, new_c = reoptimize_active_brackets(
                        tournament,
                        division=re_div_val,
                        age_group=re_age_val,
                        preserve_locked=preserve_lk,
                        target_group_size=int(re_target_sz),
                        max_group_size=int(re_max_sz),
                        max_weight_spread_pct=float(re_spread),
                        blend_skills=re_blend_skills,
                    )
                    st.success(
                        f"Successfully re-optimized! Replaced {orig_c} bracket(s) with {new_c} newly balanced bracket(s)."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    else:
        with st.container(border=True):
            st.markdown("##### 🎯 Targeted Regeneration by Bracket ID(s)")
            st.caption(
                "Select one or more Bracket IDs (or paste comma-separated IDs) to re-run the Madison grouping algorithm "
                "on just those specific brackets without touching the rest of the tournament."
            )

            rc1, rc2 = st.columns([2, 1])
            with rc1:
                selected_regen_ids = st.multiselect(
                    "Select Bracket ID(s) to Regenerate",
                    options=all_gids,
                    format_func=lambda gid: _group_summary_label(gid_map[gid]),
                    help="Pick 1 or more brackets (e.g. two adjacent 2-man or 3-man brackets) to pool and re-divide.",
                )
            with rc2:
                typed_regen_ids = st.text_input(
                    "Or Paste Comma-Separated Bracket IDs",
                    placeholder="e.g. COED-8U-BEG-01, COED-8U-BEG-02",
                    help="Quickly paste Bracket IDs copied from the Explorer or Lookup tab.",
                )

            ro1, ro2, ro3, ro4 = st.columns(4)
            with ro1:
                regen_target_sz = st.number_input(
                    "Target Size Override",
                    min_value=2,
                    max_value=8,
                    value=4,
                    key="rg_tsz",
                    help="Target pod size for the regenerated brackets.",
                )
            with ro2:
                regen_max_sz = st.number_input(
                    "Max Size Override",
                    min_value=2,
                    max_value=8,
                    value=4,
                    key="rg_msz",
                    help="Maximum pod size for the regenerated brackets.",
                )
            with ro3:
                regen_spread = st.number_input(
                    "Base Max Spread % Override",
                    min_value=3.0,
                    max_value=30.0,
                    value=10.0,
                    step=0.5,
                    key="rg_sp",
                    help="Target max weight spread % for the regenerated brackets.",
                )
            with ro4:
                combine_pool = st.checkbox(
                    "Pool selected brackets together (even if different skill/age)",
                    value=False,
                    help="Check this to combine e.g. a solo Advanced bracket and a Beginner bracket into one shared pool and regroup them.",
                )

            if st.button(
                "⚡ Regenerate Selected Bracket(s)",
                type="primary",
                help="Pool the wrestlers in the selected Bracket IDs and re-partition them.",
            ):
                combined_ids = list(selected_regen_ids)
                if typed_regen_ids.strip():
                    for part in typed_regen_ids.split(","):
                        if part.strip():
                            combined_ids.append(part.strip().upper())
                if not combined_ids:
                    st.error("Please select or enter at least one Bracket ID.")
                else:
                    try:
                        regenerate_brackets_by_ids(
                            tournament,
                            group_ids=combined_ids,
                            target_group_size=int(regen_target_sz),
                            max_group_size=int(regen_max_sz),
                            max_weight_spread_pct=float(regen_spread),
                            combine_across_skills_or_ages=bool(combine_pool),
                        )
                        st.success(f"Regenerated bracket(s): {', '.join(combined_ids)}")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    st.markdown("---")

    # 3. Mat / Table Assignment & Load Balancer
    st.subheader("🏟️ Mat / Table Assignment & Load Balancer")
    st.caption(
        "Balance brackets across `Mat 1 .. Mat N` or move specific brackets/age groups between mats. "
        "**Once mats are assigned, adding walk-ins, scratching no-shows, or re-optimizing brackets keeps existing mats fixed.**"
    )

    mat_col_auto, mat_col_manual = st.columns([1.3, 1.2])
    cur_mat_count = max(1, int(getattr(cfg, "mat_count", 4) or 4))

    with mat_col_auto:
        with st.container(border=True):
            st.markdown("#### ⚖️ Rebalance & Auto-Assign Mats")
            st.caption(
                "Evenly distribute brackets and bouts across `Mat 1 .. Mat N` (or within a specific Division / Age Group)."
            )
            mc1, mc2 = st.columns([1, 1.8])
            with mc1:
                new_mat_count = st.number_input(
                    "Tournament Mat Count",
                    min_value=1,
                    max_value=24,
                    value=cur_mat_count,
                    key="tweak_mat_count",
                    help="Total number of mats/tables available in your gym.",
                )
            with mc2:
                mat_strategy = st.selectbox(
                    "Distribution Strategy",
                    options=[
                        "coed_by_age_girls_together",
                        "equal_age_group",
                        "balanced",
                        "contiguous_blocks",
                        "round_robin",
                    ],
                    format_func=lambda s: {
                        "coed_by_age_girls_together": "👧👦 Coed by Age Group + All Girls Together Across Mats (Girls Wrestle Simultaneously)",
                        "equal_age_group": "🎯 Equal Brackets by Age Group Across Mats (Spread Every Division/Age Evenly)",
                        "balanced": "⚖️ Equal Bouts by Age Group Across Mats (Balance Total Bouts Per Mat)",
                        "contiguous_blocks": "🧱 Contiguous Age/Weight Blocks Per Mat (Mat 1=Youngest .. Mat N=Oldest)",
                        "round_robin": "🔄 Round-Robin Alternating (Cycle Brackets 1..N Across Mats)",
                    }[s],
                    key="tweak_mat_strategy",
                    help=(
                        "'Coed by Age Group + All Girls Together' pools all Girls brackets as one group across mats (since Girls wrestle at once) while spreading each Coed age group evenly across mats. "
                        "'Equal Brackets by Age Group' sends an equal number of brackets of EACH (division, age group) to every mat."
                    ),
                )

            ms1, ms2, ms3, ms4 = st.columns(4)
            with ms1:
                mat_div_opts = ["ALL Divisions"] + list(cfg.divisions)
                sel_mat_div = st.selectbox("Division Scope", mat_div_opts, key="tweak_mat_div")
                mat_div_val = None if sel_mat_div.startswith("ALL") else sel_mat_div
            with ms2:
                mat_age_opts = ["ALL Age Groups"] + list(cfg.age_groups)
                sel_mat_age = st.selectbox("Age Group Scope", mat_age_opts, key="tweak_mat_age")
                mat_age_val = None if sel_mat_age.startswith("ALL") else sel_mat_age
            with ms3:
                mat_pres_lk = st.checkbox(
                    "Skip Locked (🔒)",
                    value=False,
                    key="tweak_mat_pres_lk",
                    help="Leave UNCHECKED to rebalance ALL brackets in the selected scope across all mats (even if brackets were locked from merges/tweaks). Check only if you want locked brackets to stay on their current mat.",
                )
            with ms4:
                mat_lock_after = st.checkbox(
                    "Lock After Assigning",
                    value=True,
                    key="tweak_mat_lock_after",
                    help="Automatically mark assigned brackets as 🔒 Locked after rebalancing so their Mat # stays frozen.",
                )

            if st.button(
                f"⚖️ Rebalance / Auto-Assign Brackets Across {int(new_mat_count)} Mat(s)",
                type="primary",
                key="btn_auto_assign_mats",
                use_container_width=True,
            ):
                try:
                    assign_brackets_to_mats(
                        tournament,
                        mat_count=int(new_mat_count),
                        strategy=mat_strategy,
                        division=mat_div_val,
                        age_group=mat_age_val,
                        preserve_locked=bool(mat_pres_lk),
                        lock_assigned=bool(mat_lock_after),
                    )
                    st.success(f"Rebalanced brackets across {int(new_mat_count)} mat(s) using '{mat_strategy}'!")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with mat_col_manual:
        with st.container(border=True):
            st.markdown("#### 🎯 Move Brackets Across Mats")
            st.caption(
                "Filter by current **Mat #** or **Age Group** to move specific brackets (or an entire age/division group) to another mat."
            )
            max_mat_opt = max(int(new_mat_count), cur_mat_count, max((g.mat_number or 1 for g in groups), default=1))
            src_mat_filter_opts = ["All Mats"] + [f"Mat {m}" for m in range(1, max_mat_opt + 1)]
            if any(g.mat_number is None for g in groups):
                src_mat_filter_opts.append("Unassigned")

            mf1, mf2 = st.columns(2)
            with mf1:
                src_mat_filter = st.selectbox(
                    "Filter Source Mat #",
                    options=src_mat_filter_opts,
                    key="manual_src_mat_filter",
                    help="Filter the bracket list below to only brackets currently on a specific mat (e.g. Mat 1).",
                )
            with mf2:
                src_age_filter = st.selectbox(
                    "Filter Source Age Group",
                    options=["All Ages"] + list(dict.fromkeys(g.age_group for g in groups)),
                    key="manual_src_age_filter",
                    help="Filter the bracket list below to a specific age group.",
                )

            filtered_manual_gids = [
                g.group_id
                for g in groups
                if (
                    src_mat_filter == "All Mats"
                    or (src_mat_filter == "Unassigned" and g.mat_number is None)
                    or (src_mat_filter.startswith("Mat ") and g.mat_number == int(src_mat_filter.split()[1]))
                )
                and (src_age_filter == "All Ages" or g.age_group == src_age_filter)
            ]

            manual_mat_gids = st.multiselect(
                f"Select Bracket(s) to Move ({len(filtered_manual_gids)} matching filter)",
                options=filtered_manual_gids,
                format_func=lambda gid: _group_summary_label(gid_map[gid]),
                key="manual_mat_gids",
                help="Select one or more brackets to move to the chosen Target Mat #.",
            )
            manual_mat_choices = list(range(1, max_mat_opt + 1)) + [None]
            target_mat_num = st.selectbox(
                "Target Mat #",
                options=manual_mat_choices,
                format_func=lambda m: f"🏟️ Mat {m}" if m is not None else "Unassigned (Clear Mat #)",
                key="manual_target_mat",
            )
            mv_b1, mv_b2 = st.columns(2)
            with mv_b1:
                if st.button(
                    "📌 Move Selected Bracket(s)",
                    type="primary",
                    key="btn_manual_set_mat",
                    use_container_width=True,
                ):
                    if not manual_mat_gids:
                        st.error("Please select at least one bracket to move.")
                    else:
                        try:
                            set_bracket_mat(
                                tournament,
                                group_ids=manual_mat_gids,
                                mat_number=target_mat_num,
                                lock_bracket=True,
                            )
                            lbl = f"Mat {target_mat_num}" if target_mat_num is not None else "Unassigned"
                            st.success(f"Moved {len(manual_mat_gids)} bracket(s) to {lbl} and locked!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
            with mv_b2:
                if st.button(
                    f"📦 Move All {len(filtered_manual_gids)} Matching Filter",
                    type="secondary",
                    key="btn_manual_move_filtered",
                    use_container_width=True,
                    disabled=(len(filtered_manual_gids) == 0),
                    help="Move every bracket matching your 'Filter Source Mat #' and 'Filter Source Age Group' above to the Target Mat #.",
                ):
                    try:
                        set_bracket_mat(
                            tournament,
                            group_ids=filtered_manual_gids,
                            mat_number=target_mat_num,
                            lock_bracket=True,
                        )
                        lbl = f"Mat {target_mat_num}" if target_mat_num is not None else "Unassigned"
                        st.success(f"Moved all {len(filtered_manual_gids)} matching bracket(s) to {lbl}!")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            lk_c1, lk_c2 = st.columns(2)
            locked_total = sum(1 for g in groups if g.locked)
            with lk_c1:
                if st.button(
                    f"🔒 Lock All {len(groups)} Brackets & Mats",
                    key="btn_lock_all_mats",
                    use_container_width=True,
                    help="Freeze all current brackets and mat assignments. Walk-ins and scratches will update pods in-place on their existing mats without reshuffling.",
                ):
                    toggle_bracket_lock(tournament, all_gids, locked=True)
                    st.success(f"Locked all {len(groups)} brackets and their mat assignments!")
                    st.rerun()
            with lk_c2:
                if st.button(
                    f"🔓 Unlock All ({locked_total} Locked)",
                    key="btn_unlock_all_mats",
                    use_container_width=True,
                    disabled=(locked_total == 0),
                    help="Unlock all brackets so you can run a full tournament re-optimization or mat rebalance.",
                ):
                    toggle_bracket_lock(tournament, all_gids, locked=False)
                    st.success("Unlocked all brackets!")
                    st.rerun()

    with st.expander("📊 Live Mat / Scoring Table Load & Bout Distribution", expanded=True):
        mat_buckets: dict[int | None, list[BracketGroup]] = {m: [] for m in range(1, max(cur_mat_count, int(new_mat_count)) + 1)}
        for g in groups:
            mat_buckets.setdefault(g.mat_number, []).append(g)

        mat_load_rows = []
        for m_num in sorted(
            mat_buckets.keys(),
            key=lambda x: (0, x) if x is not None else (1, 999),
        ):
            m_grps = mat_buckets[m_num]
            if m_num is None and not m_grps:
                continue
            coed_age_counts: dict[str, int] = {}
            girls_ages: list[str] = []
            for g in m_grps:
                if g.division.strip().lower().startswith("girl"):
                    girls_ages.append(g.age_group)
                else:
                    lbl_age = f"{g.division} {g.age_group}"
                    coed_age_counts[lbl_age] = coed_age_counts.get(lbl_age, 0) + 1
            coed_summary = ", ".join(f"{k} ({v})" for k, v in coed_age_counts.items())
            girls_summary = f"{len(girls_ages)} ({', '.join(girls_ages)})" if girls_ages else "0"
            locked_on_mat = sum(1 for g in m_grps if g.locked)
            mat_load_rows.append(
                {
                    "Mat / Table": f"🏟️ Mat {m_num}" if m_num is not None else "⚠️ Unassigned",
                    "Brackets": f"{len(m_grps)} ({locked_on_mat} 🔒)",
                    "Wrestlers": sum(g.size for g in m_grps),
                    "Scheduled Bouts": sum(len(g.bouts) for g in m_grps),
                    "Coed by Age Group": coed_summary if coed_summary else "—",
                    "Girls Brackets": girls_summary,
                    "Assigned Bracket IDs": ", ".join(g.group_id for g in m_grps) if m_grps else "—",
                }
            )
        st.dataframe(mat_load_rows, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 4. Manual Wrestler Move & Bracket Merge / Swap
    st.subheader("🔧 Surgical Manual Adjustments (Auto-Locks Affected Brackets)")
    st.caption(
        "Use these controls for fine-grained director overrides. Any bracket modified here is automatically marked **🔒 Locked** "
        "so its bouts and roster stay fixed."
    )
    t_col1, t_col2 = st.columns(2)

    with t_col1:
        st.markdown("#### ➡️ Move Wrestler to Another Bracket")
        st.caption("Transfer one wrestler from their current bracket into another existing bracket or spin off a new pod.")
        src_gid = st.selectbox(
            "From Bracket",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="mv_src_gid",
            help="Select the bracket the wrestler is currently in.",
        )
        src_grp = gid_map[src_gid]
        w_options = {w.id: f"{w.name} ({w.weight:g} lbs, {w.display_team})" for w in src_grp.wrestlers}
        sel_wid = st.selectbox(
            "Select Wrestler to Move",
            options=list(w_options.keys()),
            format_func=lambda wid: w_options[wid],
            key="mv_wid",
            help="Choose which wrestler in the source bracket to move.",
        )

        dest_choices = ["__NEW__"] + [gid for gid in all_gids if gid != src_gid]
        dest_gid = st.selectbox(
            "To Destination Bracket",
            options=dest_choices,
            format_func=lambda gid: (
                f"➕ Create New Bracket in {src_grp.division} {src_grp.age_group} {src_grp.skill_level}"
                if gid == "__NEW__"
                else _group_summary_label(gid_map[gid])
            ),
            key="mv_dst_gid",
            help="Pick the destination bracket or choose 'Create New Bracket' to spin off a new pod.",
        )
        renum_after_move = st.checkbox(
            "Renumber bracket IDs after move",
            value=False,
            key="mv_renum",
            help="Keep unchecked once sheets are printed so existing Bracket IDs don't shift.",
        )
        if st.button("Move Wrestler", key="btn_move_wrestler", help="Move wrestler and recalculate bouts for both brackets."):
            try:
                move_wrestler(
                    tournament,
                    wrestler_id=sel_wid,
                    from_group_id=src_gid,
                    to_group_id=dest_gid,
                    renumber_ids=renum_after_move,
                )
                st.success("Moved wrestler and updated bouts!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with t_col2:
        st.markdown("#### 🔀 Swap Two Wrestlers Between Brackets")
        st.caption("Trade two wrestlers one-for-one between two brackets (great for resolving same-club teammate collisions).")
        swap_ga = st.selectbox(
            "Bracket A",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="sw_ga",
            help="First bracket in the swap.",
        )
        wa_map = {w.id: f"{w.name} ({w.weight:g} lbs, {w.team})" for w in gid_map[swap_ga].wrestlers}
        swap_wa = st.selectbox(
            "Wrestler A",
            options=list(wa_map.keys()),
            format_func=lambda k: wa_map[k],
            key="sw_wa",
            help="Wrestler from Bracket A who will move to Bracket B.",
        )

        other_gids = [gid for gid in all_gids if gid != swap_ga] or all_gids
        swap_gb = st.selectbox(
            "Bracket B",
            options=other_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="sw_gb",
            help="Second bracket in the swap.",
        )
        wb_map = {w.id: f"{w.name} ({w.weight:g} lbs, {w.team})" for w in gid_map[swap_gb].wrestlers}
        swap_wb = st.selectbox(
            "Wrestler B",
            options=list(wb_map.keys()),
            format_func=lambda k: wb_map[k],
            key="sw_wb",
            help="Wrestler from Bracket B who will move to Bracket A.",
        )

        if st.button("Swap Wrestlers", key="btn_swap_wrestlers", help="Exchange Wrestler A and Wrestler B and recalculate bouts."):
            try:
                swap_wrestlers(tournament, swap_ga, swap_wa, swap_gb, swap_wb)
                st.success("Swapped wrestlers and recalculated bouts!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("---")
    b_col1, b_col2 = st.columns(2)

    with b_col1:
        st.markdown("#### 🔗 Merge Brackets (2 or More)")
        st.caption("Select 1, 2, or more source brackets to fold into a single target bracket and rebuild its round-robin schedule.")
        m_srcs = st.multiselect(
            "Source Bracket(s) to Fold into Target",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="mg_srcs",
            help="Pick 1 source bracket (to merge 2 brackets), 2 source brackets (to merge 3 brackets), or more. Selected source brackets will be folded into the Target bracket.",
        )
        m_targets = [gid for gid in all_gids if gid not in set(m_srcs)] or all_gids
        m_dst = st.selectbox(
            "Into Target Bracket",
            options=m_targets,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="mg_dst",
            help="Destination bracket that will receive all wrestlers from the selected Source bracket(s).",
        )
        if m_srcs:
            combined_wrestlers = sum(gid_map[sid].size for sid in m_srcs if sid in gid_map) + (
                gid_map[m_dst].size if m_dst in gid_map and m_dst not in set(m_srcs) else 0
            )
            st.caption(
                f"📊 Merging **{len(m_srcs) + 1} brackets** -> **{combined_wrestlers} total wrestlers** in `{m_dst}`."
            )
        if st.button(
            "🔗 Merge Selected Brackets",
            key="btn_merge_brackets",
            disabled=not bool(m_srcs) or m_dst in set(m_srcs),
            help="Combine all selected Source bracket(s) into the Target bracket.",
        ):
            try:
                merge_multiple_brackets(tournament, m_srcs, m_dst)
                st.success(f"Merged {', '.join(m_srcs)} into {m_dst}!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with b_col2:
        st.markdown("#### ✏️ Edit Wrestler Weight / Info")
        st.caption("Fix a typo in a wrestler's name, club, or scale weight in-place and re-evaluate bracket weight spreads.")
        ed_gid = st.selectbox(
            "Select Bracket",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="ed_gid",
            help="Select the bracket containing the wrestler you want to edit.",
        )
        ed_grp = gid_map[ed_gid]
        ed_wmap = {w.id: w for w in ed_grp.wrestlers}
        ed_wid = st.selectbox(
            "Select Wrestler",
            options=list(ed_wmap.keys()),
            format_func=lambda wid: f"{ed_wmap[wid].name} ({ed_wmap[wid].weight:g} lbs, {ed_wmap[wid].team})",
            key="ed_wid",
            help="Choose the wrestler to update.",
        )
        curr_w = ed_wmap[ed_wid]
        ew1, ew2, ew3 = st.columns(3)
        new_wt = ew1.number_input("Scale Weight (lbs)", value=float(curr_w.weight), step=0.1, key="ed_wt")
        new_name = ew2.text_input("Name", value=curr_w.name, key="ed_name")
        new_team = ew3.text_input("Team / Club", value=curr_w.team, key="ed_team")
        if st.button("Save Wrestler Update", key="btn_edit_wrestler", help="Save updated wrestler details and refresh bracket stats."):
            try:
                update_wrestler_in_bracket(
                    tournament,
                    group_id=ed_gid,
                    wrestler_id=ed_wid,
                    name=new_name,
                    weight=new_wt,
                    team=new_team,
                )
                st.success(f"Updated {new_name}!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_print_and_export_tab(tournament: SavedTournament) -> None:
    groups = tournament.result.groups

    st.subheader("🖨️ Print & Export Tournament Brackets")
    st.caption(
        "Generate official 1-page-per-bracket mat-side score sheets (with or without the top bracket drawing), "
        "filter by **Mat #** to print table-by-table packets, download blank walk-in templates, or export Excel/CSV files."
    )

    with st.expander("🖨️ Printing Guide & Mat-Side Score Sheet Layout Details", expanded=False):
        st.markdown(
            """
            - **Guaranteed 1 Page Per Bracket (US Letter Portrait)**: Every bracket sheet is styled with CSS `@page { size: letter portrait; margin: 0.25in; }` and `page-break-after: always` so each weight class prints cleanly on its own single sheet of paper.
            - **Pre-Printed Mat / Table Badges**: Each sheet automatically displays its assigned **`MAT 1` .. `MAT N`** badge in the top-right header (or a blank write-in line if unassigned). Use **Filter Mat #** below (or the **Mat** dropdown inside the preview toolbar) to print packet-by-packet for each scoring table.
            - **Printable Master Wrestler & Mat Directory Handout (`roster_directory.html`)**:
              - **6 Instant Handout Views in 1 File**: Switch between **Alphabetical (A–Z All Wrestlers)** for wall posting, **Check-In by Age Group & Club** (`Age -> Club A–Z -> Wrestler A–Z`) for age-group check-in tables, **Sorted by Bracket ID**, **Grouped by Mat # (`Mat 1 .. Mat N`)** for each mat table & runner, **Grouped by School / Club** for coach handouts, or **Grouped by Division & Age Group** for staging/announcing.
              - **Everything Needed on One Line**: Check-in box (`☐`), Wrestler Name, School/Club, Scale Weight, Division/Age/Skill, bold **`MAT #`** badge, **`Bracket ID`** & weight range, Seed/Format/Bout count, and **Pod Opponents**.
              - **1 Age / Mat / Club Per Page Option**: Check `1 Age/Mat/Club Per Page` in the roster preview toolbar to print separate sheets for each age check-in table, scoring mat, or club coach.
            - **Two Printable Bracket Layout Modes**:
              - **Full Bracket + Bout Sheet**: Includes the top symmetric bracket progression diagram (`3rd Place` left, `1st Place` right, or `Best 2 out of 3 Series`), Official Placement & Awards, W/L Tally Table, `38px`-tall Period Scoreboxes, and the 3-column Scoring & Criteria Reference Box.
              - **Bout Sheet Only (No Bracket Drawing — Larger Fonts & Taller Boxes)**: Removes the redundant top bracket drawing and redistributes that vertical space into **larger typography (`10.5px–16px`)**, taller W/L tally rows (`20px`), and **taller (`42px`) period scoreboxes** so mat-side scorers have maximum room to write match points while staying strictly within 1 printed page.
            """
        )

    hdr_c1, hdr_c2, hdr_c3, hdr_c4 = st.columns([1.5, 0.9, 1.4, 0.7])
    with hdr_c1:
        custom_pr_name = st.text_input(
            "Tournament Name on Print Header",
            value=tournament.name,
            key="pr_custom_name",
            help="Appears at the top-left of every printed bracket score sheet and master roster handout.",
        )
    with hdr_c2:
        default_pr_date = datetime.now().strftime("%B %d, %Y")
        custom_pr_date = st.text_input(
            "Tournament Date on Print Header",
            value=default_pr_date,
            key="pr_custom_date",
            help="Appears under the tournament title on every printed page.",
        )
    with hdr_c3:
        sheet_layout_mode = st.selectbox(
            "Printable Sheet Layout",
            options=[
                "Bout Sheet Only (No Bracket Drawing — Larger Fonts & Scoreboxes)",
                "Full Bracket + Bout Sheet (With Top Bracket Drawing)",
                "Master Wrestler & Mat Handout Roster (A–Z / By Mat / By Club)",
            ],
            index=0,
            key="pr_sheet_layout_mode",
            help="Defaults to Bout Sheet Only (larger fonts/boxes). Switch to Full Bracket + Bout Sheet or Master Wrestler & Mat Directory Handout anytime.",
        )
    with hdr_c4:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button(
            "🔄 Refresh",
            key="btn_refresh_printouts",
            use_container_width=True,
            help="Regenerate and refresh both the Bracket/Bout Sheets and Master Wrestler Handout from the latest bracket data.",
        ):
            st.toast("Refreshed printouts from latest bracket data!", icon="🔄")
            st.rerun()

    include_diagram = not sheet_layout_mode.startswith("Bout Sheet Only")

    export_dir = DEFAULT_STORE_DIR / tournament.slug / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    blank_html_path = export_blank_bracket_html(
        export_dir / "blank_brackets.html",
        tournament_name=custom_pr_name.strip() or tournament.name,
        tournament_date=custom_pr_date.strip(),
        include_bracket_diagram=include_diagram,
    )
    blank_bout_only_path = export_blank_bracket_html(
        export_dir / "blank_bout_sheets.html",
        tournament_name=custom_pr_name.strip() or tournament.name,
        tournament_date=custom_pr_date.strip(),
        include_bracket_diagram=False,
    )

    with st.expander("📝 Print / Download Blank Walk-In Bracket & Bout Sheet (Hand-Write Ready)", expanded=not bool(groups)):
        st.caption(
            "Need to hand-write a last-minute bracket or exhibition pod at the mat table? "
            "Download or print a 1-page blank sheet (includes 4-Man Round-Robin, 3-Man Round-Robin, and 2-Man Best 2-of-3 templates with seed matchup hints, in both Full and Bout-Sheet-Only layouts)."
        )
        bl_c1, bl_c2, bl_c3 = st.columns([1.3, 1.3, 1.8])
        with bl_c1:
            st.download_button(
                "📝 Blank Bracket + Bout Sheet (.html)",
                data=blank_html_path.read_bytes(),
                file_name=f"{tournament.slug}_blank_bracket_sheet.html",
                mime="text/html",
                type="secondary",
                use_container_width=True,
                help="Blank write-in sheet with top bracket drawing + bout table.",
            )
        with bl_c2:
            st.download_button(
                "📋 Blank Bout Sheet Only — No Bracket (.html)",
                data=blank_bout_only_path.read_bytes(),
                file_name=f"{tournament.slug}_blank_bout_sheet_only.html",
                mime="text/html",
                type="secondary",
                use_container_width=True,
                help="Blank write-in bout sheet without the top bracket drawing — larger fonts and taller period boxes.",
            )
        with bl_c3:
            show_blank_preview = st.checkbox(
                "Show Live Blank Sheet Preview (with Print Button)",
                value=not bool(groups),
                key="pr_show_blank_preview",
                help="Open an interactive preview of the blank sheet where you can switch Template Size (4-Man, 3-Man, 2-Man) and Sheet Layout (Full vs Bout Sheet Only).",
            )
        if show_blank_preview:
            components.html(blank_html_path.read_text(encoding="utf-8"), height=850, scrolling=True)

    if not groups:
        st.info("No populated brackets yet. Go to **📥 Sheet Import & Sync** to import a roster, or use the Blank Bracket Sheet above.")
        return

    mat_count = max(1, int(getattr(tournament.config, "mat_count", 4) or 4))
    mat_nums_present = sorted({g.mat_number for g in groups if g.mat_number is not None} | set(range(1, mat_count + 1)))
    pr_mat_opts = ["All"] + [f"Mat {m}" for m in mat_nums_present]
    if any(g.mat_number is None for g in groups):
        pr_mat_opts.append("Unassigned")

    p1, p2, p3, p4, p5, p6 = st.columns([0.9, 0.9, 0.9, 0.9, 1.0, 1.4])
    divs = ["All"] + list(dict.fromkeys(g.division for g in groups))
    ages = ["All"] + list(dict.fromkeys(g.age_group for g in groups))
    skills = ["All"] + list(dict.fromkeys(g.skill_level for g in groups))
    sizes_present = sorted({g.size for g in groups})
    pr_size_opts = ["All"] + [f"{s}-Man" if s > 1 else "1-Man (Solo)" for s in sizes_present]
    if any(s in sizes_present for s in (1, 2)):
        pr_size_opts.append("≤2-Man")
    if any(s in sizes_present for s in (1, 2, 3)):
        pr_size_opts.append("≤3-Man")

    with p1:
        p_div = st.selectbox("Filter Division", divs, key="pr_div", help="Print/export only Coed or Girls brackets.")
    with p2:
        p_age = st.selectbox("Filter Age Group", ages, key="pr_age", help="Print/export only a specific age division (e.g. print 6U & 8U morning session first).")
    with p3:
        p_skill = st.selectbox("Filter Skill Level", skills, key="pr_skill", help="Filter by Beginner, Intermediate, or Advanced.")
    with p4:
        p_mat = st.selectbox("Filter Mat #", pr_mat_opts, key="pr_mat", help="Print/export only brackets assigned to a specific mat/table (e.g. Mat 1 packet).")
    with p5:
        p_size = st.selectbox("Filter Bracket Size", pr_size_opts, key="pr_size", help="Quickly review or print only specific pod sizes (e.g. 2-Man Best 2-of-3, 3-Man, 4-Man, or ≤2-Man pods).")
    with p6:
        p_specific_ids = st.multiselect(
            "Or Specific Bracket ID(s)",
            options=[g.group_id for g in groups],
            key="pr_ids",
            help="Need to re-print just 1 or 2 brackets after a mat-side walk-in or scratch? Select their Bracket IDs here!",
        )

    export_groups: list[BracketGroup] = []
    id_filter = set(p_specific_ids)
    for g in groups:
        if id_filter and g.group_id not in id_filter:
            continue
        if not id_filter:
            if p_div != "All" and g.division != p_div:
                continue
            if p_age != "All" and g.age_group != p_age:
                continue
            if p_skill != "All" and g.skill_level != p_skill:
                continue
            if p_mat != "All":
                if p_mat == "Unassigned" and g.mat_number is not None:
                    continue
                elif p_mat.startswith("Mat ") and g.mat_number != int(p_mat.split()[1]):
                    continue
            if p_size != "All":
                if p_size == "≤2-Man" and g.size > 2:
                    continue
                elif p_size == "≤3-Man" and g.size > 3:
                    continue
                elif p_size == "1-Man (Solo)" and g.size != 1:
                    continue
                elif p_size.endswith("-Man") and not p_size.startswith("≤") and g.size != int(p_size.split("-")[0]):
                    continue
        export_groups.append(g)

    def _clean_fn_token(val: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", (val or "").strip().lower()).strip("_")

    fn_base = _clean_fn_token(custom_pr_name.strip() or tournament.slug) or _clean_fn_token(tournament.slug) or "tournament"
    fn_suffix_parts: list[str] = []
    if id_filter:
        if len(p_specific_ids) <= 2:
            fn_suffix_parts.extend(_clean_fn_token(gid) for gid in p_specific_ids)
        else:
            fn_suffix_parts.append(f"{len(p_specific_ids)}_selected_brackets")
    else:
        if p_mat != "All":
            fn_suffix_parts.append(_clean_fn_token(p_mat))
        if p_div != "All":
            fn_suffix_parts.append(_clean_fn_token(p_div))
        if p_age != "All":
            fn_suffix_parts.append(_clean_fn_token(p_age))
        if p_skill != "All":
            fn_suffix_parts.append(_clean_fn_token(p_skill))
        if p_size != "All":
            sz_tok = p_size.replace("≤", "le_").replace("(Solo)", "solo")
            fn_suffix_parts.append(_clean_fn_token(sz_tok))
    fn_suffix = ("_" + "_".join(p for p in fn_suffix_parts if p)) if fn_suffix_parts else ""

    filtered_result = TournamentResult(
        source=tournament.result.source,
        wrestlers=[w for g in export_groups for w in g.wrestlers],
        groups=export_groups,
        skipped_rows=tournament.result.skipped_rows,
    )

    html_path = export_printable_html(
        filtered_result,
        export_dir / "brackets.html",
        tournament_name=custom_pr_name.strip() or tournament.name,
        tournament_date=custom_pr_date.strip(),
        include_bracket_diagram=include_diagram,
    )
    bout_only_html_path = export_printable_html(
        filtered_result,
        export_dir / "bout_sheets_only.html",
        tournament_name=custom_pr_name.strip() or tournament.name,
        tournament_date=custom_pr_date.strip(),
        include_bracket_diagram=False,
    )
    roster_html_path = export_printable_roster_html(
        filtered_result,
        export_dir / "roster_directory.html",
        tournament_name=custom_pr_name.strip() or tournament.name,
        tournament_date=custom_pr_date.strip(),
        scratched_wrestlers=tournament.scratched_wrestlers,
    )
    xlsx_path = export_xlsx_workbook(filtered_result, export_dir / "brackets_workbook.xlsx")
    csv_paths = export_csv_files(filtered_result, export_dir)

    d1, d2, d3, d4, d5, d6, d7 = st.columns([1.15, 1.15, 1.25, 0.9, 0.9, 0.8, 0.8])
    with d1:
        st.download_button(
            f"🖨️ Full Brackets ({len(export_groups)})",
            data=html_path.read_bytes(),
            file_name=f"{fn_base}_brackets{fn_suffix}.html",
            mime="text/html",
            type="primary" if sheet_layout_mode.startswith("Full Bracket") else "secondary",
            use_container_width=True,
            help="Self-contained printable HTML file with 1 page per bracket (includes top bracket drawing, or toggle layout in toolbar).",
        )
    with d2:
        st.download_button(
            f"📋 Bout Sheets Only ({len(export_groups)})",
            data=bout_only_html_path.read_bytes(),
            file_name=f"{fn_base}_bout_sheets_only{fn_suffix}.html",
            mime="text/html",
            type="primary" if sheet_layout_mode.startswith("Bout Sheet Only") else "secondary",
            use_container_width=True,
            help="Printable HTML bout sheets WITHOUT the top bracket drawing — larger fonts, taller tally rows, and 42px period scoreboxes!",
        )
    with d3:
        st.download_button(
            f"📑 Wrestler & Mat Roster ({len(filtered_result.wrestlers)})",
            data=roster_html_path.read_bytes(),
            file_name=f"{fn_base}_wrestler_mat_roster{fn_suffix}.html",
            mime="text/html",
            type="primary" if sheet_layout_mode.startswith("Master Wrestler") else "secondary",
            use_container_width=True,
            help="Printable Master Wrestler & Mat Directory handout (switch between Alphabetical A-Z, Check-In by Age & Club, By Mat #, By Club/Coach, or By Division/Age before printing!).",
        )
    with d4:
        st.download_button(
            "📝 Blank Sheet",
            data=blank_html_path.read_bytes(),
            file_name=f"{fn_base}_blank_bracket_sheet.html",
            mime="text/html",
            use_container_width=True,
            help="Download a printable blank bracket & bout sheet for hand-writing walk-in pods.",
        )
    with d5:
        st.download_button(
            "📊 Excel (.xlsx)",
            data=xlsx_path.read_bytes(),
            file_name=f"{fn_base}_brackets{fn_suffix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            help="Excel workbook with Summary, Master_Roster (A-Z with Mat # & Bracket ID), Flags, and separate tabs per age/division.",
        )
    with d6:
        st.download_button(
            "📄 Rosters (.csv)",
            data=csv_paths["rosters_csv"].read_bytes(),
            file_name=f"{fn_base}_rosters{fn_suffix}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Flat CSV listing every wrestler, their assigned Bracket ID, Mat #, seed, weight, and club.",
        )
    with d7:
        st.download_button(
            "🥊 Bouts (.csv)",
            data=csv_paths["bouts_csv"].read_bytes(),
            file_name=f"{fn_base}_bouts{fn_suffix}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Flat CSV listing every scheduled bout across the selected brackets.",
        )

    if sheet_layout_mode.startswith("Master Wrestler"):
        st.markdown("#### 📑 Live Printable Master Wrestler & Mat Handout Preview")
        st.caption(
            "Use **Handout View** inside the dark toolbar below to switch between **Alphabetical (A–Z All Wrestlers)**, "
            "**Check-In by Age Group & Club (Age Check-In Tables)**, **Sorted by Bracket ID**, **Grouped by Mat # (Table Handouts)**, "
            "**Grouped by School / Club (Coach Handouts)**, or **Grouped by Division & Age**, "
            "check **1 Age/Mat/Club Per Page** if handing out separate sheets, and click **Print Roster Handout**."
        )
        components.html(roster_html_path.read_text(encoding="utf-8"), height=850, scrolling=True)
    else:
        prev_tab_sheets, prev_tab_roster = st.tabs(
            [
                f"🥊 Bracket & Bout Score Sheets ({len(export_groups)} Brackets)",
                f"📑 Master Wrestler & Mat Handout Roster ({len(filtered_result.wrestlers)} Wrestlers)",
            ]
        )
        with prev_tab_sheets:
            st.caption(
                "Use the **Layout** and **Mat** dropdowns inside the preview toolbar below (or the filters above) "
                "to switch between **Full Bracket + Bout Sheet** and **Bout Sheet Only**, then click **Print Visible Sheets**."
            )
            components.html(html_path.read_text(encoding="utf-8"), height=850, scrolling=True)
        with prev_tab_roster:
            st.caption(
                "Printable tournament handout for the check-in desk, mat runners, table workers, and club coaches. "
                "Switch **Handout View** in the toolbar between **Alphabetical (A–Z)**, **Check-In by Age Group & Club**, "
                "**Sorted by Bracket ID**, **Grouped by Mat #**, **Grouped by School / Club**, or **Grouped by Division & Age**, then click **Print Roster Handout**."
            )
            components.html(roster_html_path.read_text(encoding="utf-8"), height=850, scrolling=True)


def _render_wrestler_lookup_tab(tournament: SavedTournament) -> None:
    groups = tournament.result.groups
    if not groups and not tournament.scratched_wrestlers:
        st.info("No wrestlers loaded yet. Go to **📥 Sheet Import & Sync** to load a roster.")
        return

    st.subheader("🔍 Wrestler Lookup & Mat-Side Quick Actions")
    st.caption(
        "Fast check-in desk & mat-side directory: search any active or scratched wrestler by name, school/club, weight, "
        "mat number, or bracket ID. Inspect their assigned **Mat #**, pod, bout matchups, printable sheet, and perform instant 1-click adjustments."
    )

    with st.expander("💡 How to Use Wrestler Lookup at the Head Table / Weigh-In Desk", expanded=False):
        st.markdown(
            """
            - **Instant Multi-Token Search**: Type any combination of first/last name, school/club, weight, Mat #, or Bracket ID (e.g. `Mason`, `Apex 8U`, `Mat 1`, `COED-8U-BEG-01`, or `54.5`).
            - **Check Mat & Bout Assignments**: Every wrestler row and card prominently displays their assigned **`Mat #`** (`Mat 1 .. Mat N`) so parents and coaches know which table to report to before the session starts.
            - **Print Master Wrestler & Mat Handout**: Click **📑 Download Printable Wrestler & Mat Roster (.html)** below to print the full tournament wrestler list (sorted Alphabetically A–Z, by Mat #, by Club, or by Age Group) to hand out to table workers, mat runners, and coaches.
            - **Status Filters**: Switch **Entry Status** to `Scratched` to find and **↩️ Restore** a no-show wrestler who arrived late, or `Flagged` to see wrestlers in brackets with weight/teammate warnings.
            - **All-in-One Wrestler Card**: Each card displays the wrestler's pod roster, seed, weight spread, scheduled bouts (with opponent weight diffs and same-club alerts), an embedded printable bracket sheet preview, and **⚡ Quick Actions** to edit weight, move brackets (ranked by fit), or scratch on the spot.
            """
        )

    all_gids = [g.group_id for g in groups]
    gid_map = {g.group_id: g for g in groups}
    mat_count = max(1, int(getattr(tournament.config, "mat_count", 4) or 4))

    # Collect unique filter options across active + scratched
    divisions = ["All"] + list(dict.fromkeys([g.division for g in groups] + [str(r.get("division", "Coed")) for r in tournament.scratched_wrestlers]))
    ages = ["All"] + list(dict.fromkeys([g.age_group for g in groups] + [str(r.get("age_group", "")) for r in tournament.scratched_wrestlers if r.get("age_group")]))
    skills = ["All"] + list(dict.fromkeys([g.skill_level for g in groups] + [str(r.get("skill_level", "")) for r in tournament.scratched_wrestlers if r.get("skill_level")]))
    teams_set = sorted(
        {w.display_team for g in groups for w in g.wrestlers if w.display_team}
        | {str(r.get("team", "")) for r in tournament.scratched_wrestlers if r.get("team")}
    )
    teams = ["All"] + teams_set
    mat_nums_present = sorted({g.mat_number for g in groups if g.mat_number is not None} | set(range(1, mat_count + 1)))
    wl_mat_opts = ["All"] + [f"Mat {m}" for m in mat_nums_present]
    if any(g.mat_number is None for g in groups):
        wl_mat_opts.append("Unassigned")

    s_col1, s_col2 = st.columns([2.5, 1.5])
    with s_col1:
        wl_query = st.text_input(
            "🔎 Search by Wrestler Name, Club/School, Mat #, Bracket ID, or Weight",
            placeholder="e.g. Mason, Apex, Mat 1, COED-8U-BEG-01, 54.5...",
            key="wl_query",
            help="Type any part of a wrestler's name, team/club, weight, Mat #, or Bracket ID.",
        )
    actual_scratched_total = sum(1 for r in tournament.scratched_wrestlers if r.get("entry_status") != "no_match")
    no_match_total = sum(1 for r in tournament.scratched_wrestlers if r.get("entry_status") == "no_match")
    with s_col2:
        wl_status = st.selectbox(
            "Entry Status",
            options=["All", "Active", "No Match", "Scratched", "Flagged", "Dual-Entry"],
            format_func=lambda s: {
                "All": f"All Entries ({len(tournament.result.wrestlers) + len(tournament.scratched_wrestlers)})",
                "Active": f"✅ Active in Brackets ({len(tournament.result.wrestlers)})",
                "No Match": f"⚪ No Match ({no_match_total})",
                "Scratched": f"❌ Scratched ({actual_scratched_total})",
                "Flagged": "⚠️ In Flagged / Warning Brackets",
                "Dual-Entry": "🔁 Dual-Division Entries",
            }[s],
            key="wl_status",
            help="Filter by active roster, no-match entries, scratched no-shows, flagged pods, or dual-division entries.",
        )

    f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns(5)
    with f_col1:
        wl_div = st.selectbox("Division", divisions, key="wl_div", help="Filter by Coed or Girls division.")
    with f_col2:
        wl_age = st.selectbox("Age Group", ages, key="wl_age", help="Filter by age group (6U, 8U, 10U, 12U, 14U).")
    with f_col3:
        wl_skill = st.selectbox("Skill Level", skills, key="wl_skill", help="Filter by Beginner, Intermediate, or Advanced.")
    with f_col4:
        wl_team = st.selectbox("School / Club", teams, key="wl_team", help="View all wrestlers from a specific school or wrestling club.")
    with f_col5:
        wl_mat = st.selectbox("Mat #", wl_mat_opts, key="wl_mat", help="Filter wrestlers assigned to a specific mat/table.")

    matches = search_tournament_wrestlers(
        tournament,
        query=wl_query,
        division=wl_div,
        age_group=wl_age,
        skill_level=wl_skill,
        team=wl_team,
        status=wl_status,
        mat_number=wl_mat,
    )

    if not matches:
        st.warning("No wrestlers matched your search criteria.")
        return

    active_matches = sum(1 for m in matches if m["status"] == "Active")
    no_match_matches = sum(1 for m in matches if m["status"] == "No Match")
    scratched_matches = sum(1 for m in matches if m["status"] == "Scratched")
    wl_export_dir = DEFAULT_STORE_DIR / tournament.slug / "exports"
    wl_export_dir.mkdir(parents=True, exist_ok=True)
    wl_roster_html_path = export_printable_roster_html(
        tournament.result,
        wl_export_dir / "roster_directory.html",
        tournament_name=tournament.name,
        scratched_wrestlers=tournament.scratched_wrestlers,
    )
    cnt_col, dl_roster_col = st.columns([2.2, 1.3])
    with cnt_col:
        no_match_summary = f", **{no_match_matches}** no-match" if no_match_matches else ""
        st.caption(
            f"Found **{len(matches)}** matching entry(s) "
            f"(**{active_matches}** active{no_match_summary}, **{scratched_matches}** scratched)."
        )
    with dl_roster_col:
        st.download_button(
            "📑 Download Printable Wrestler & Mat Roster (.html)",
            data=wl_roster_html_path.read_bytes(),
            file_name=f"{tournament.slug}_wrestler_mat_roster.html",
            mime="text/html",
            use_container_width=True,
            key="btn_wl_dl_roster_html",
            help="Download a printable Master Wrestler & Mat Directory handout (A-Z, By Mat #, By Club, or By Division/Age).",
        )

    # Roster Summary Table
    with st.expander("📋 Matching Wrestlers Directory Table", expanded=(not wl_query.strip() and len(matches) > 8)):
        table_rows = []
        for m in matches:
            w = m["wrestler"]
            g = m["group"]
            m_status = m["status"]
            if m["bouts"]:
                bouts_summary = ", ".join(f"Bout {b['bout_number']} vs {b['opponent_name']}" for b in m["bouts"])
            elif m_status == "Active":
                bouts_summary = "Solo / No Bouts"
            elif m_status == "No Match":
                bouts_summary = m["scratch_record"].get("reason", "NO MATCH — No opponent within weight range")
            else:
                bouts_summary = f"Scratched ({m['scratch_record'].get('reason', 'No-show')})"

            status_disp = (
                "✅ Active"
                if m_status == "Active"
                else ("⚪ No Match" if m_status == "No Match" else "❌ Scratched")
            )
            table_rows.append(
                {
                    "Status": status_disp,
                    "Wrestler": w.name,
                    "Weight (lbs)": f"{w.weight:g}",
                    "School / Club": w.display_team,
                    "Mat #": g.mat_label if g else ("NO MATCH" if m_status == "No Match" else "-"),
                    "Division": w.division,
                    "Age": w.age_group,
                    "Skill": w.skill_level,
                    "Bracket ID": "NO MATCH" if m_status == "No Match" else m["group_id"],
                    "Seed": f"#{m['seed']} of {g.size}" if g and m["seed"] else ("NO MATCH" if m_status == "No Match" else "-"),
                    "Pod Spread": f"{g.weight_spread_lbs:g} lbs ({g.weight_spread_pct:.1f}%)" if g else "-",
                    "Scheduled Bouts": bouts_summary,
                }
            )
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

    max_cards = 25
    shown_matches = matches[:max_cards]
    if len(matches) > max_cards:
        st.info(
            f"Showing the first **{max_cards}** detailed wrestler cards (type a name or filter above to narrow down)."
        )

    for idx, m in enumerate(shown_matches):
        w = m["wrestler"]
        g: BracketGroup | None = m["group"]
        is_active = m["status"] == "Active"
        is_no_match = m["status"] == "No Match"
        dual_badge = " 🔁 Dual-Entry" if w.is_dual_entry else ""

        if is_active and g is not None:
            warn_badge = " ⚠️" if g.has_warnings else ""
            lock_badge = " 🔒" if g.locked else ""
            mat_badge = f"🏟️ {g.mat_label}  |  "
            card_title = (
                f"✅ {w.name} ({w.weight:g} lbs) — {w.display_team}  |  "
                f"{mat_badge}{g.group_id}{lock_badge}{warn_badge} ({w.division} {w.age_group} {w.skill_level}, Seed #{m['seed']}/{g.size}){dual_badge}"
            )
        elif is_no_match:
            card_title = (
                f"⚪ [NO MATCH] {w.name} ({w.weight:g} lbs) — {w.display_team}  |  "
                f"NO MATCH ({w.division} {w.age_group} {w.skill_level}){dual_badge}"
            )
        else:
            rec = m["scratch_record"] or {}
            card_title = (
                f"❌ [SCRATCHED] {w.name} ({w.weight:g} lbs) — {w.team}  |  "
                f"Formerly {m['group_id']} ({w.division} {w.age_group} {w.skill_level}){dual_badge}"
            )

        expand_card = len(shown_matches) <= 5 or bool(wl_query.strip() and len(shown_matches) <= 10)
        with st.expander(card_title, expanded=expand_card):
            if not is_active:
                rec = m["scratch_record"] or {}
                sc_c1, sc_c2 = st.columns([3, 1])
                with sc_c1:
                    if is_no_match:
                        st.info(
                            f"**Status:** `NO MATCH` &nbsp;|&nbsp; "
                            f"**Division / Age / Skill:** `{w.division} • {w.age_group} • {w.skill_level}` &nbsp;|&nbsp; "
                            f"**Details:** `{rec.get('reason', 'NO MATCH — No opponent within weight range')}`"
                        )
                    else:
                        st.error(
                            f"**Scratched at:** `{rec.get('scratched_at', 'Unknown')}` &nbsp;|&nbsp; "
                            f"**Reason:** `{rec.get('reason', 'No-show')}` &nbsp;|&nbsp; "
                            f"**Original Bracket(s):** `{m['group_id'] or 'N/A'}`"
                        )
                with sc_c2:
                    s_idx = m["scratch_index"]
                    if s_idx is not None:
                        same_div_gids = [
                            grp.group_id
                            for grp in sorted(
                                [gr for gr in tournament.result.groups if gr.division == w.division],
                                key=lambda gr: abs(((gr.min_weight + gr.max_weight) / 2.0) - w.weight),
                            )
                        ]
                        other_gids = [gr.group_id for gr in tournament.result.groups if gr.division != w.division]
                        place_opts = (same_div_gids + ["__NEW__"] + other_gids) if is_no_match else (["AUTO"] + same_div_gids + ["__NEW__"] + other_gids)
                        place_target = st.selectbox(
                            "Target Bracket",
                            options=place_opts,
                            format_func=lambda opt, _div=w.division: (
                                "🎯 Auto (Original / New)" if opt == "AUTO"
                                else (f"➕ Create New {_div} Bracket" if opt == "__NEW__" else _group_summary_label(gid_map[opt]))
                            ),
                            key=f"wl_restore_target_{s_idx}_{idx}",
                            help="Choose an existing bracket (closest weight in same division listed first) or create a new bracket.",
                        )
                        btn_lbl = "↩️ Place in Selected Bracket" if is_no_match else "↩️ Restore Wrestler to Bracket"
                        if st.button(
                            btn_lbl,
                            key=f"wl_restore_{s_idx}_{idx}",
                            type="primary",
                            use_container_width=True,
                            help="Place or restore this wrestler into the selected bracket without changing any other division bracket.",
                        ):
                            try:
                                _, restored_gid = restore_scratched_wrestler(
                                    tournament, scratch_index=s_idx, target_group_id=place_target
                                )
                                st.success(f"Placed {w.name} into {restored_gid}!")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                continue

            assert g is not None
            info_col1, info_col2 = st.columns([1.3, 1.7])
            with info_col1:
                st.markdown("##### 🤼 Wrestler & Pod Summary")
                st.markdown(
                    f"- **Wrestler ID:** `{w.id}`  \n"
                    f"- **Scale Weight:** `{w.weight:g} lbs`  \n"
                    f"- **Club / School:** `{w.display_team}`  \n"
                    f"- **Assigned Mat / Table:** `🏟️ {g.mat_label}`  \n"
                    f"- **Division / Age / Skill:** `{w.division} • {w.age_group} • {w.skill_level}`  \n"
                    f"- **Bracket ID:** `{g.group_id}` (Seed **#{m['seed']}** of **{g.size}**)  \n"
                    f"- **Pod Weight Range:** `{g.weight_label}` (Spread `{g.weight_spread_lbs:g} lbs / {g.weight_spread_pct:.1f}%`, Max `{g.allowed_spread_pct:.1f}%`)"
                )
                if g.flags:
                    for fl in g.flags:
                        if fl.severity == "warning":
                            st.warning(f"**[{fl.code}]** {fl.message}")
                        else:
                            st.info(f"**[{fl.code}]** {fl.message}")

                st.markdown("**Pod Roster:**")
                for p_idx, pw in enumerate(g.wrestlers, start=1):
                    marker = "👉 " if pw.id == w.id else "&nbsp;&nbsp;&nbsp;&nbsp;"
                    bold_s = "**" if pw.id == w.id else ""
                    tm_flag = " *(Teammate)*" if (pw.id != w.id and pw.team_key and pw.team_key == w.team_key) else ""
                    st.markdown(
                        f"{marker}Seed #{p_idx}: {bold_s}{pw.name}{bold_s} — `{pw.weight:g} lbs` ({pw.display_team}){tm_flag}"
                    )

            with info_col2:
                bouts_hdr = (
                    "##### 🥊 Scheduled Bouts in Bracket (Best 2 out of 3 Series)"
                    if g.size == 2 or g.bracket_format == "best_of_3"
                    else "##### 🥊 Scheduled Bouts in Bracket"
                )
                st.markdown(bouts_hdr)
                if not m["bouts"]:
                    st.info("No bouts scheduled (solo bracket).")
                else:
                    bout_rows = []
                    for b in m["bouts"]:
                        opp_wt = f"{b['opponent_weight']:g} lbs" if b["opponent_weight"] is not None else "-"
                        diff_lbs = (
                            f"{b['opponent_weight'] - w.weight:+g} lbs"
                            if b["opponent_weight"] is not None
                            else "-"
                        )
                        is_rubber_bout = g.size == 2 and b["bout_number"] == 3
                        bout_lbl = "Bout 3* (If 1-1)" if is_rubber_bout else f"Bout {b['bout_number']}"
                        bout_rows.append(
                            {
                                "Bout #": bout_lbl,
                                "Round": f"Rd {b['round_number']}",
                                "Opponent": b["opponent_name"],
                                "Opp. Weight": opp_wt,
                                "Wt Diff": diff_lbs,
                                "Opp. Club": b["opponent_team"],
                                "Notes": "⚠️ Same Club" if b["is_teammate"] else ("🏆 Best 2 of 3" if g.size == 2 else "✅ OK"),
                            }
                        )
                    st.dataframe(bout_rows, use_container_width=True, hide_index=True)

                with st.expander("🖨️ View Printable Bracket Score Sheet", expanded=False):
                    bout_count = len(g.bouts) if g.bouts else 1
                    card_height = max(720, 550 + bout_count * 82 + g.size * 22)
                    components.html(
                        render_single_bracket_preview_html(g, tournament_name=tournament.name),
                        height=card_height,
                        scrolling=False,
                    )

            st.markdown("---")
            st.markdown("##### ⚡ Quick Actions for This Wrestler")
            qa_col1, qa_col2, qa_col3 = st.columns(3)
            ukey = f"{w.id}_{g.group_id}_{idx}"

            with qa_col1:
                with st.container(border=True):
                    st.markdown("**✏️ Edit Weight / Details**")
                    ed_name = st.text_input("Name", value=w.name, key=f"wl_ed_name_{ukey}")
                    ew_c1, ew_c2 = st.columns(2)
                    ed_wt = ew_c1.number_input(
                        "Weight (lbs)",
                        value=float(w.weight),
                        min_value=20.0,
                        max_value=285.0,
                        step=0.1,
                        key=f"wl_ed_wt_{ukey}",
                    )
                    ed_team = ew_c2.text_input("Club", value=w.team, key=f"wl_ed_team_{ukey}")
                    ed_c1, ed_c2, ed_c3 = st.columns(3)
                    div_choices = list(tournament.config.divisions)
                    if w.division not in div_choices:
                        div_choices.append(w.division)
                    ed_div = ed_c1.selectbox(
                        "Division",
                        options=div_choices,
                        index=div_choices.index(w.division),
                        key=f"wl_ed_div_{ukey}",
                        help="Update this wrestler's division (e.g. Coed or Girls).",
                    )
                    age_choices = list(tournament.config.age_groups)
                    if w.age_group not in age_choices:
                        age_choices.append(w.age_group)
                    ed_age = ed_c2.selectbox(
                        "Age Group",
                        options=age_choices,
                        index=age_choices.index(w.age_group),
                        key=f"wl_ed_age_{ukey}",
                        help="Update this wrestler's age group (e.g. 6U, 8U, 10U).",
                    )
                    skill_choices = list(tournament.config.skill_levels)
                    if w.skill_level not in skill_choices:
                        skill_choices.append(w.skill_level)
                    ed_skill = ed_c3.selectbox(
                        "Skill Level",
                        options=skill_choices,
                        index=skill_choices.index(w.skill_level),
                        key=f"wl_ed_skill_{ukey}",
                        help="Update this wrestler's skill level (e.g. Beginner or Advanced).",
                    )
                    if st.button(
                        "💾 Save Changes",
                        key=f"wl_btn_save_{ukey}",
                        use_container_width=True,
                        help="Update this wrestler's name, weight, club, division, age group, or skill level in-place.",
                    ):
                        try:
                            update_wrestler_in_bracket(
                                tournament,
                                group_id=g.group_id,
                                wrestler_id=w.id,
                                name=ed_name,
                                weight=float(ed_wt),
                                team=ed_team,
                                skill_level=ed_skill,
                                age_group=ed_age,
                                division=ed_div,
                            )
                            st.success(f"Updated {ed_name}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

            with qa_col2:
                with st.container(border=True):
                    st.markdown("**➡️ Move to Another Bracket**")
                    candidates = find_candidate_brackets_for_walkin(
                        tournament,
                        weight=w.weight,
                        division=w.division,
                        age_group=w.age_group,
                        skill_level=w.skill_level,
                        team=w.team,
                    )
                    cand_map = {c["group_id"]: c for c in candidates if c["group_id"] != g.group_id}
                    other_same_bucket = [c["group_id"] for c in candidates if c["group_id"] != g.group_id]
                    other_all = [gid for gid in all_gids if gid != g.group_id and gid not in cand_map]
                    move_opts = other_same_bucket + ["__NEW__"] + other_all

                    def _fmt_move_dest(opt: str, _cmap=cand_map, _g=g) -> str:
                        if opt == "__NEW__":
                            return f"➕ Spin Off New Bracket ({_g.division} {_g.age_group} {_g.skill_level}, stays on {_g.mat_label})"
                        if opt in _cmap:
                            c = _cmap[opt]
                            badge = "✅" if c["fits_spread"] else "⚠️"
                            tm = " [Teammate]" if c["has_teammate"] else ""
                            return (
                                f"{badge} [{c['mat_label']}] {opt} ({c['current_weights']}, size {c['current_size']}/{c['max_size']}, "
                                f"new spread {c['new_spread_pct']:.1f}%){tm}"
                            )
                        return _group_summary_label(gid_map[opt])

                    dest_gid = st.selectbox(
                        "Target Bracket (Ranked by Fit)",
                        options=move_opts,
                        format_func=_fmt_move_dest,
                        key=f"wl_mv_dest_{ukey}",
                        help="Brackets in the same division/age/skill are listed first, ranked by weight proximity and capacity.",
                    )
                    if st.button(
                        "➡️ Move Wrestler",
                        key=f"wl_btn_move_{ukey}",
                        use_container_width=True,
                        help="Move this wrestler to the selected destination bracket and update bouts.",
                    ):
                        try:
                            move_wrestler(
                                tournament,
                                wrestler_id=w.id,
                                from_group_id=g.group_id,
                                to_group_id=dest_gid,
                            )
                            st.success(f"Moved {w.name} to {dest_gid}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

            with qa_col3:
                with st.container(border=True):
                    st.markdown("**❌ Scratch Wrestler**")
                    sc_reason = st.text_input(
                        "Reason",
                        value="No-show",
                        key=f"wl_sc_reason_{ukey}",
                    )
                    sc_both = st.checkbox(
                        "Scratch all divisions (if dual)",
                        value=True,
                        key=f"wl_sc_both_{ukey}",
                    )
                    if st.button(
                        "❌ Confirm Scratch",
                        key=f"wl_btn_scratch_{ukey}",
                        type="secondary",
                        use_container_width=True,
                        help="Scratch this wrestler and recalculate bouts for the remaining pod.",
                    ):
                        try:
                            _, sc_gids = scratch_wrestler(
                                tournament,
                                wrestler_id=w.id,
                                group_id=None if sc_both else g.group_id,
                                scratch_all_divisions=sc_both,
                                reason=sc_reason.strip() or "No-show",
                            )
                            st.success(f"Scratched {w.name} from {', '.join(sc_gids)}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))


def _render_history_tab(tournament: SavedTournament) -> None:
    st.subheader("📜 Tournament Activity & Audit Log")
    st.caption(
        "Chronological record of every spreadsheet import, Madison optimization, mat assignment, walk-in addition, no-show scratch, "
        "restoration, and manual bracket adjustment saved to disk (`~/.bracketman/tournaments/`)."
    )
    if not tournament.history:
        st.info("No activity recorded yet.")
        return
    for entry in reversed(tournament.history):
        st.markdown(f"- `{entry}`")


def main() -> None:
    logo_file = _find_file("assets/logo.jpg")
    logo_icon = str(logo_file) if logo_file.exists() else "🚀"
    st.set_page_config(
        page_title="Bracketman — Wrestling Tournament Manager",
        page_icon=logo_icon,
        layout="wide",
    )

    active = _render_sidebar()

    if active is None:
        st.title("Welcome to Bracketman 🤼")
        st.markdown(
            "Create your first tournament in the **sidebar on the left** and paste your Google Sheet link "
            "(or load the built-in 120-wrestler sample roster) to build Madison weight brackets!"
        )
        st.info(
            "**How Bracketman Works:**\n"
            "1. **Create or Select a Tournament** in the left sidebar (and configure your **Mat Count**).\n"
            "2. **Import Your Roster** in **📥 Sheet Import & Sync** from a Google Sheet link or Excel/CSV upload.\n"
            "3. **Review Pods & Mats** in **🏆 Brackets Explorer** or look up individual wrestlers and their assigned **Mat #** in **🔍 Wrestler Lookup**.\n"
            "4. **Balance Mats, Walk-Ins & Scratches** in **🛠️ Tweak & Regenerate by ID**.\n"
            "5. **Print 1-Page Score Sheets** (all at once or per **Mat #**) in **🖨️ Print & Export**."
        )
        return

    st.title(active.name)
    if active.sheet_url:
        st.caption(f"Connected Google Sheet: {active.sheet_url}")

    with st.expander("🧭 Quick-Start Tournament Director Workflow Guide", expanded=False):
        st.markdown(
            """
            1. **📥 Sheet Import & Sync**: Connect your Google Sheet (or upload `.xlsx`/`.csv`), set your target bracket size (default `4`), max weight spread (`10%`), and **Mat Count** (default `4`), and click **🚀 Import Spreadsheet & Build Brackets**.
            2. **🏆 Brackets Explorer**: Inspect generated brackets by division, age, **Mat #**, or warning flags (`⚠️`). Reassign any bracket's Mat # inline or lock (`🔒`) finalized pods.
            3. **🔍 Wrestler Lookup**: Instant search at the weigh-in table or head table by wrestler name, club/school, weight, **Mat #**, or Bracket ID—with 1-click weight edits, bracket moves, and scratch/restore.
            4. **🛠️ Tweak & Regenerate by ID**: Add late walk-ins (automatically ranked by best bracket fit), scratch no-shows, re-optimize an age division, or use the **🏟️ Mat / Table Assignment & Load Balancer** to balance bouts across mats.
            5. **🖨️ Print & Export**: Print 1-page-per-bracket mat-side score sheets (in **Full** or **Bout Sheet Only** layout, filtered by **Mat #** for each scoring table) or export multi-tab Excel/CSV files.
            """
        )

    tab_explore, tab_lookup, tab_tweak, tab_import, tab_print, tab_log = st.tabs(
        [
            "🏆 Brackets Explorer",
            "🔍 Wrestler Lookup",
            "🛠️ Tweak & Regenerate by ID",
            "📥 Sheet Import & Sync",
            "🖨️ Print & Export",
            "📜 Audit Log",
        ]
    )

    with tab_explore:
        _render_explorer_tab(active)
    with tab_lookup:
        _render_wrestler_lookup_tab(active)
    with tab_tweak:
        _render_tweak_and_regenerate_tab(active)
    with tab_import:
        _render_import_tab(active)
    with tab_print:
        _render_print_and_export_tab(active)
    with tab_log:
        _render_history_tab(active)

    st.markdown("---")
    st.caption(
        "Bracketman — Created by **Simon Engelbert** &nbsp;|&nbsp; "
        "📦 [GitHub Repository](https://github.com/sengelbert/bracketman) &nbsp;|&nbsp; "
        "📖 [User Guide](https://github.com/sengelbert/bracketman#readme) &nbsp;|&nbsp; "
        "🏗️ [Architecture & Decisions](https://github.com/sengelbert/bracketman/blob/main/docs/ARCHITECTURE_AND_DECISIONS.md)"
    )


if __name__ == "__main__":
    main()


