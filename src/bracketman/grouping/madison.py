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


def _count_skill_mix_cost(wrestlers: list[Wrestler]) -> float:
    """Soft penalty for mixing different skill levels (e.g. Beginner & Advanced) in the same pod.
    Ordered strictly so: Weight Spread / Avoiding 2-Man Pods > Age Group > Skill Level > Same Club.
    """
    if len(wrestlers) <= 1:
        return 0.0
    counts: dict[str, int] = defaultdict(int)
    for w in wrestlers:
        counts[w.skill_level] += 1
    if len(counts) <= 1:
        return 0.0
    minority = len(wrestlers) - max(counts.values())
    return 140.0 + minority * 25.0


def _dominant_skill_level(wrestlers: list[Wrestler], skill_levels: list[str] | None = None) -> str:
    """Return the majority skill level in a pod, breaking ties using canonical skill order."""
    if not wrestlers:
        return skill_levels[0] if skill_levels else "Beginner"
    counts: dict[str, int] = defaultdict(int)
    for w in wrestlers:
        counts[w.skill_level] += 1
    skill_order = {s: i for i, s in enumerate(skill_levels or ["Beginner", "Advanced"])}
    return max(counts.keys(), key=lambda s: (counts[s], -skill_order.get(s, 99)))


def _slice_cost(wrestlers: list[Wrestler], rule: GroupRuleConfig) -> float:
    """Compute penalty cost for forming a single group from `wrestlers`.
    Enforces the priority hierarchy: Weight > Age > Skill > Team.
    """
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

    # 1. Group size deviation & avoiding 2-man brackets when 3-4 man is possible
    size_diff = abs(size - rule.target_group_size)
    cost += (size_diff ** 2) * 30.0
    if size < rule.min_group_size:
        cost += (rule.min_group_size - size) * 350.0
    if size == 2 and rule.target_group_size >= 3:
        cost += 180.0
    if size > rule.max_group_size:
        cost += (size - rule.max_group_size) * 5000.0

    # 2. Weight spread cost (Priority 1: pct and lbs), scaling progressively with min_w
    cost += spread_pct * 6.0 + spread_lbs * 2.0

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

    # 3. Skill homogeneity cost (Priority 3: keep pure Beginner/Advanced when possible, blend when needed)
    cost += _count_skill_mix_cost(wrestlers)

    # 4. Teammate collision penalty (Priority 4: lowest tie-breaker)
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
    """Swap boundary wrestlers between adjacent weight groups if it reduces skill mixing or
    teammate collisions without violating weight spread rules or exceeding `max_swap_weight_diff_lbs`.
    """
    if len(groups) < 2:
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
            current_skill_cost = _count_skill_mix_cost(g_left) + _count_skill_mix_cost(g_right)
            if (not rule.separate_teammates or current_pairs == 0) and current_skill_cost == 0.0:
                continue

            best_swap: tuple[int, int] | None = None
            best_cost_delta = -0.5
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
                    new_skill_cost = _count_skill_mix_cost(new_left) + _count_skill_mix_cost(new_right)
                    if new_skill_cost > current_skill_cost:
                        continue
                    if new_skill_cost == current_skill_cost and (
                        not rule.separate_teammates or new_pairs >= current_pairs
                    ):
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
    """Generate diagnostic flags for a group based on its rule constraints and merged wrestler attributes."""
    flags: list[GroupFlag] = list(group.flags)
    existing_codes = {f.code for f in flags}
    rule = group.rule

    if group.size == 1:
        w = group.wrestlers[0]
        if "SOLO_WRESTLER" not in existing_codes:
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

    if group.size < rule.min_group_size and "SMALL_GROUP" not in existing_codes:
        flags.append(
            GroupFlag(
                code="SMALL_GROUP",
                message=f"Group has {group.size} wrestlers (configured min is {rule.min_group_size}).",
                severity="info",
            )
        )

    if group.size > rule.max_group_size and "OVERSIZED_GROUP" not in existing_codes:
        flags.append(
            GroupFlag(
                code="OVERSIZED_GROUP",
                message=f"Group has {group.size} wrestlers (exceeds configured max {rule.max_group_size}).",
                severity="warning",
            )
        )

    allowed_pct = group.allowed_spread_pct
    if allowed_pct and group.weight_spread_pct > allowed_pct and "WEIGHT_SPREAD_PCT_EXCEEDED" not in existing_codes:
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

    if (
        rule.max_weight_spread_lbs is not None
        and group.weight_spread_lbs > rule.max_weight_spread_lbs
        and "WEIGHT_SPREAD_LBS_EXCEEDED" not in existing_codes
    ):
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

    if rule.separate_teammates and group.teammate_pairs_count > 0 and "TEAMMATE_CONFLICT" not in existing_codes:
        dup_teams = [f"{t} (x{c})" for t, c in group.team_counts.items() if c > 1]
        flags.append(
            GroupFlag(
                code="TEAMMATE_CONFLICT",
                message=f"Contains teammates from same club: {', '.join(dup_teams)}.",
                severity="info",
            )
        )

    # Detect wrestlers merged across skill levels, age groups, or divisions (auto or manual merge)
    diff_skills = [w for w in group.wrestlers if w.skill_level != group.skill_level]
    if diff_skills and "SKILL_MERGED" not in existing_codes:
        merged_str = ", ".join(f"{w.name} ({w.weight:g} lbs, {w.age_group} {w.skill_level})" for w in diff_skills)
        flags.append(
            GroupFlag(
                code="SKILL_MERGED",
                message=f"Merged skill level: {merged_str} into {group.group_id} ({group.skill_level}).",
                severity="info",
            )
        )

    diff_ages = [w for w in group.wrestlers if w.age_group != group.age_group]
    if diff_ages and "AGE_MERGED" not in existing_codes:
        merged_age_str = ", ".join(f"{w.name} ({w.weight:g} lbs, {w.age_group} {w.skill_level})" for w in diff_ages)
        flags.append(
            GroupFlag(
                code="AGE_MERGED",
                message=f"Merged age group: {merged_age_str} into {group.group_id} ({group.age_group}).",
                severity="warning",
            )
        )

    diff_divs = [w for w in group.wrestlers if w.division != group.division]
    if diff_divs and "DIVISION_MERGED" not in existing_codes:
        merged_div_str = ", ".join(f"{w.name} ({w.weight:g} lbs, {w.division} {w.age_group})" for w in diff_divs)
        flags.append(
            GroupFlag(
                code="DIVISION_MERGED",
                message=f"Merged division: {merged_div_str} into {group.group_id} ({group.division}).",
                severity="warning",
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

    # Divisions where this wrestler already has an active entry in another bracket
    existing_divs_for_w = {
        g.division
        for g in all_groups
        if g.group_id != solo_group.group_id
        and g.size > 0
        and any(
            cw.name.strip().lower() == w.name.strip().lower() and cw.team_key == w.team_key
            for cw in g.wrestlers
        )
    }

    for candidate in all_groups:
        if candidate.group_id == solo_group.group_id or candidate.size == 0:
            continue
        if candidate.size >= candidate.rule.max_group_size:
            continue
        # Never merge a wrestler into a bracket or division where they ALREADY have an entry
        # (ensures at most 1 Coed and 1 Girls bracket per wrestler)
        if candidate.division in existing_divs_for_w:
            continue
        if any(
            cw.name.strip().lower() == w.name.strip().lower() and cw.team_key == w.team_key
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
            rel_penalty = 25.0
            rel_desc = f"adjacent age group ({candidate.age_group} {candidate.skill_level})"
        elif same_div and adj_age and not same_skill:
            rel_penalty = 35.0
            rel_desc = f"adjacent age/skill ({candidate.age_group} {candidate.skill_level})"
        elif not same_div and same_age:
            rel_penalty = 55.0
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

        mat_penalty = (
            0.0
            if (solo_group.mat_number is None or candidate.mat_number == solo_group.mat_number)
            else 12.0
        )
        score = (
            rel_penalty
            + mat_penalty
            + new_spread_pct * 2.0
            + abs((candidate.size + 1) - candidate.rule.target_group_size) * 5.0
        )
        if score < best_score:
            best_score = score
            best_target = candidate
            mat_note = f", {candidate.mat_label}" if candidate.mat_number is not None else ""
            best_reason = (
                f"Merge into {candidate.group_id} ({rel_desc}{mat_note}, {candidate.weight_label}, "
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

    # Order keys canonically by config order
    div_order = {d: i for i, d in enumerate(cfg.divisions)}
    age_order = {a: i for i, a in enumerate(cfg.age_groups)}
    skill_order = {s: i for i, s in enumerate(cfg.skill_levels)}

    all_groups: list[BracketGroup] = []

    if cfg.blend_skills_to_fill_brackets:
        # Option B: Pool by (division, age_group) and use the unified priority DP
        # (Division [Locked] > Weight > Age > Skill > Team)
        age_buckets: dict[tuple[str, str], list[Wrestler]] = defaultdict(list)
        for w in wrestlers:
            age_buckets[(w.division, w.age_group)].append(w)

        sorted_age_keys = sorted(
            age_buckets.keys(),
            key=lambda k: (div_order.get(k[0], 99), age_order.get(k[1], 99), k),
        )

        for div, age_grp in sorted_age_keys:
            pool = list(age_buckets[(div, age_grp)])
            pool.sort(key=lambda w: (w.weight, skill_order.get(w.skill_level, 99), w.team_key, w.name))
            default_skill = cfg.skill_levels[0] if cfg.skill_levels else "Beginner"
            base_rule = cfg.resolve_rule(div, age_grp, default_skill)

            if base_rule.mode == "fixed_classes" and base_rule.fixed_weight_classes:
                labeled_slices = group_fixed_classes(pool, base_rule)
            else:
                raw_slices = partition_madison_dp(pool, base_rule)
                raw_slices = optimize_adjacent_teammate_swaps(raw_slices, base_rule)
                labeled_slices = [(None, s) for s in raw_slices]

            temp_groups: list[BracketGroup] = []
            for fixed_label, slice_wrestlers in labeled_slices:
                pod_skill = _dominant_skill_level(slice_wrestlers, cfg.skill_levels)
                pod_rule = cfg.resolve_rule(div, age_grp, pod_skill)
                b_fmt = resolve_bracket_format(len(slice_wrestlers), pod_rule.bracket_format)
                bouts = generate_bouts_for_group(slice_wrestlers, b_fmt)
                temp_groups.append(
                    BracketGroup(
                        group_id="",
                        division=div,
                        age_group=age_grp,
                        skill_level=pod_skill,
                        group_index=1,
                        wrestlers=slice_wrestlers,
                        rule=pod_rule,
                        bracket_format=b_fmt,
                        bouts=bouts,
                        fixed_class_label=fixed_label,
                    )
                )

            # Sort within (div, age_grp) by (skill_order, min_weight) and assign sequential group IDs
            temp_groups.sort(key=lambda g: (skill_order.get(g.skill_level, 99), g.min_weight, g.max_weight))
            skill_counters: dict[str, int] = defaultdict(int)
            for grp in temp_groups:
                skill_counters[grp.skill_level] += 1
                idx = skill_counters[grp.skill_level]
                grp.group_index = idx
                grp.group_id = _make_group_id(div, age_grp, grp.skill_level, idx)
                all_groups.append(grp)
    else:
        # Strict skill-bucket mode: Bucket wrestlers by (division, age_group, skill_level)
        buckets: dict[tuple[str, str, str], list[Wrestler]] = defaultdict(list)
        for w in wrestlers:
            buckets[(w.division, w.age_group, w.skill_level)].append(w)

        sorted_keys = sorted(
            buckets.keys(),
            key=lambda k: (
                div_order.get(k[0], 99),
                age_order.get(k[1], 99),
                skill_order.get(k[2], 99),
                k,
            ),
        )

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
            if (cfg.allow_skill_merge_for_stragglers or getattr(cfg, "blend_skills_to_fill_brackets", False)) and same_div and same_age:
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

    if cfg.auto_assign_mats and cfg.mat_count and cfg.mat_count >= 1:
        assign_mats_to_groups(all_groups, mat_count=cfg.mat_count, strategy="balanced")

    return TournamentResult(
        source=source,
        wrestlers=wrestlers,
        groups=all_groups,
        skipped_rows=skipped_rows or [],
    )


def assign_mats_to_groups(
    groups: list[BracketGroup],
    mat_count: int = 4,
    strategy: str = "balanced",
    preserve_existing_locked: bool = False,
) -> list[BracketGroup]:
    """Assign each bracket group to a Mat / Table number (`1..mat_count`).

    Strategies:
      - `"coed_by_age_girls_together"`: Pools all `Girls` brackets together as a single group
        (since Girls wrestle simultaneously across all age groups) and distributes them evenly
        across mats `1..mat_count`, while distributing each `Coed` age group (`4U, 6U, 8U, 10U, 12U, 15U`)
        equally across mats `1..mat_count` by bracket count.
      - `"equal_age_group"`: Distributes an equal number of brackets (`n // mat_count`, `±1`) from
        EACH `(division, age_group)` across all mats `1..mat_count`, allocating any `+1` remainder
        brackets to the mats with the **fewest total brackets** `(mat_brackets[m], mat_bouts[m], m)`.
      - `"balanced"` (default): Distributes contiguous blocks from each `(division, age_group)`
        across mats `1..mat_count`, allocating any `+1` remainder brackets to the mats with the
        **fewest total bouts** `(mat_bouts[m], mat_brackets[m], m)` so mat finish times stay equal.
      - `"contiguous_blocks"`: Splits the entire bracket list into `mat_count` contiguous
        age/weight segments of equal bout load (e.g. Mat 1 = youngest/lightest, Mat N = oldest/Girls).
      - `"round_robin"`: Alternates `Mat 1, Mat 2, ..., Mat N` sequentially across groups.
    """
    if mat_count < 1 or not groups:
        return groups

    def _is_preserved(grp: BracketGroup) -> bool:
        return bool(
            preserve_existing_locked
            and grp.locked
            and grp.mat_number is not None
            and 1 <= grp.mat_number <= mat_count
        )

    if strategy == "round_robin":
        idx_counter = 0
        for g in groups:
            if _is_preserved(g):
                continue
            g.mat_number = (idx_counter % mat_count) + 1
            idx_counter += 1
        return groups

    mat_bouts: dict[int, int] = {m: 0 for m in range(1, mat_count + 1)}
    mat_brackets: dict[int, int] = {m: 0 for m in range(1, mat_count + 1)}

    for g in groups:
        if _is_preserved(g):
            assert g.mat_number is not None
            mat_bouts[g.mat_number] += max(1, len(g.bouts))
            mat_brackets[g.mat_number] += 1

    unlocked_groups = [g for g in groups if not _is_preserved(g)]
    if not unlocked_groups:
        return groups

    if strategy == "contiguous_blocks":
        rem_bouts = sum(max(1, len(g.bouts)) for g in unlocked_groups)
        cur_mat = 1
        for idx, grp in enumerate(unlocked_groups):
            rem_groups = len(unlocked_groups) - idx
            rem_mats = mat_count - cur_mat
            grp_bouts = max(1, len(grp.bouts))
            dynamic_target = (mat_bouts[cur_mat] + rem_bouts) / float(mat_count - cur_mat + 1)
            # Advance to next mat if current mat has at least 1 bracket and adding this bracket
            # pushes it past dynamic_target (while ensuring enough remaining brackets for remaining mats)
            if (
                cur_mat < mat_count
                and mat_brackets[cur_mat] > 0
                and (
                    rem_groups <= rem_mats
                    or (mat_bouts[cur_mat] + grp_bouts * 0.5 > dynamic_target and rem_groups > rem_mats)
                )
            ):
                cur_mat += 1
            grp.mat_number = cur_mat
            mat_bouts[cur_mat] += grp_bouts
            mat_brackets[cur_mat] += 1
            rem_bouts -= grp_bouts
        return groups

    # Bucket distribution ("coed_by_age_girls_together", "equal_age_group", and "balanced"):
    buckets_map: dict[tuple[str, str], list[BracketGroup]] = {}
    for g in unlocked_groups:
        if strategy == "coed_by_age_girls_together" and g.division.strip().lower().startswith("girl"):
            b_key = ("Girls", "ALL_GIRLS")
        else:
            b_key = (g.division, g.age_group)
        buckets_map.setdefault(b_key, []).append(g)

    for bucket in buckets_map.values():
        n = len(bucket)
        k_mats = min(n, mat_count)
        if strategy in ("equal_age_group", "coed_by_age_girls_together"):
            # Prioritize equal total bracket count across mats first, then bouts
            least_loaded = sorted(
                range(1, mat_count + 1),
                key=lambda m: (mat_brackets[m], mat_bouts[m], m),
            )[:k_mats]
        else:
            # Default "balanced": prioritize equal total bout count across mats first, then brackets
            least_loaded = sorted(
                range(1, mat_count + 1),
                key=lambda m: (mat_bouts[m], mat_brackets[m], m),
            )[:k_mats]

        base_chunk = n // k_mats
        rem = n % k_mats
        # Allocate the +1 remainder chunks to the `rem` least-loaded mats (not Mat 1!)
        chunk_for_mat = {
            m: base_chunk + (1 if idx < rem else 0)
            for idx, m in enumerate(least_loaded)
        }

        # Assign contiguous weight slices in ascending mat number order so lighter weights
        # stay on lower mat numbers while each mat receives its exact load-balanced chunk size
        cursor = 0
        for mat_num in sorted(least_loaded):
            chunk_len = chunk_for_mat[mat_num]
            for grp in bucket[cursor : cursor + chunk_len]:
                grp.mat_number = mat_num
                mat_bouts[mat_num] += max(1, len(grp.bouts))
                mat_brackets[mat_num] += 1
            cursor += chunk_len

    return groups


