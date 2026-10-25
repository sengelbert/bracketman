"""Tests for tournament persistence, manual bracket tweaking, and targeted regeneration by ID."""

from pathlib import Path

from bracketman.io.xlsx import write_xlsx_sheets
from bracketman.store import (
    add_walkin_wrestler,
    create_tournament,
    import_spreadsheet_to_tournament,
    load_tournament,
    merge_brackets,
    move_wrestler,
    regenerate_brackets_by_ids,
    reoptimize_active_brackets,
    restore_scratched_wrestler,
    scratch_wrestler,
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

    # Update a wrestler's weight
    update_wrestler_in_bracket(
        reloaded, g1.group_id, wb_id, weight=40.5, base_dir=base_dir
    )
    assert any(w.id == wb_id and w.weight == 40.5 for w in g1.wrestlers)

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

