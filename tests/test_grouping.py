"""Tests for Madison DP weight grouping, teammate separation, and straggler handling."""

from bracketman.config import TournamentConfig
from bracketman.grouping.madison import (
    build_tournament_groups,
    optimize_adjacent_teammate_swaps,
    partition_madison_dp,
)
from bracketman.models import GroupRuleConfig, Wrestler


def _make_wrestler(
    idx: int,
    weight: float,
    team: str = "T1",
    age_group: str = "8U",
    skill: str = "Beginner",
    division: str = "Coed",
) -> Wrestler:
    return Wrestler(
        id=f"W{idx:03d}",
        name=f"Wrestler {idx}",
        weight=weight,
        age_group=age_group,
        skill_level=skill,
        team=team,
        team_tab=team,
        division=division,
    )


def test_madison_dp_avoids_leaving_solo_straggler():
    """9 wrestlers with close weights should be split into (3, 3, 3) or (4, 5), never (4, 4, 1)."""
    rule = GroupRuleConfig(target_group_size=4, min_group_size=3, max_group_size=5, max_weight_spread_pct=12.0)
    wrestlers = [_make_wrestler(i, 50.0 + i * 0.5, team=f"T{i}") for i in range(9)]
    groups = partition_madison_dp(wrestlers, rule)
    sizes = [len(g) for g in groups]
    assert 1 not in sizes
    assert sum(sizes) == 9


def test_madison_dp_respects_natural_weight_clusters():
    """6 wrestlers in two tight weight clusters (45-46 lbs and 52-53 lbs) should split 3 and 3."""
    rule = GroupRuleConfig(target_group_size=4, min_group_size=3, max_group_size=4, max_weight_spread_pct=10.0)
    wrestlers = [
        _make_wrestler(1, 45.0, "T1"),
        _make_wrestler(2, 45.5, "T2"),
        _make_wrestler(3, 46.0, "T3"),
        _make_wrestler(4, 52.0, "T4"),
        _make_wrestler(5, 52.5, "T5"),
        _make_wrestler(6, 53.0, "T6"),
    ]
    groups = partition_madison_dp(wrestlers, rule)
    assert [len(g) for g in groups] == [3, 3]


def test_adjacent_boundary_swap_separates_teammates():
    """Boundary wrestlers with nearly identical weights should swap to eliminate teammate collision."""
    rule = GroupRuleConfig(
        target_group_size=3,
        min_group_size=3,
        max_group_size=4,
        max_weight_spread_pct=10.0,
        separate_teammates=True,
    )
    g1 = [
        _make_wrestler(1, 48.0, "AR"),
        _make_wrestler(2, 49.0, "COL"),
        _make_wrestler(3, 50.0, "AR"),
    ]
    g2 = [
        _make_wrestler(4, 50.2, "ENG"),
        _make_wrestler(5, 51.0, "GE"),
        _make_wrestler(6, 52.0, "HER"),
    ]
    optimized = optimize_adjacent_teammate_swaps([g1, g2], rule)
    teams_g1 = [w.team for w in optimized[0]]
    teams_g2 = [w.team for w in optimized[1]]
    assert len(set(teams_g1)) == 3
    assert len(set(teams_g2)) == 3


def test_skill_merge_for_solo_straggler():
    """When allow_skill_merge_for_stragglers=True, a solo Advanced wrestler merges into same-age Beginner."""
    cfg = TournamentConfig(allow_skill_merge_for_stragglers=True)
    wrestlers = [
        _make_wrestler(1, 60.0, "T1", age_group="10U", skill="Beginner"),
        _make_wrestler(2, 61.0, "T2", age_group="10U", skill="Beginner"),
        _make_wrestler(3, 62.0, "T3", age_group="10U", skill="Beginner"),
        _make_wrestler(4, 61.5, "T4", age_group="10U", skill="Advanced"),
    ]
    res = build_tournament_groups(wrestlers, config=cfg)
    assert len(res.groups) == 1
    assert res.groups[0].size == 4
    assert any(f.code == "SKILL_MERGED" for f in res.groups[0].flags)
