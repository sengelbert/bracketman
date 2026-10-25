"""Streamlit web UI for managing wrestling tournaments, tweaking brackets, and printing."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from bracketman.exporters.csv_xlsx import export_csv_files, export_xlsx_workbook
from bracketman.exporters.html import export_printable_html, render_single_bracket_preview_html
from bracketman.models import BracketGroup, TournamentResult
from bracketman.store import (
    SavedTournament,
    add_walkin_wrestler,
    create_tournament,
    delete_tournament,
    find_candidate_brackets_for_walkin,
    import_spreadsheet_to_tournament,
    list_tournaments,
    load_tournament,
    merge_brackets,
    move_wrestler,
    regenerate_brackets_by_ids,
    restore_scratched_wrestler,
    save_tournament,
    scratch_wrestler,
    swap_wrestlers,
    toggle_bracket_lock,
    update_wrestler_in_bracket,
)


SAMPLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1VWSHOuqCDildUjOL7BdS7CQ4OdJ6K78m8Osr3RjqoLY/edit?usp=drivesdk"
)
MERGE_ID_RE = re.compile(r"Merge into ([A-Z0-9-]+)")


def _extract_suggested_group_id(suggestion: str | None) -> str | None:
    if not suggestion:
        return None
    m = MERGE_ID_RE.search(suggestion)
    return m.group(1) if m else None


def _group_summary_label(g: BracketGroup) -> str:
    lock_icon = "🔒 " if g.locked else ""
    warn_icon = "⚠️ " if g.has_warnings else ""
    return (
        f"{lock_icon}{warn_icon}{g.group_id} | {g.division} {g.age_group} {g.skill_level} | "
        f"{g.size} wrestlers ({g.weight_label}, spread {g.weight_spread_lbs:g}lb / {g.weight_spread_pct:.1f}%)"
    )


def _render_sidebar() -> SavedTournament | None:
    logo_path = Path("assets/logo.jpg")
    if logo_path.exists():
        st.sidebar.image(str(logo_path), use_container_width=True)
    st.sidebar.title("Bracketman")
    st.sidebar.caption("Tournament Grouping & Bracket Manager")

    tournaments = list_tournaments()
    slug_map = {t.slug: t for t in tournaments}

    with st.sidebar.expander("➕ Create New Tournament", expanded=not bool(tournaments)):
        with st.form("create_tournament_form", clear_on_submit=True):
            new_name = st.text_input("Tournament Name", placeholder="e.g. SSWL Week 1 Qualifier")
            new_url = st.text_input(
                "Google Sheet URL (optional)",
                value=SAMPLE_SHEET_URL if not tournaments else "",
                placeholder="https://docs.google.com/spreadsheets/d/...",
            )
            import_now = st.checkbox("Import & build brackets immediately", value=True)
            submitted = st.form_submit_button("Create Tournament", type="primary")
            if submitted:
                if not new_name.strip():
                    st.error("Please enter a tournament name.")
                else:
                    t = create_tournament(name=new_name.strip(), sheet_url=new_url.strip())
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
    )
    st.session_state["active_tournament_slug"] = selected_slug
    active = load_tournament(selected_slug)

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"**Entries:** `{len(active.result.wrestlers)}`  \n"
        f"**Brackets:** `{len(active.result.groups)}`  \n"
        f"**Locked/Tweaked:** `{sum(1 for g in active.result.groups if g.locked or g.manually_modified)}`  \n"
        f"**Flagged:** `{sum(1 for g in active.result.groups if g.has_warnings)}`  \n"
        f"**Updated:** `{active.updated_at}`"
    )

    with st.sidebar.expander("🗑️ Delete Tournament"):
        st.warning(f"Delete **{active.name}** permanently?")
        if st.button("Confirm Delete Tournament", key=f"del_{active.slug}"):
            delete_tournament(active.slug)
            st.session_state.pop("active_tournament_slug", None)
            st.rerun()

    return active


def _render_import_tab(tournament: SavedTournament) -> None:
    st.subheader("📥 Spreadsheet Import & Grouping Settings")
    st.markdown(
        "Paste a **Google Sheet link** (all team tabs will be read automatically) or **upload an `.xlsx`/`.csv` file**."
    )

    col_src1, col_src2 = st.columns([3, 2])
    with col_src1:
        sheet_url = st.text_input(
            "Google Spreadsheet URL",
            value=tournament.sheet_url or SAMPLE_SHEET_URL,
            placeholder="https://docs.google.com/spreadsheets/d/.../edit",
        )
    with col_src2:
        uploaded_file = st.file_uploader(
            "Or Upload Local Spreadsheet (.xlsx / .csv)",
            type=["xlsx", "csv"],
        )

    st.markdown("#### Grouping Rules & Import Mode")
    c1, c2, c3, c4 = st.columns(4)
    cfg = tournament.config
    with c1:
        target_sz = st.number_input(
            "Target Bracket Size",
            min_value=2,
            max_value=8,
            value=int(cfg.default_rule.target_group_size),
        )
    with c2:
        max_sz = st.number_input(
            "Max Bracket Size",
            min_value=2,
            max_value=8,
            value=int(cfg.default_rule.max_group_size),
        )
    with c3:
        min_sz = st.number_input(
            "Min Desired Size",
            min_value=2,
            max_value=6,
            value=int(cfg.default_rule.min_group_size),
        )
    with c4:
        base_spread_pct = st.number_input(
            "Base Max Spread % (<50 lbs)",
            min_value=3.0,
            max_value=25.0,
            value=float(cfg.default_rule.max_weight_spread_pct),
            step=0.5,
        )

    o1, o2, o3, o4 = st.columns(4)
    with o1:
        prog_spread = st.checkbox(
            "Progressive Weight Spread (wider lbs/% as weight increases)",
            value=bool(cfg.default_rule.progressive_spread),
        )
    with o2:
        sep_teams = st.checkbox(
            "Separate Teammates Across Pods",
            value=bool(cfg.default_rule.separate_teammates),
        )
    with o3:
        merge_skills = st.checkbox(
            "Auto-Merge Solo Skill Stragglers (Same Age)",
            value=bool(cfg.allow_skill_merge_for_stragglers),
        )
    with o4:
        merge_ages = st.checkbox(
            "Auto-Merge Solo Age Stragglers",
            value=bool(cfg.allow_age_merge_for_stragglers),
        )

    locked_count = sum(1 for g in tournament.result.groups if g.locked or g.manually_modified)
    mode_options = ["full_overwrite", "preserve_locked"]
    mode_labels = {
        "full_overwrite": "🔄 Full Overwrite — Rebuild all brackets from scratch",
        "preserve_locked": (
            f"🔒 Sync & Keep Locked/Tweaked Brackets ({locked_count} currently locked) — "
            "Only regroup unlocked wrestlers"
        ),
    }
    import_mode = st.radio(
        "When importing from spreadsheet:",
        options=mode_options,
        format_func=lambda m: mode_labels[m],
        horizontal=False,
    )

    if st.button("🚀 Import Spreadsheet & Build Brackets", type="primary"):
        # Persist updated rule settings onto tournament config
        cfg.default_rule.target_group_size = int(target_sz)
        cfg.default_rule.max_group_size = int(max_sz)
        cfg.default_rule.min_group_size = int(min_sz)
        cfg.default_rule.max_weight_spread_pct = float(base_spread_pct)
        cfg.default_rule.progressive_spread = bool(prog_spread)
        cfg.default_rule.separate_teammates = bool(sep_teams)
        for ag_cfg in cfg.age_group_overrides.values():
            ag_cfg["target_group_size"] = int(target_sz)
            ag_cfg["max_group_size"] = int(max_sz)
            ag_cfg["max_weight_spread_pct"] = float(base_spread_pct)
            for sk_cfg in ag_cfg.get("skills", {}).values():
                sk_cfg["target_group_size"] = int(target_sz)
                sk_cfg["max_group_size"] = int(max_sz)

        try:
            with st.spinner("Reading tabs and building Madison weight brackets..."):
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
                f"{len(tournament.result.wrestlers)} wrestler entries!"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to import spreadsheet: {exc}")


def _render_explorer_tab(tournament: SavedTournament) -> None:
    groups = tournament.result.groups
    if not groups:
        st.info("No brackets built yet. Go to **📥 Sheet Import & Sync** to load a Google Sheet.")
        return

    # KPI Row
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Wrestler Entries", len(tournament.result.wrestlers))
    k2.metric("Total Brackets", len(groups))
    k3.metric("Total Bouts", sum(len(g.bouts) for g in groups))
    k4.metric("4-Man / 3-Man / 2-Man", f"{sum(1 for g in groups if g.size==4)} / {sum(1 for g in groups if g.size==3)} / {sum(1 for g in groups if g.size==2)}")
    k5.metric("Solo / Flagged", f"{sum(1 for g in groups if g.size==1)} / {sum(1 for g in groups if g.has_warnings)}")

    # Division / Age / Skill Summary Table
    with st.expander("📊 Division / Age Group / Skill Summary Breakdown", expanded=True):
        buckets: dict[tuple[str, str, str], list[BracketGroup]] = {}
        for g in groups:
            buckets.setdefault((g.division, g.age_group, g.skill_level), []).append(g)

        summary_rows = []
        for (div, age, skill), grps in buckets.items():
            multi = [g for g in grps if g.size > 1]
            avg_pct = sum(g.weight_spread_pct for g in multi) / len(multi) if multi else 0.0
            avg_lbs = sum(g.weight_spread_lbs for g in multi) / len(multi) if multi else 0.0
            summary_rows.append(
                {
                    "Division": div,
                    "Age Group": age,
                    "Skill Level": skill,
                    "Wrestlers": sum(g.size for g in grps),
                    "Brackets": len(grps),
                    "Weight Range": f"{min(g.min_weight for g in grps):g}–{max(g.max_weight for g in grps):g} lbs",
                    "Avg Spread (lbs)": f"{avg_lbs:.1f} lbs",
                    "Avg Spread (%)": f"{avg_pct:.1f}%",
                    "Solo / Warnings": sum(1 for g in grps if g.has_warnings),
                }
            )
        st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    # Filter Bar
    f1, f2, f3, f4, f5 = st.columns([1.2, 1.2, 1.2, 1.5, 2.2])
    divisions = ["All"] + list(dict.fromkeys(g.division for g in groups))
    ages = ["All"] + list(dict.fromkeys(g.age_group for g in groups))
    skills = ["All"] + list(dict.fromkeys(g.skill_level for g in groups))

    with f1:
        sel_div = st.selectbox("Division", divisions, key="exp_div")
    with f2:
        sel_age = st.selectbox("Age Group", ages, key="exp_age")
    with f3:
        sel_skill = st.selectbox("Skill Level", skills, key="exp_skill")
    with f4:
        sel_status = st.selectbox(
            "Filter Status",
            ["All Brackets", "⚠️ Flagged / Warnings Only", "🧍 Solo Wrestlers Only", "🔒 Locked / Tweaked Only"],
            key="exp_status",
        )
    with f5:
        search_q = st.text_input("Search Bracket ID, Wrestler, or Club", key="exp_search").strip().lower()

    filtered: list[BracketGroup] = []
    for g in groups:
        if sel_div != "All" and g.division != sel_div:
            continue
        if sel_age != "All" and g.age_group != sel_age:
            continue
        if sel_skill != "All" and g.skill_level != sel_skill:
            continue
        if sel_status == "⚠️ Flagged / Warnings Only" and not g.has_warnings:
            continue
        if sel_status == "🧍 Solo Wrestlers Only" and g.size != 1:
            continue
        if sel_status == "🔒 Locked / Tweaked Only" and not (g.locked or g.manually_modified):
            continue
        if search_q:
            haystack = " ".join(
                [g.group_id] + [f"{w.name} {w.team} {w.team_tab}" for w in g.wrestlers]
            ).lower()
            if search_q not in haystack:
                continue
        filtered.append(g)

    st.caption(f"Showing **{len(filtered)}** of **{len(groups)}** brackets")

    for g in filtered:
        with st.expander(_group_summary_label(g), expanded=(len(filtered) <= 6 or g.has_warnings)):
            top_l, top_r = st.columns([4, 1])
            with top_l:
                st.markdown(
                    f"**Bracket ID:** `{g.group_id}` &nbsp;|&nbsp; "
                    f"**Format:** `{g.bracket_format}` &nbsp;|&nbsp; "
                    f"**Actual Spread:** `{g.weight_spread_lbs:g} lbs ({g.weight_spread_pct:.1f}%)` &nbsp;|&nbsp; "
                    f"**Progressive Max Allowed:** `<= {g.allowed_spread_lbs:g} lbs ({g.allowed_spread_pct:.1f}%)`"
                )
            with top_r:
                lock_label = "🔓 Unlock" if g.locked else "🔒 Lock Bracket"
                if st.button(lock_label, key=f"lock_btn_{g.group_id}"):
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
                        ):
                            try:
                                merge_brackets(tournament, g.group_id, target_gid)
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

            bout_count = len(g.bouts) if g.bouts else 1
            card_height = max(440, 370 + bout_count * 70 + g.size * 34)
            components.html(render_single_bracket_preview_html(g), height=card_height, scrolling=False)

            with st.expander(f"❌ Scratch a No-Show from {g.group_id}", expanded=False):
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
        st.info("No brackets available yet. Import a spreadsheet first.")
        return

    all_gids = [g.group_id for g in groups]
    gid_map = {g.group_id: g for g in groups}

    # 1. Walk-Ins & Scratches Section
    st.subheader("⚡ Walk-In Registration & No-Show Scratches")
    st.caption("Quickly handle wrestlers who show up unannounced, or scratch wrestlers who didn't show up.")

    col_walkin, col_scratch = st.columns(2)

    with col_walkin:
        with st.container(border=True):
            st.markdown("#### ➕ Add Walk-In Wrestler")
            w_name = st.text_input("Wrestler Name", key="wi_name", placeholder="e.g. John Doe")
            w_c1, w_c2 = st.columns(2)
            w_wt = w_c1.number_input("Scale Weight (lbs)", min_value=20.0, max_value=285.0, value=55.0, step=0.1, key="wi_wt")
            w_team = w_c2.text_input("School / Club", value="Unattached", key="wi_team")

            w_c3, w_c4, w_c5 = st.columns(3)
            cfg = tournament.config
            div_opts = list(cfg.divisions)
            age_opts = list(cfg.age_groups)
            skill_opts = list(cfg.skill_levels)

            w_div = w_c3.selectbox("Division", div_opts, key="wi_div")
            w_age = w_c4.selectbox("Age Group", age_opts, index=min(1, len(age_opts)-1), key="wi_age")
            w_skill = w_c5.selectbox("Skill Level", skill_opts, key="wi_skill")

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
                        return f"🎯 Auto-Place into Best Bracket ({best['group_id']}: {best['current_weights']}, size {best['current_size']}->{best['current_size']+1})"
                    return "🎯 Auto-Place (Will create new bracket if none fits)"
                if opt == "__NEW__":
                    return f"➕ Create New Bracket in {w_div} {w_age} {w_skill}"
                cand = next((c for c in candidates if c["group_id"] == opt), None)
                if cand:
                    fit_badge = "✅" if cand["fits_spread"] else "⚠️"
                    tm_badge = " [Teammate in pod!]" if cand["has_teammate"] else ""
                    return f"{fit_badge} {opt} ({cand['current_weights']}, size {cand['current_size']}/{cand['max_size']}, spread {cand['new_spread_lbs']:g}lb / {cand['new_spread_pct']:.1f}%){tm_badge}"
                return opt

            target_choice = st.selectbox(
                "Target Placement",
                options=target_options,
                format_func=_format_target,
                key="wi_target",
            )

            if st.button("Add Walk-In to Bracket", type="primary", key="btn_add_walkin"):
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
                )
                sc_reason = st.text_input("Scratch Reason", value="No-show", key="sc_reason")
                sc_all = st.checkbox("Scratch from both Coed & Girls (if dual entry)", value=True, key="sc_all")

                if st.button("Confirm Scratch Wrestler", type="secondary", key="btn_confirm_scratch"):
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

            if tournament.scratched_wrestlers:
                st.markdown("---")
                st.markdown(f"**Recently Scratched ({len(tournament.scratched_wrestlers)}):**")
                for s_idx, sc_rec in enumerate(tournament.scratched_wrestlers):
                    sc_col1, sc_col2 = st.columns([3, 1])
                    sc_col1.caption(
                        f"• **{sc_rec['name']}** ({sc_rec['weight']:g} lbs, {sc_rec['team']}) &mdash; "
                        f"From {', '.join(sc_rec.get('original_groups', []))} ({sc_rec.get('reason', 'No-show')})"
                    )
                    if sc_col2.button("↩️ Restore", key=f"btn_restore_{s_idx}"):
                        try:
                            restore_scratched_wrestler(tournament, scratch_index=s_idx)
                            st.success(f"Restored {sc_rec['name']}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

    st.markdown("---")

    # 2. Targeted Bracket Regeneration by ID(s)
    st.subheader("🔄 Regenerate Specific Bracket(s) by ID")
    st.markdown(
        "Select one or more **Bracket IDs** (or type comma-separated IDs) to re-run the Madison grouping algorithm "
        "on just those brackets without touching the rest of the tournament."
    )

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        selected_regen_ids = st.multiselect(
            "Select Bracket ID(s) to Regenerate",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
        )
    with rc2:
        typed_regen_ids = st.text_input(
            "Or Paste Comma-Separated Bracket IDs",
            placeholder="e.g. COED-8U-BEG-01, COED-8U-BEG-02",
        )

    ro1, ro2, ro3, ro4 = st.columns(4)
    with ro1:
        regen_target_sz = st.number_input("Target Size Override", min_value=2, max_value=8, value=4, key="rg_tsz")
    with ro2:
        regen_max_sz = st.number_input("Max Size Override", min_value=2, max_value=8, value=4, key="rg_msz")
    with ro3:
        regen_spread = st.number_input(
            "Base Max Spread % Override", min_value=3.0, max_value=30.0, value=10.0, step=0.5, key="rg_sp"
        )
    with ro4:
        combine_pool = st.checkbox(
            "Pool selected brackets together (even if different skill/age)",
            value=False,
            help="Check this to combine e.g. a solo Advanced bracket and a Beginner bracket into one shared pool and regroup them.",
        )

    if st.button("⚡ Regenerate Selected Bracket(s)", type="primary"):
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

    # 2. Manual Wrestler Move & Bracket Merge / Swap
    t_col1, t_col2 = st.columns(2)

    with t_col1:
        st.subheader("➡️ Move Wrestler to Another Bracket")
        src_gid = st.selectbox(
            "From Bracket",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="mv_src_gid",
        )
        src_grp = gid_map[src_gid]
        w_options = {w.id: f"{w.name} ({w.weight:g} lbs, {w.display_team})" for w in src_grp.wrestlers}
        sel_wid = st.selectbox(
            "Select Wrestler to Move",
            options=list(w_options.keys()),
            format_func=lambda wid: w_options[wid],
            key="mv_wid",
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
        )
        renum_after_move = st.checkbox("Renumber bracket IDs after move", value=False, key="mv_renum")
        if st.button("Move Wrestler", key="btn_move_wrestler"):
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
        st.subheader("🔀 Swap Two Wrestlers Between Brackets")
        swap_ga = st.selectbox(
            "Bracket A",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="sw_ga",
        )
        wa_map = {w.id: f"{w.name} ({w.weight:g} lbs, {w.team})" for w in gid_map[swap_ga].wrestlers}
        swap_wa = st.selectbox("Wrestler A", options=list(wa_map.keys()), format_func=lambda k: wa_map[k], key="sw_wa")

        other_gids = [gid for gid in all_gids if gid != swap_ga] or all_gids
        swap_gb = st.selectbox(
            "Bracket B",
            options=other_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="sw_gb",
        )
        wb_map = {w.id: f"{w.name} ({w.weight:g} lbs, {w.team})" for w in gid_map[swap_gb].wrestlers}
        swap_wb = st.selectbox("Wrestler B", options=list(wb_map.keys()), format_func=lambda k: wb_map[k], key="sw_wb")

        if st.button("Swap Wrestlers", key="btn_swap_wrestlers"):
            try:
                swap_wrestlers(tournament, swap_ga, swap_wa, swap_gb, swap_wb)
                st.success("Swapped wrestlers and recalculated bouts!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("---")
    b_col1, b_col2 = st.columns(2)

    with b_col1:
        st.subheader("🔗 Merge Two Brackets")
        m_src = st.selectbox(
            "Merge Source Bracket (will be folded into Target)",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="mg_src",
        )
        m_targets = [gid for gid in all_gids if gid != m_src] or all_gids
        m_dst = st.selectbox(
            "Into Target Bracket",
            options=m_targets,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="mg_dst",
        )
        if st.button("Merge Brackets", key="btn_merge_brackets"):
            try:
                merge_brackets(tournament, m_src, m_dst)
                st.success(f"Merged {m_src} into {m_dst}!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with b_col2:
        st.subheader("✏️ Edit Wrestler Weight / Info")
        ed_gid = st.selectbox(
            "Select Bracket",
            options=all_gids,
            format_func=lambda gid: _group_summary_label(gid_map[gid]),
            key="ed_gid",
        )
        ed_grp = gid_map[ed_gid]
        ed_wmap = {w.id: w for w in ed_grp.wrestlers}
        ed_wid = st.selectbox(
            "Select Wrestler",
            options=list(ed_wmap.keys()),
            format_func=lambda wid: f"{ed_wmap[wid].name} ({ed_wmap[wid].weight:g} lbs, {ed_wmap[wid].team})",
            key="ed_wid",
        )
        curr_w = ed_wmap[ed_wid]
        ew1, ew2, ew3 = st.columns(3)
        new_wt = ew1.number_input("Scale Weight (lbs)", value=float(curr_w.weight), step=0.1, key="ed_wt")
        new_name = ew2.text_input("Name", value=curr_w.name, key="ed_name")
        new_team = ew3.text_input("Team / Club", value=curr_w.team, key="ed_team")
        if st.button("Save Wrestler Update", key="btn_edit_wrestler"):
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
    if not groups:
        st.info("No brackets to print or export yet.")
        return

    st.subheader("🖨️ Print & Export Tournament Brackets")

    p1, p2, p3, p4 = st.columns(4)
    divs = ["All"] + list(dict.fromkeys(g.division for g in groups))
    ages = ["All"] + list(dict.fromkeys(g.age_group for g in groups))
    skills = ["All"] + list(dict.fromkeys(g.skill_level for g in groups))

    with p1:
        p_div = st.selectbox("Filter Division", divs, key="pr_div")
    with p2:
        p_age = st.selectbox("Filter Age Group", ages, key="pr_age")
    with p3:
        p_skill = st.selectbox("Filter Skill Level", skills, key="pr_skill")
    with p4:
        p_specific_ids = st.multiselect(
            "Or Specific Bracket ID(s)",
            options=[g.group_id for g in groups],
            key="pr_ids",
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
        export_groups.append(g)

    filtered_result = TournamentResult(
        source=tournament.result.source,
        wrestlers=[w for g in export_groups for w in g.wrestlers],
        groups=export_groups,
        skipped_rows=tournament.result.skipped_rows,
    )

    export_dir = Path("data/tournaments") / tournament.slug / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    html_path = export_printable_html(
        filtered_result,
        export_dir / "brackets.html",
        tournament_name=tournament.name,
    )
    xlsx_path = export_xlsx_workbook(filtered_result, export_dir / "brackets_workbook.xlsx")
    csv_paths = export_csv_files(filtered_result, export_dir)

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.download_button(
            f"🖨️ Download Printable HTML ({len(export_groups)} brackets)",
            data=html_path.read_bytes(),
            file_name=f"{tournament.slug}_brackets.html",
            mime="text/html",
            type="primary",
        )
    with d2:
        st.download_button(
            "📊 Download Multi-Tab Excel (.xlsx)",
            data=xlsx_path.read_bytes(),
            file_name=f"{tournament.slug}_brackets.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with d3:
        st.download_button(
            "📄 Download Bracket Rosters (.csv)",
            data=csv_paths["rosters_csv"].read_bytes(),
            file_name=f"{tournament.slug}_rosters.csv",
            mime="text/csv",
        )
    with d4:
        st.download_button(
            "🥊 Download Bout Schedule (.csv)",
            data=csv_paths["bouts_csv"].read_bytes(),
            file_name=f"{tournament.slug}_bouts.csv",
            mime="text/csv",
        )

    st.markdown("#### Live Printable Bracket Sheet Preview")
    st.caption(
        "Use the **Print Visible Brackets** button inside the preview below (or download the HTML file above) to print one bracket per page."
    )
    components.html(html_path.read_text(encoding="utf-8"), height=850, scrolling=True)


def _render_history_tab(tournament: SavedTournament) -> None:
    st.subheader("📜 Tournament Activity & Audit Log")
    if not tournament.history:
        st.info("No activity recorded yet.")
        return
    for entry in tournament.history:
        st.markdown(f"- `{entry}`")


def main() -> None:
    logo_icon = "assets/logo.jpg" if Path("assets/logo.jpg").exists() else "🚀"
    st.set_page_config(
        page_title="Bracketman — Wrestling Tournament Manager",
        page_icon=logo_icon,
        layout="wide",
    )

    active = _render_sidebar()

    if active is None:
        st.title("Welcome to Bracketman")
        st.markdown(
            "Create your first tournament in the sidebar on the left and paste your Google Sheet link to build brackets!"
        )
        return

    st.title(active.name)
    if active.sheet_url:
        st.caption(f"Connected Google Sheet: {active.sheet_url}")

    tab_explore, tab_tweak, tab_import, tab_print, tab_log = st.tabs(
        [
            "🏆 Brackets Explorer",
            "🛠️ Tweak & Regenerate by ID",
            "📥 Sheet Import & Sync",
            "🖨️ Print & Export",
            "📜 Audit Log",
        ]
    )

    with tab_explore:
        _render_explorer_tab(active)
    with tab_tweak:
        _render_tweak_and_regenerate_tab(active)
    with tab_import:
        _render_import_tab(active)
    with tab_print:
        _render_print_and_export_tab(active)
    with tab_log:
        _render_history_tab(active)


if __name__ == "__main__":
    main()
