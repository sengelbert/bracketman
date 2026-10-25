"""Madison system dynamic weight grouping, teammate separation, and straggler handling."""

from __future__ import annotations

from collections import defaultdict
import math

from bracketman.config import TournamentConfig
from bracketman.grouping.bouts import generate_bouts_for_group, resolve_bracket_format
from bracketman.models import BracketGroup, GroupFlag, GroupRuleConfig, TournamentResult, Wrestler


def _calc_spread_pct(min_w: float, max_w: float) -> float:
    if min_w <= 0 or max_w <= min_w:
        return 0.0
    return ((max_w - min_w) / min_w) * 100.0


def _count_teammate_pairs(wrestlers: list[Wrestler]) -> int:
    counts: dict[str, int] = defaultdict(int)
    for w in wrestlers:
        if w.team_key:
            counts[w.team_key] += 1
    return sum(c * (c - 1) // 2 for c in counts.values() if c > 1)


def _slice_cost(wrestlers: list[Wrestler], rule: GroupRuleConfig) -> float:
    """Compute penalty cost for forming a single group from `wrestlers`."""
    size = len(wrestlers)
    if size == 0:
        return 0.0

    # Solo wrestler penalty: high so we avoid 1-man brackets whenever a safe group is possible,
    # but finite so dangerous weight mismatches (e.g. >1.75x allowed spread) are not forced together.
    if size == 1:
        return 8000.0

    min_w = wrestlers[0].weight
    max_w = wrestlers[-1].weight
    for w in wrestlers:
        if w.weight < min_w:
            min_w = w.weight
        if w.weight > max_w:
            max_w = w.weight

    spread_lbs = max_w - min_w
    spread_pct = _calc_spread_pct(min_w, max_w)

    cost = 0.0

    # 1. Group size deviation cost
    size_diff = abs(size - rule.target_group_size)
    cost += (size_diff ** 2) * 30.0
    if size < rule.min_group_size:
        cost += (rule.min_group_size - size) * 350.0
    if size > rule.max_group_size:
        cost += (size - rule.max_group_size) * 5000.0

    # 2. Weight spread cost (pct and lbs), scaling progressively with min_w
    cost += spread_pct * 4.0 + spread_lbs * 1.5

    allowed_pct = rule.effective_max_spread_pct(min_w)
    if allowed_pct and spread_pct > allowed_pct:
        over_pct = spread_pct - allowed_pct
        if over_pct <= allowed_pct * 0.65:
            # Moderate overage penalty
            cost += 500.0 + (over_pct ** 2) * 45.0
        else:
            # Severe weight mismatch: worse than leaving a solo outlier
            cost += 18000.0 + (over_pct ** 2) * 200.0

    if rule.max_weight_spread_lbs is not None:
        allowed_lbs = rule.max_weight_spread_lbs
        if spread_lbs > allowed_lbs:
            over_lbs = spread_lbs - allowed_lbs
            if over_lbs <= allowed_lbs * 0.65:
                cost += 500.0 + (over_lbs ** 2) * 45.0
            else:
                cost += 18000.0 + (over_lbs ** 2) * 200.0

    # 3. Teammate collision penalty
    if rule.separate_teammates:
        cost += _count_teammate_pairs(wrestlers) * 45.0

    return cost


def partition_madison_dp(
    sorted_wrestlers: list[Wrestler],
    rule: GroupRuleConfig,
) -> list[list[Wrestler]]:
    """Optimally partition weight-sorted wrestlers into Madison groups using dynamic programming."""
    n = len(sorted_wrestlers)
    if n == 0:
        return []
    max_sz = max(1, rule.max_group_size)
    if n <= max_sz and _slice_cost(sorted_wrestlers, rule) < 8000.0:
        return [list(sorted_wrestlers)]

    dp = [math.inf] * (n + 1)
    prev = [0] * (n + 1)
    dp[0] = 0.0

    for i in range(1, n + 1):
        start_min = max(0, i - max_sz)
        for j in range(start_min, i):
            candidate = sorted_wrestlers[j:i]
            c = dp[j] + _slice_cost(candidate, rule)
            if c < dp[i]:
                dp[i] = c
                prev[i] = j

    groups: list[list[Wrestler]] = []
    curr = n
    while curr > 0:
        j = prev[curr]
        groups.append(list(sorted_wrestlers[j:curr]))
        curr = j
    groups.reverse()
    return groups


def optimize_adjacent_teammate_swaps(
    groups: list[list[Wrestler]],
    rule: GroupRuleConfig,
    max_swap_weight_diff_lbs: float = 2.5,
) -> list[list[Wrestler]]:
    """Swap boundary wrestlers between adjacent weight groups if it reduces teammate collisions
    without violating weight spread rules or exceeding `max_swap_weight_diff_lbs`.
    """
    if not rule.separate_teammates or len(groups) < 2:
        return groups

    improved = True
    passes = 0
    while improved and passes < 5:
        improved = False
        passes += 1
        for g_idx in range(len(groups) - 1):
            g_left = groups[g_idx]
            g_right = groups[g_idx + 1]
            if len(g_left) < 2 or len(g_right) < 2:
                continue

            current_pairs = _count_teammate_pairs(g_left) + _count_teammate_pairs(g_right)
            if current_pairs == 0:
                continue

            best_swap: tuple[int, int] | None = None
            best_cost_delta = 0.0
            current_cost = _slice_cost(g_left, rule) + _slice_cost(g_right, rule)

            # Consider swapping one of the heaviest 2 in g_left with one of the lightest 2 in g_right
            left_candidates = range(max(0, len(g_left) - 2), len(g_left))
            right_candidates = range(0, min(2, len(g_right)))

            for li in left_candidates:
                for ri in right_candidates:
                    w_l = g_left[li]
                    w_r = g_right[ri]
                    if abs(w_r.weight - w_l.weight) > max_swap_weight_diff_lbs:
                        continue

                    new_left = list(g_left)
                    new_right = list(g_right)
                    new_left[li] = w_r
                    new_right[ri] = w_l
                    new_left.sort(key=lambda w: (w.weight, w.team_key, w.name))
                    new_right.sort(key=lambda w: (w.weight, w.team_key, w.name))

                    new_pairs = _count_teammate_pairs(new_left) + _count_teammate_pairs(new_right)
                    if new_pairs >= current_pairs:
                        continue

                    new_cost = _slice_cost(new_left, rule) + _slice_cost(new_right, rule)
                    delta = new_cost - current_cost
                    if delta < best_cost_delta:
                        best_cost_delta = delta
                        best_swap = (li, ri)

            if best_swap is not None:
                li, ri = best_swap
                w_l = g_left[li]
                w_r = g_right[ri]
                g_left[li] = w_r
                g_right[ri] = w_l
                g_left.sort(key=lambda w: (w.weight, w.team_key, w.name))
                g_right.sort(key=lambda w: (w.weight, w.team_key, w.name))
                improved = True

    return groups


def group_fixed_classes(
    sorted_wrestlers: list[Wrestler],
    rule: GroupRuleConfig,
) -> list[tuple[str | None, list[Wrestler]]]:
    """Group wrestlers into predefined fixed weight classes, splitting oversized classes."""
    classes = sorted(rule.fixed_weight_classes or [])
    if not classes:
        return [(None, g) for g in partition_madison_dp(sorted_wrestlers, rule)]

    buckets: dict[str, list[Wrestler]] = defaultdict(list)
    for w in sorted_wrestlers:
        placed = False
        for limit in classes:
            if w.weight <= limit:
                buckets[f"{limit:g} lbs"].append(w)
                placed = True
                break
        if not placed:
            buckets[f"{classes[-1]:g}+ lbs (HWT)"].append(w)

    result: list[tuple[str | None, list[Wrestler]]] = []
    for label, members in buckets.items():
        if not members:
            continue
        if len(members) <= rule.max_group_size:
            result.append((label, members))
        else:
            sub_groups = partition_madison_dp(members, rule)
            for idx, sg in enumerate(sub_groups):
                sub_label = f"{label} ({chr(ord('A') + idx)})"
                result.append((sub_label, sg))
    return result


def evaluate_group_flags(group: BracketGroup) -> list[GroupFlag]:
    """Generate diagnostic flags for a group based on its rule constraints."""
    flags: list[GroupFlag] = list(group.flags)
    rule = group.rule

    if group.size == 1:
        w = group.wrestlers[0]
        flags.append(
            GroupFlag(
                code="SOLO_WRESTLER",
                message=(
                    f"Solo wrestler {w.name} ({w.weight:g} lbs, {w.team}) has no opponents "
                    f"in {group.division} {group.age_group} {group.skill_level}."
                ),
                severity="warning",
            )
        )
        return flags

    if group.size < rule.min_group_size:
        flags.append(
            GroupFlag(
                code="SMALL_GROUP",
                message=f"Group has {group.size} wrestlers (configured min is {rule.min_group_size}).",
                severity="info",
            )
        )

    allowed_pct = group.allowed_spread_pct
    if allowed_pct and group.weight_spread_pct > allowed_pct:
        flags.append(
            GroupFlag(
                code="WEIGHT_SPREAD_PCT_EXCEEDED",
                message=(
                    f"Weight spread {group.weight_spread_lbs:g} lbs / {group.weight_spread_pct:.1f}% "
                    f"({group.weight_label}) exceeds allowed {group.allowed_spread_lbs:g} lbs / {allowed_pct:.1f}%."
                ),
                severity="warning",
            )
        )

    if rule.max_weight_spread_lbs is not None and group.weight_spread_lbs > rule.max_weight_spread_lbs:
        flags.append(
            GroupFlag(
                code="WEIGHT_SPREAD_LBS_EXCEEDED",
                message=(
                    f"Weight spread {group.weight_spread_lbs:.1f} lbs ({group.weight_label}) "
                    f"exceeds hard cap {rule.max_weight_spread_lbs:.1f} lbs."
                ),
                severity="warning",
            )
        )

    if rule.separate_teammates and group.teammate_pairs_count > 0:
        dup_teams = [f"{t} (x{c})" for t, c in group.team_counts.items() if c > 1]
        flags.append(
            GroupFlag(
                code="TEAMMATE_CONFLICT",
                message=f"Contains teammates from same club: {', '.join(dup_teams)}.",
                severity="info",
            )
        )

    return flags


def _make_group_id(division: str, age_group: str, skill_level: str, index: int) -> str:
    div_prefix = division[:4].upper()
    skill_prefix = skill_level[:3].upper()
    return f"{div_prefix}-{age_group}-{skill_prefix}-{index:02d}"


def _find_best_merge_candidate(
    solo_group: BracketGroup,
    all_groups: list[BracketGroup],
    config: TournamentConfig,
) -> tuple[BracketGroup | None, str | None]:
    """Find the best existing group that a solo wrestler could merge into (same age/diff skill,
    adjacent age group, or Coed equivalent for Girls).
    """
    if solo_group.size != 1:
        return None, None
    w = solo_group.wrestlers[0]

    best_target: BracketGroup | None = None
    best_score = math.inf
    best_reason: str | None = None

    age_order = {ag: i for i, ag in enumerate(config.age_groups)}
    solo_age_idx = age_order.get(solo_group.age_group, -99)

    for candidate in all_groups:
        if candidate.group_id == solo_group.group_id or candidate.size == 0:
            continue
        if candidate.size >= candidate.rule.max_group_size:
            continue
        # Do not merge a dual-entry wrestler into a group that already contains the same person
        if any(
            cw.name.lower() == w.name.lower() and cw.team_key == w.team_key
            for cw in candidate.wrestlers
        ):
            continue

        # Classify relationship between solo_group and candidate
        same_div = candidate.division == solo_group.division
        same_age = candidate.age_group == solo_group.age_group
        same_skill = candidate.skill_level == solo_group.skill_level
        cand_age_idx = age_order.get(candidate.age_group, -99)
        adj_age = abs(cand_age_idx - solo_age_idx) == 1

        rel_penalty = 0.0
        rel_desc = ""
        if same_div and same_age and not same_skill:
            rel_penalty = 10.0
            rel_desc = f"adjacent skill ({candidate.skill_level})"
        elif same_div and adj_age and same_skill:
            rel_penalty = 35.0
            rel_desc = f"adjacent age group ({candidate.age_group} {candidate.skill_level})"
        elif same_div and adj_age and not same_skill:
            rel_penalty = 55.0
            rel_desc = f"adjacent age/skill ({candidate.age_group} {candidate.skill_level})"
        elif not same_div and same_age:
            rel_penalty = 40.0
            rel_desc = f"{candidate.division} division ({candidate.age_group} {candidate.skill_level})"
        else:
            continue

        new_min = min(candidate.min_weight, w.weight)
        new_max = max(candidate.max_weight, w.weight)
        new_spread_pct = _calc_spread_pct(new_min, new_max)
        new_spread_lbs = new_max - new_min

        max_pct = candidate.rule.effective_max_spread_pct(new_min) or 12.0
        if new_spread_pct > max_pct * 1.35:
            continue
        if (
            candidate.rule.max_weight_spread_lbs is not None
            and new_spread_lbs > candidate.rule.max_weight_spread_lbs * 1.35
        ):
            continue

        score = rel_penalty + new_spread_pct * 2.0 + abs((candidate.size + 1) - candidate.rule.target_group_size) * 5.0
        if score < best_score:
            best_score = score
            best_target = candidate
            best_reason = (
                f"Merge into {candidate.group_id} ({rel_desc}, {candidate.weight_label}, "
                f"size {candidate.size}->{candidate.size + 1}, new spread {new_spread_pct:.1f}%)"
            )

    return best_target, best_reason


def build_tournament_groups(
    wrestlers: list[Wrestler],
    config: TournamentConfig | None = None,
    source: str = "",
    skipped_rows: list[dict] | None = None,
) -> TournamentResult:
    """Group all loaded wrestlers into brackets according to `config`."""
    cfg = config or TournamentConfig()

    # Bucket wrestlers by (division, age_group, skill_level)
    buckets: dict[tuple[str, str, str], list[Wrestler]] = defaultdict(list)
    for w in wrestlers:
        buckets[(w.division, w.age_group, w.skill_level)].append(w)

    # Order keys canonically by config order
    div_order = {d: i for i, d in enumerate(cfg.divisions)}
    age_order = {a: i for i, a in enumerate(cfg.age_groups)}
    skill_order = {s: i for i, s in enumerate(cfg.skill_levels)}

    sorted_keys = sorted(
        buckets.keys(),
        key=lambda k: (
            div_order.get(k[0], 99),
            age_order.get(k[1], 99),
            skill_order.get(k[2], 99),
            k,
        ),
    )

    all_groups: list[BracketGroup] = []

    for div, age_grp, skill in sorted_keys:
        pool = list(buckets[(div, age_grp, skill)])
        pool.sort(key=lambda w: (w.weight, w.team_key, w.name))
        rule = cfg.resolve_rule(div, age_grp, skill)

        if rule.mode == "fixed_classes" and rule.fixed_weight_classes:
            labeled_slices = group_fixed_classes(pool, rule)
        else:
            raw_slices = partition_madison_dp(pool, rule)
            raw_slices = optimize_adjacent_teammate_swaps(raw_slices, rule)
            labeled_slices = [(None, s) for s in raw_slices]

        for idx, (fixed_label, slice_wrestlers) in enumerate(labeled_slices, start=1):
            gid = _make_group_id(div, age_grp, skill, idx)
            b_fmt = resolve_bracket_format(len(slice_wrestlers), rule.bracket_format)
            bouts = generate_bouts_for_group(slice_wrestlers, b_fmt)
            grp = BracketGroup(
                group_id=gid,
                division=div,
                age_group=age_grp,
                skill_level=skill,
                group_index=idx,
                wrestlers=slice_wrestlers,
                rule=rule,
                bracket_format=b_fmt,
                bouts=bouts,
                fixed_class_label=fixed_label,
            )
            all_groups.append(grp)

    # Optional auto-merge or recommendation for solo wrestlers
    merged_solo_ids: set[str] = set()
    for grp in list(all_groups):
        if grp.group_id in merged_solo_ids or grp.size != 1:
            continue
        active_groups = [g for g in all_groups if g.group_id not in merged_solo_ids]
        target, suggestion = _find_best_merge_candidate(grp, active_groups, cfg)
        can_auto_merge = False
        if target is not None:
            same_div = target.division == grp.division
            same_age = target.age_group == grp.age_group
            if cfg.allow_skill_merge_for_stragglers and same_div and same_age:
                can_auto_merge = True
            elif cfg.allow_age_merge_for_stragglers and same_div and not same_age:
                can_auto_merge = True

        if can_auto_merge and target is not None:
            w = grp.wrestlers[0]
            target.wrestlers.append(w)
            target.wrestlers.sort(key=lambda x: (x.weight, x.team_key, x.name))
            target.bracket_format = resolve_bracket_format(len(target.wrestlers), target.rule.bracket_format)
            target.bouts = generate_bouts_for_group(target.wrestlers, target.bracket_format)
            target.flags.append(
                GroupFlag(
                    code="SKILL_MERGED",
                    message=(
                        f"Merged solo wrestler {w.name} ({w.weight:g} lbs, {grp.age_group} {grp.skill_level}) "
                        f"into {target.group_id}."
                    ),
                    severity="info",
                )
            )
            merged_solo_ids.add(grp.group_id)

    if merged_solo_ids:
        all_groups = [g for g in all_groups if g.group_id not in merged_solo_ids]

    # Evaluate flags and attach suggestions for remaining solo wrestlers
    for grp in all_groups:
        grp.flags = evaluate_group_flags(grp)
        if grp.size == 1:
            _, suggestion = _find_best_merge_candidate(grp, all_groups, cfg)
            for f in grp.flags:
                if f.code == "SOLO_WRESTLER" and suggestion:
                    f.suggestion = suggestion

    return TournamentResult(
        source=source,
        wrestlers=wrestlers,
        groups=all_groups,
        skipped_rows=skipped_rows or [],
    )
