"""Tests for tournament persistence, manual bracket tweaking, and targeted regeneration by ID."""

from pathlib import Path

import pytest
from bracketman.io.xlsx import write_xlsx_sheets
from bracketman.store import (
    add_walkin_wrestler,
    assign_brackets_to_mats,
    create_tournament,
    enforce_max_one_bracket_per_division,
    find_duplicate_division_entries,
    import_spreadsheet_to_tournament,
    load_tournament,
    merge_brackets,
    move_wrestler,
    regenerate_brackets_by_ids,
    reoptimize_active_brackets,
    restore_scratched_wrestler,
    scratch_wrestler,
    search_tournament_wrestlers,
    set_bracket_mat,
    swap_wrestlers,
    update_wrestler_in_bracket,
)


def _create_sample_xlsx(path: Path) -> Path:
    sheets = [
        (
            "Arapahoe",
            [
                ["Weight", "Wrestlers Name", "Age Group", "School", "Ability", "Boys / COED Bracket", "Girls only Bracket"],
                [40.0, "Wrestler A", "6U", "AR", "Novice", "X", ""],
                [41.0, "Wrestler B", "6U", "AR", "Novice", "X", ""],
                [42.0, "Wrestler C", "6U", "AR", "Novice", "X", ""],
                [43.0, "Wrestler D", "6U", "AR", "Novice", "X", ""],
                [48.0, "Wrestler E", "6U", "AR", "Novice", "X", ""],
                [49.0, "Wrestler F", "6U", "AR", "Novice", "X", ""],
                [50.0, "Wrestler G", "6U", "AR", "Novice", "X", ""],
                [49.5, "Wrestler H", "6U", "AR", "Experienced", "X", ""],
            ],
        )
    ]
    write_xlsx_sheets(path, sheets)
    return path


def test_store_lifecycle_and_manual_tweaks(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Example Tournament", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    reloaded = load_tournament(t.slug, base_dir=base_dir)
    assert len(reloaded.result.wrestlers) == 8
    # 7 in 6U Beginner -> 2 groups (4 and 3), 1 in 6U Advanced -> 1 group (solo)
    assert len(reloaded.result.groups) == 3

    g1 = reloaded.result.groups[0]
    g2 = reloaded.result.groups[1]
    assert g1.group_id == "COED-6U-BEG-01"
    assert g2.group_id == "COED-6U-BEG-02"

    # Move heaviest wrestler from g1 into g2
    w_to_move = g1.wrestlers[-1]
    move_wrestler(
        reloaded,
        wrestler_id=w_to_move.id,
        from_group_id=g1.group_id,
        to_group_id=g2.group_id,
        base_dir=base_dir,
    )
    assert g1.size == 3
    assert g2.size == 4
    assert g1.locked and g2.locked

    # Swap wrestlers between g1 and g2
    wa_id = g1.wrestlers[0].id
    wb_id = g2.wrestlers[0].id
    swap_wrestlers(reloaded, g1.group_id, wa_id, g2.group_id, wb_id, base_dir=base_dir)
    assert any(w.id == wb_id for w in g1.wrestlers)
    assert any(w.id == wa_id for w in g2.wrestlers)

    # Update a wrestler's weight, skill level, age group, and division
    update_wrestler_in_bracket(
        reloaded,
        g1.group_id,
        wb_id,
        weight=40.5,
        skill_level="Advanced",
        age_group="8U",
        division="Girls",
        base_dir=base_dir,
    )
    assert any(
        w.id == wb_id
        and w.weight == 40.5
        and w.skill_level == "Advanced"
        and w.age_group == "8U"
        and w.division == "Girls"
        for w in g1.wrestlers
    )
    assert "skill: Beginner -> Advanced" in reloaded.history[0]
    assert "age: 6U -> 8U" in reloaded.history[0]
    assert "division: Coed -> Girls" in reloaded.history[0]

    # Merge solo Advanced bracket COED-6U-ADV-01 into COED-6U-BEG-02
    adv_group = next(g for g in reloaded.result.groups if g.skill_level == "Advanced")
    merge_brackets(reloaded, adv_group.group_id, g2.group_id, base_dir=base_dir)
    assert len(reloaded.result.groups) == 2


def test_regenerate_specific_brackets_by_ids_and_preserve_locked(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Regen Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    # Regenerate COED-6U-BEG-01 and COED-6U-BEG-02 with max_group_size=3 (7 wrestlers -> 3, 2, 2)
    regenerate_brackets_by_ids(
        t,
        group_ids=["COED-6U-BEG-01", "COED-6U-BEG-02"],
        target_group_size=3,
        max_group_size=3,
        base_dir=base_dir,
    )
    beg_groups = [g for g in t.result.groups if g.skill_level == "Beginner"]
    assert len(beg_groups) == 3
    assert sorted(g.size for g in beg_groups) == [2, 2, 3]

    # Lock the first bracket and run import with mode="preserve_locked"
    beg_groups[0].locked = True
    locked_wrestler_names = {w.name for w in beg_groups[0].wrestlers}
    import_spreadsheet_to_tournament(t, xlsx_path, mode="preserve_locked", base_dir=base_dir)
    preserved = [g for g in t.result.groups if g.locked]
    assert len(preserved) == 1
    assert {w.name for w in preserved[0].wrestlers} == locked_wrestler_names


def test_walkin_and_scratch_wrestler(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Walkin Scratch Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    initial_count = len(t.result.wrestlers)

    # 1. Add walk-in wrestler with AUTO placement
    _, walkin_w, placed_gid = add_walkin_wrestler(
        t,
        name="Walkin Kid",
        weight=41.5,
        team="Club X",
        division="Coed",
        age_group="6U",
        skill_level="Beginner",
        target_group_id="AUTO",
        base_dir=base_dir,
    )
    assert len(t.result.wrestlers) == initial_count + 1
    assert placed_gid == "COED-6U-BEG-02"
    g2 = next(g for g in t.result.groups if g.group_id == placed_gid)
    assert any(w.name == "Walkin Kid" for w in g2.wrestlers)

    # 2. Scratch a wrestler who didn't show up
    w_to_scratch = g2.wrestlers[0]
    scratch_wrestler(t, w_to_scratch.id, group_id=g2.group_id, base_dir=base_dir)
    assert not any(w.id == w_to_scratch.id for w in g2.wrestlers)
    assert len(t.scratched_wrestlers) == 1
    assert t.scratched_wrestlers[0]["name"] == w_to_scratch.name

    # 3. Restore the scratched wrestler
    restore_scratched_wrestler(t, scratch_index=0, target_group_id="AUTO", base_dir=base_dir)
    assert len(t.scratched_wrestlers) == 0
    assert any(w.id == w_to_scratch.id for w in g2.wrestlers)


def test_reoptimize_active_brackets(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Reoptimize Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    # Add a walk-in to 6U BEG
    add_walkin_wrestler(
        t,
        name="Walkin Newcomer",
        weight=42.5,
        team="Mat Club",
        division="Coed",
        age_group="6U",
        skill_level="Beginner",
        base_dir=base_dir,
    )
    # Scratch one original wrestler
    orig_w = t.result.groups[0].wrestlers[0]
    scratch_wrestler(t, orig_w.id, base_dir=base_dir)

    # Re-optimize 6U brackets
    t, orig_cnt, new_cnt = reoptimize_active_brackets(
        t,
        division="Coed",
        age_group="6U",
        preserve_locked=True,
        base_dir=base_dir,
    )

    reloaded = load_tournament(t.slug, base_dir=base_dir)
    all_active_names = [w.name for g in reloaded.result.groups for w in g.wrestlers]
    assert "Walkin Newcomer" in all_active_names
    assert orig_w.name not in all_active_names

    # Check 6U beginner groups sizes are balanced
    beg_groups = [g for g in reloaded.result.groups if g.age_group == "6U" and g.skill_level == "Beginner"]
    for g in beg_groups:
        assert 2 <= g.size <= 4
        assert len(g.bouts) > 0


def test_search_tournament_wrestlers(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Search Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    # Search active wrestler by name
    res = search_tournament_wrestlers(t, query="Wrestler A")
    assert len(res) == 1
    assert res[0]["status"] == "Active"
    assert res[0]["wrestler"].name == "Wrestler A"
    assert res[0]["group_id"] == "COED-6U-BEG-01"
    assert res[0]["seed"] == 1
    assert len(res[0]["bouts"]) == 3

    # Scratch Wrestler B and search scratched status
    w_b = next(w for w in t.result.wrestlers if w.name == "Wrestler B")
    scratch_wrestler(t, w_b.id, reason="Illness", base_dir=base_dir)

    sc_res = search_tournament_wrestlers(t, status="Scratched")
    assert len(sc_res) == 1
    assert sc_res[0]["status"] == "Scratched"
    assert sc_res[0]["wrestler"].name == "Wrestler B"
    assert sc_res[0]["scratch_record"]["reason"] == "Illness"

    # Search by reason keyword across all
    by_reason = search_tournament_wrestlers(t, query="Illness", status="All")
    assert len(by_reason) == 1
    assert by_reason[0]["wrestler"].name == "Wrestler B"

    # Filter by Flagged brackets (solo Advanced wrestler Wrestler H)
    flagged_res = search_tournament_wrestlers(t, status="Flagged")
    assert any(r["wrestler"].name == "Wrestler H" for r in flagged_res)


def test_mat_assignment_and_lookup_by_mat(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Mat Test", base_dir=base_dir)
    t.config.mat_count = 3
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    # All generated groups should be auto-assigned a mat between 1 and 3
    assert all(g.mat_number in (1, 2, 3) for g in t.result.groups)

    # Manually assign COED-6U-BEG-01 to Mat 2
    set_bracket_mat(t, ["COED-6U-BEG-01"], mat_number=2, base_dir=base_dir)
    g1 = next(g for g in t.result.groups if g.group_id == "COED-6U-BEG-01")
    assert g1.mat_number == 2
    assert g1.mat_label == "Mat 2"

    # Search wrestlers by mat filter and by query "Mat 2"
    mat2_res = search_tournament_wrestlers(t, mat_number="Mat 2")
    assert any(r["wrestler"].name == "Wrestler A" for r in mat2_res)
    assert all(r["mat_number"] == 2 for r in mat2_res)

    query_mat2 = search_tournament_wrestlers(t, query="mat 2")
    assert any(r["wrestler"].name == "Wrestler A" for r in query_mat2)

    # Rebalance across 2 mats using round_robin strategy
    assign_brackets_to_mats(t, mat_count=2, strategy="round_robin", preserve_locked=False, base_dir=base_dir)
    reloaded = load_tournament(t.slug, base_dir=base_dir)
    assert reloaded.config.mat_count == 2
    assert all(g.mat_number in (1, 2) for g in reloaded.result.groups)

    # Pin COED-6U-BEG-01 to Mat 2 and verify sticky mat preservation across walk-ins, scratches, and regeneration
    set_bracket_mat(reloaded, ["COED-6U-BEG-01"], mat_number=2, lock_bracket=True, base_dir=base_dir)
    g1 = next(g for g in reloaded.result.groups if g.group_id == "COED-6U-BEG-01")
    assert g1.mat_number == 2
    assert g1.locked is True

    # 1. Walk-in placed into existing bracket preserves mat_number == 2
    reloaded, _, _ = add_walkin_wrestler(
        reloaded,
        name="Walkin SameMat",
        weight=41.5,
        age_group="6U",
        skill_level="Beginner",
        team="Alpha",
        division="Coed",
        target_group_id="COED-6U-BEG-01",
        base_dir=base_dir,
    )
    g1 = next(g for g in reloaded.result.groups if g.group_id == "COED-6U-BEG-01")
    assert g1.mat_number == 2

    # 2. Walk-in spun off into __NEW__ bracket inherits closest-weight mat in same (division, age_group)
    reloaded, _, new_gid = add_walkin_wrestler(
        reloaded,
        name="Walkin NewPod",
        weight=42.5,
        age_group="6U",
        skill_level="Beginner",
        team="Beta",
        division="Coed",
        target_group_id="__NEW__",
        base_dir=base_dir,
    )
    g_new = next(g for g in reloaded.result.groups if g.group_id == new_gid)
    assert g_new.mat_number == 2

    # 3. Scratching and restoring a wrestler preserves mat_number == 2
    walkin_w = next(w for w in g1.wrestlers if w.name == "Walkin SameMat")
    reloaded, _ = scratch_wrestler(
        reloaded,
        wrestler_id=walkin_w.id,
        group_id="COED-6U-BEG-01",
        reason="No-show",
        base_dir=base_dir,
    )
    g1 = next(g for g in reloaded.result.groups if g.group_id == "COED-6U-BEG-01")
    assert g1.mat_number == 2
    reloaded, _ = restore_scratched_wrestler(reloaded, scratch_index=0, base_dir=base_dir)
    g1 = next(g for g in reloaded.result.groups if g.group_id == "COED-6U-BEG-01")
    assert g1.mat_number == 2

    # 4. Targeted regeneration (regenerate_brackets_by_ids) inherits mat_number == 2
    regenerate_brackets_by_ids(
        reloaded, group_ids=["COED-6U-BEG-01", new_gid], base_dir=base_dir
    )
    g1_after = next(g for g in reloaded.result.groups if g.group_id == "COED-6U-BEG-01")
    assert g1_after.mat_number == 2

    # 5. Scope-wide re-optimization preserves prior mat assignments even when unlocked
    for g in reloaded.result.groups:
        g.locked = False
    prior_mats = {w.name: g.mat_number for g in reloaded.result.groups for w in g.wrestlers}
    reloaded, _, _ = reoptimize_active_brackets(reloaded, preserve_locked=False, base_dir=base_dir)
    for g in reloaded.result.groups:
        assert g.mat_number in (1, 2)
        if any(w.name == "Wrestler A" for w in g.wrestlers):
            assert g.mat_number == prior_mats["Wrestler A"]

    # 6. Multi-bucket 6-mat balancing spreads remainder chunks to least-loaded mats (no Mat 1 bias)
    multi_rows = [["Weight", "Wrestlers Name", "Age Group", "School", "Ability", "Boys / COED Bracket", "Girls only Bracket"]]
    for age in ["6U", "8U", "10U", "12U"]:
        for i in range(12):  # 3 brackets of 4 per age group -> 12 brackets total across 4 age groups
            multi_rows.append([40.0 + i * 0.5, f"Kid {age}_{i}", age, f"Club_{i % 4}", "Beginner", "X", ""])
    xlsx6_path = tmp_path / "six_mat_rosters.xlsx"
    write_xlsx_sheets(xlsx6_path, [("Roster", multi_rows)])

    t6 = create_tournament("Six Mat Balance Test", base_dir=base_dir)
    t6.config.mat_count = 6
    import_spreadsheet_to_tournament(t6, xlsx6_path, mode="full_overwrite", base_dir=base_dir)

    mat_counts_balanced = {m: sum(1 for g in t6.result.groups if g.mat_number == m) for m in range(1, 7)}
    # 16 brackets across 6 mats (4 brackets per age group) must spread across all 6 mats (2-3 per mat, never 0 on Mats 5/6)
    assert mat_counts_balanced == {1: 3, 2: 3, 3: 3, 4: 3, 5: 2, 6: 2}

    # Verify contiguous_blocks strategy also partitions evenly across all 6 mats (2-4 brackets / equal bout load per mat)
    assign_brackets_to_mats(t6, mat_count=6, strategy="contiguous_blocks", preserve_locked=False, base_dir=base_dir)
    mat_counts_contig = {m: sum(1 for g in t6.result.groups if g.mat_number == m) for m in range(1, 7)}
    assert all(2 <= c <= 4 for c in mat_counts_contig.values())
    assert sum(mat_counts_contig.values()) == len(t6.result.groups)

    # Verify equal_age_group strategy sends equal brackets per age group across mats and strictly equalizes total bracket counts
    assign_brackets_to_mats(t6, mat_count=4, strategy="equal_age_group", preserve_locked=False, base_dir=base_dir)
    for age in ["6U", "8U", "10U", "12U"]:
        per_mat_for_age = [
            sum(1 for g in t6.result.groups if g.age_group == age and g.mat_number == m)
            for m in range(1, 5)
        ]
        # Within every single age group, the difference between any two mats is at most 1 bracket
        assert max(per_mat_for_age) - min(per_mat_for_age) <= 1
    total_per_mat_4 = [sum(1 for g in t6.result.groups if g.mat_number == m) for m in range(1, 5)]
    assert max(total_per_mat_4) - min(total_per_mat_4) <= 1

    # 7. Verify coed_by_age_girls_together balances all Girls brackets as one pool across mats + Coed by age group
    for age_idx, age in enumerate(["6U", "8U", "10U", "12U"]):
        for j in range(3):
            multi_rows.append([42.0 + j * 0.5, f"Girl {age}_{j}", age, f"Club_{j}", "Beginner", "", "X"])
    write_xlsx_sheets(xlsx6_path, [("Roster", multi_rows)])
    import_spreadsheet_to_tournament(t6, xlsx6_path, mode="full_overwrite", base_dir=base_dir)
    assign_brackets_to_mats(t6, mat_count=4, strategy="coed_by_age_girls_together", preserve_locked=False, base_dir=base_dir)
    girls_per_mat = [
        sum(1 for g in t6.result.groups if g.division == "Girls" and g.mat_number == m)
        for m in range(1, 5)
    ]
    # 4 Girls brackets across 4 mats -> every mat gets exactly 1 Girls bracket!
    assert girls_per_mat == [1, 1, 1, 1]
    for age in ["6U", "8U", "10U", "12U"]:
        coed_per_mat = [
            sum(1 for g in t6.result.groups if g.division == "Coed" and g.age_group == age and g.mat_number == m)
            for m in range(1, 5)
        ]
        assert max(coed_per_mat) - min(coed_per_mat) <= 1


def test_enforce_max_one_bracket_per_division(tmp_path: Path):
    base_dir = tmp_path / "tournaments"
    rows = [
        ["Weight", "Wrestlers Name", "Age Group", "School", "Ability", "Boys / COED Bracket", "Girls only Bracket"],
        [50.0, "Light A", "8U", "Alpha", "Advanced", "X", ""],
        [51.0, "Light B", "8U", "Beta", "Advanced", "X", ""],
        [75.0, "Dom C", "8U", "Alpha", "Advanced", "X", ""],
        [77.6, "Kai M", "8U", "Columbine", "Advanced", "X", "X"],
        [71.2, "Lilly L", "10U", "Delta", "Advanced", "", "X"],
        [77.8, "Dulcie S", "10U", "Epsilon", "Advanced", "", "X"],
    ]
    xlsx_path = tmp_path / "dual_test.xlsx"
    write_xlsx_sheets(xlsx_path, [("Columbine", rows)])

    t = create_tournament("Dual Uniqueness Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    # Kai M has a solo 8U Girls bracket and an active 8U Coed bracket.
    # Attempting to merge Kai M's Girls bracket into another Coed bracket must raise ValueError!
    kai_girls_grp = next(g for g in t.result.groups if g.division == "Girls" and any(w.name == "Kai M" for w in g.wrestlers))
    other_coed_grp = next(g for g in t.result.groups if g.division == "Coed" and all(w.name != "Kai M" for w in g.wrestlers))
    with pytest.raises(ValueError, match="at most 1 Coed and 1 Girls"):
        merge_brackets(t, kai_girls_grp.group_id, other_coed_grp.group_id, base_dir=base_dir)

    # Simulate a legacy tournament state where Kai M's Girls entry was manually placed in other_coed_grp
    kai_girls_w = kai_girls_grp.wrestlers[0]
    other_coed_grp.wrestlers.append(kai_girls_w)
    t.result.groups = [g for g in t.result.groups if g.group_id != kai_girls_grp.group_id]

    dups = find_duplicate_division_entries(t)
    assert len(dups) == 1
    assert dups[0]["name"] == "Kai M"

    # Running enforce_max_one_bracket_per_division re-homes Kai M's Girls entry into GIRL-10U-ADV-01
    t, actions = enforce_max_one_bracket_per_division(t, base_dir=base_dir)
    assert len(actions) == 1
    assert find_duplicate_division_entries(t) == []
    coed_kais = [g.group_id for g in t.result.groups if g.division == "Coed" and any(w.name == "Kai M" for w in g.wrestlers)]
    girls_kais = [g.group_id for g in t.result.groups if g.division == "Girls" and any(w.name == "Kai M" for w in g.wrestlers)]
    assert len(coed_kais) == 1
    assert len(girls_kais) == 1

    # Now test a heavy dual-entry girl (e.g. Kenlea M at 93.1 lbs) who has NO compatible Girls bracket within weight range:
    from bracketman.exporters.html import export_printable_roster_html
    from bracketman.models import Wrestler
    kenlea_coed = Wrestler(
        id="W9001", name="Kenlea M", weight=93.1, age_group="10U", team="Columbine", team_tab="Columbine",
        skill_level="Advanced", division="Coed", is_dual_entry=True,
    )
    kenlea_girls = Wrestler(
        id="W9002", name="Kenlea M", weight=93.1, age_group="10U", team="Columbine", team_tab="Columbine",
        skill_level="Advanced", division="Girls", is_dual_entry=True,
    )
    t.result.groups[0].wrestlers.append(kenlea_coed)
    t.result.groups[1].wrestlers.append(kenlea_girls)
    t.result.wrestlers.extend([kenlea_coed, kenlea_girls])

    t, actions2 = enforce_max_one_bracket_per_division(t, base_dir=base_dir)
    assert any("NO MATCH" in a for a in actions2)

    kenlea_matches = search_tournament_wrestlers(t, query="Kenlea M")
    statuses = {m["wrestler"].division: (m["status"], m["group_id"]) for m in kenlea_matches}
    assert statuses["Coed"][0] == "Active"
    assert statuses["Girls"] == ("No Match", "NO MATCH")

    # Ensure she does NOT show up when filtering for Scratched, and DOES show up under No Match
    assert search_tournament_wrestlers(t, query="Kenlea M", status="Scratched") == []
    no_match_res = search_tournament_wrestlers(t, query="Kenlea M", status="No Match")
    assert len(no_match_res) == 1
    assert no_match_res[0]["group_id"] == "NO MATCH"

    # Ensure printable roster HTML shows NO MATCH in the main table and does NOT list her under Scratched
    roster_html = export_printable_roster_html(
        t.result,
        tmp_path / "roster_nomatch.html",
        tournament_name=t.name,
        scratched_wrestlers=t.scratched_wrestlers,
    ).read_text(encoding="utf-8")
    assert "NO MATCH" in roster_html
    assert "SCRATCHED / NO-SHOW WRESTLERS" not in roster_html


def test_verify_tournament_roster_and_brackets(tmp_path: Path):
    from bracketman.models import Wrestler
    from bracketman.store import verify_tournament_roster_and_brackets
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Verify Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)

    v1 = verify_tournament_roster_and_brackets(t)
    assert v1["total_active_wrestlers"] == len(t.result.wrestlers)
    assert len(v1["dup_div_entries"]) == 0
    assert len(v1["unbracketed_wrestlers"]) == 0

    # Add an unbracketed wrestler to result.wrestlers
    orphan = Wrestler(
        id="W_ORPHAN", name="Orphan Wrestler", weight=50.0, age_group="8U",
        skill_level="Beginner", team="Club X", team_tab="Club X", division="Coed",
    )
    t.result.wrestlers.append(orphan)
    v2 = verify_tournament_roster_and_brackets(t)
    assert len(v2["unbracketed_wrestlers"]) == 1
    assert v2["unbracketed_wrestlers"][0].name == "Orphan Wrestler"
    assert v2["all_clear"] is False

    # Add a NO MATCH record to scratched_wrestlers
    t.scratched_wrestlers.append({
        "id": "W_NM", "name": "NoMatch Wrestler", "weight": 60.0,
        "entry_status": "no_match", "reason": "No opponent in weight range",
    })
    v3 = verify_tournament_roster_and_brackets(t)
    assert len(v3["no_match_entries"]) == 1
    assert v3["no_match_entries"][0]["name"] == "NoMatch Wrestler"


def test_merge_multiple_brackets_three_into_one(tmp_path: Path):
    from bracketman.store import merge_multiple_brackets
    base_dir = tmp_path / "tournaments"
    xlsx_path = _create_sample_xlsx(tmp_path / "rosters.xlsx")

    t = create_tournament("Multi Merge Test", base_dir=base_dir)
    import_spreadsheet_to_tournament(t, xlsx_path, mode="full_overwrite", base_dir=base_dir)
    # Sample xlsx creates 3 groups: COED-6U-BEG-01 (4), COED-6U-BEG-02 (3), COED-6U-ADV-01 (1)
    assert len(t.result.groups) == 3
    gids = [g.group_id for g in t.result.groups]
    total_wrestlers = sum(g.size for g in t.result.groups)

    merge_multiple_brackets(t, [gids[1], gids[2]], gids[0], base_dir=base_dir)
    assert len(t.result.groups) == 1
    assert t.result.groups[0].group_id == gids[0]
    assert t.result.groups[0].size == total_wrestlers
    assert t.result.groups[0].locked is True









