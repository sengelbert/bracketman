"""CSV and multi-tab .xlsx workbook exporters for Bracketman."""

from __future__ import annotations

import csv
from pathlib import Path

from bracketman.io.xlsx import write_xlsx_sheets
from bracketman.models import BracketGroup, TournamentResult


def export_csv_files(result: TournamentResult, output_dir: str | Path) -> dict[str, Path]:
    """Write groups_summary.csv, brackets_rosters.csv, and bouts_schedule.csv."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "groups_summary.csv"
    rosters_path = out_dir / "brackets_rosters.csv"
    bouts_path = out_dir / "bouts_schedule.csv"

    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Group ID",
                "Division",
                "Age Group",
                "Skill Level",
                "Size",
                "Min Weight",
                "Max Weight",
                "Spread (lbs)",
                "Spread (%)",
                "Bracket Format",
                "Bout Count",
                "Flags",
                "Suggestions",
            ]
        )
        for g in result.groups:
            flags_str = "; ".join(f"{fl.code}: {fl.message}" for fl in g.flags)
            sugg_str = "; ".join(fl.suggestion for fl in g.flags if fl.suggestion)
            writer.writerow(
                [
                    g.group_id,
                    g.division,
                    g.age_group,
                    g.skill_level,
                    g.size,
                    g.min_weight,
                    g.max_weight,
                    g.weight_spread_lbs,
                    g.weight_spread_pct,
                    g.bracket_format,
                    len(g.bouts),
                    flags_str,
                    sugg_str,
                ]
            )

    with open(rosters_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Group ID",
                "Seed",
                "Wrestler ID",
                "Wrestler Name",
                "Weight (lbs)",
                "Team / School",
                "Source Tab",
                "Division",
                "Age Group",
                "Skill Level",
                "Age",
                "Dual Entry",
            ]
        )
        for g in result.groups:
            for seed, w in enumerate(g.wrestlers, start=1):
                writer.writerow(
                    [
                        g.group_id,
                        seed,
                        w.id,
                        w.name,
                        w.weight,
                        w.team,
                        w.team_tab,
                        g.division,
                        g.age_group,
                        g.skill_level,
                        w.age if w.age is not None else "",
                        "Yes" if w.is_dual_entry else "No",
                    ]
                )

    with open(bouts_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Group ID",
                "Division",
                "Age Group",
                "Skill Level",
                "Bout #",
                "Round #",
                "Wrestler A",
                "Team A",
                "Weight A",
                "Wrestler B",
                "Team B",
                "Weight B",
                "Teammate Match",
            ]
        )
        for g in result.groups:
            for b in g.bouts:
                wb_name = b.wrestler_b.name if b.wrestler_b else "BYE"
                wb_team = b.wrestler_b.team if b.wrestler_b else ""
                wb_wt = b.wrestler_b.weight if b.wrestler_b else ""
                writer.writerow(
                    [
                        g.group_id,
                        g.division,
                        g.age_group,
                        g.skill_level,
                        b.bout_number,
                        b.round_number,
                        b.wrestler_a.name,
                        b.wrestler_a.team,
                        b.wrestler_a.weight,
                        wb_name,
                        wb_team,
                        wb_wt,
                        "Yes" if b.is_teammate_match else "No",
                    ]
                )

    return {
        "summary_csv": summary_path,
        "rosters_csv": rosters_path,
        "bouts_csv": bouts_path,
    }


def export_xlsx_workbook(result: TournamentResult, output_path: str | Path) -> Path:
    """Write a multi-tab .xlsx workbook with Summary, Flags, and per-Division/Age tabs."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sheets: list[tuple[str, list[list[object]]]] = []

    # 1. Summary Tab
    summary_rows: list[list[object]] = [
        [
            "Group ID",
            "Division",
            "Age Group",
            "Skill Level",
            "Size",
            "Weight Range",
            "Spread (lbs)",
            "Spread (%)",
            "Format",
            "Bouts",
            "Wrestlers",
            "Flags",
        ]
    ]
    for g in result.groups:
        w_names = ", ".join(f"{w.name} ({w.team}, {w.weight:g})" for w in g.wrestlers)
        flags_str = "; ".join(f"{fl.code}" for fl in g.flags)
        summary_rows.append(
            [
                g.group_id,
                g.division,
                g.age_group,
                g.skill_level,
                g.size,
                g.weight_label,
                g.weight_spread_lbs,
                g.weight_spread_pct,
                g.bracket_format,
                len(g.bouts),
                w_names,
                flags_str,
            ]
        )
    sheets.append(("Summary", summary_rows))

    # 2. Flags & Recommendations Tab
    flag_rows: list[list[object]] = [
        ["Group ID", "Division", "Age Group", "Skill Level", "Severity", "Code", "Message", "Recommendation"]
    ]
    for g in result.groups:
        for fl in g.flags:
            flag_rows.append(
                [
                    g.group_id,
                    g.division,
                    g.age_group,
                    g.skill_level,
                    fl.severity.upper(),
                    fl.code,
                    fl.message,
                    fl.suggestion or "",
                ]
            )
    sheets.append(("Flags_&_Alerts", flag_rows))

    # 3. Per-(Division, Age Group) Tabs
    div_age_buckets: dict[str, list[BracketGroup]] = {}
    for g in result.groups:
        tab_key = f"{g.division}_{g.age_group}"
        div_age_buckets.setdefault(tab_key, []).append(g)

    for tab_name, grps in div_age_buckets.items():
        rows: list[list[object]] = []
        for g in grps:
            flag_note = f" [{' | '.join(fl.code for fl in g.flags)}]" if g.flags else ""
            rows.append(
                [
                    f"=== {g.group_id} ===",
                    f"{g.division} {g.age_group} {g.skill_level}",
                    f"Weights: {g.weight_label}",
                    f"Spread: {g.weight_spread_lbs:g} lbs ({g.weight_spread_pct:.1f}%)",
                    f"Format: {g.bracket_format}{flag_note}",
                ]
            )
            rows.append(["Seed", "Wrestler Name", "Weight (lbs)", "School / Code", "Club Tab", "Age", "Notes"])
            for idx, w in enumerate(g.wrestlers, start=1):
                note = "Dual Entry (Coed+Girls)" if w.is_dual_entry else ""
                rows.append([idx, w.name, w.weight, w.team, w.team_tab, w.age or "", note])
            rows.append([])  # Blank separator row between groups

        sheets.append((tab_name, rows))

    write_xlsx_sheets(out_path, sheets)
    return out_path
