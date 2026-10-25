"""Terminal report formatter for Bracketman."""

from __future__ import annotations

from collections import Counter

from bracketman.models import BracketGroup, TournamentResult


def format_summary_report(result: TournamentResult, show_rosters: bool = False) -> str:
    """Format a human-readable summary of loaded rosters, formed groups, and flags."""
    lines: list[str] = []
    unique_tabs = sorted({w.team_tab for w in result.wrestlers if w.team_tab})
    dual_entries = sum(1 for w in result.wrestlers if w.is_dual_entry) // 2

    lines.append("=" * 88)
    lines.append(f"BRACKETMAN TOURNAMENT SUMMARY")
    lines.append("=" * 88)
    lines.append(f"Source             : {result.source}")
    lines.append(f"Teams / Tabs ({len(unique_tabs):2d})  : {', '.join(unique_tabs)}")
    lines.append(f"Total Entries      : {len(result.wrestlers)} (including {dual_entries} dual Coed+Girls entries)")
    lines.append(f"Total Groups Built : {len(result.groups)}")
    lines.append(f"Total Bouts        : {sum(len(g.bouts) for g in result.groups)}")

    size_counts = Counter(g.size for g in result.groups)
    size_summary = ", ".join(f"{sz}-man: {cnt}" for sz, cnt in sorted(size_counts.items()))
    lines.append(f"Group Size Dist.   : {size_summary}")
    lines.append("")

    # Breakdown by (Division, Age Group, Skill Level)
    lines.append("DIVISION / AGE GROUP / SKILL BREAKDOWN")
    lines.append("-" * 88)
    header = (
        f"{'Division':<8} | {'Age':<5} | {'Skill':<10} | {'Wrestlers':>9} | "
        f"{'Groups':>6} | {'Weight Range':<16} | {'Avg Spread':>10} | {'Flags':>5}"
    )
    lines.append(header)
    lines.append("-" * 88)

    buckets: dict[tuple[str, str, str], list[BracketGroup]] = {}
    for g in result.groups:
        key = (g.division, g.age_group, g.skill_level)
        buckets.setdefault(key, []).append(g)

    for (div, age, skill), grps in buckets.items():
        w_count = sum(g.size for g in grps)
        min_w = min(g.min_weight for g in grps)
        max_w = max(g.max_weight for g in grps)
        multi_grps = [g for g in grps if g.size > 1]
        avg_spread = (
            sum(g.weight_spread_pct for g in multi_grps) / len(multi_grps)
            if multi_grps
            else 0.0
        )
        flag_cnt = sum(1 for g in grps if g.has_warnings)
        w_range = f"{min_w:g}–{max_w:g} lbs"
        lines.append(
            f"{div:<8} | {age:<5} | {skill:<10} | {w_count:>9} | "
            f"{len(grps):>6} | {w_range:<16} | {avg_spread:>9.1f}% | {flag_cnt:>5}"
        )

    lines.append("-" * 88)
    lines.append("")

    # Group Table
    lines.append("GENERATED BRACKET GROUPS")
    lines.append("-" * 96)
    g_header = (
        f"{'Group ID':<16} | {'Size':>4} | {'Weights':<14} | {'Actual Spread':>14} | "
        f"{'Max Allowed':>15} | {'Teams'}"
    )
    lines.append(g_header)
    lines.append("-" * 96)

    for g in result.groups:
        spread_str = f"{g.weight_spread_lbs:g}lb ({g.weight_spread_pct:.1f}%)" if g.size > 1 else "Solo"
        allowed_str = f"<= {g.allowed_spread_lbs:g}lb ({g.allowed_spread_pct:.0f}%)"
        teams_str = ", ".join(f"{w.team}" for w in g.wrestlers)
        warn_marker = " [!]" if g.has_warnings else ""
        lines.append(
            f"{g.group_id:<16} | {g.size:>4} | {g.weight_label:<14} | {spread_str:>14} | "
            f"{allowed_str:>15} | {teams_str}{warn_marker}"
        )
        if show_rosters:
            for idx, w in enumerate(g.wrestlers, start=1):
                dual_tag = " [Dual]" if w.is_dual_entry else ""
                lines.append(
                    f"    {idx}. {w.name:<24} {w.weight:>6.1f} lbs   {w.display_team:<22}{dual_tag}"
                )

    lines.append("-" * 96)

    # Warnings / Action Items
    warn_groups = [g for g in result.groups if g.flags]
    if warn_groups:
        lines.append("")
        lines.append("FLAGS & DIRECTOR RECOMMENDATIONS")
        lines.append("-" * 88)
        for g in warn_groups:
            for fl in g.flags:
                prefix = "WARN" if fl.severity == "warning" else "INFO"
                lines.append(f"[{prefix}] {g.group_id}: {fl.message}")
                if fl.suggestion:
                    lines.append(f"       -> Recommendation: {fl.suggestion}")

    if result.skipped_rows:
        lines.append("")
        lines.append(f"SKIPPED SHEET ROWS ({len(result.skipped_rows)})")
        lines.append("-" * 88)
        for sr in result.skipped_rows[:15]:
            lines.append(f"  - Tab '{sr.get('sheet')}' Row {sr.get('row')}: {sr.get('reason')}")

    return "\n".join(lines)
