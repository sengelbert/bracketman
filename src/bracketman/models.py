"""Data models for wrestlers, grouping rules, bracket groups, and bouts."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Wrestler:
    """Represents a single wrestler entry in a division."""

    id: str
    name: str
    weight: float
    age_group: str
    skill_level: str
    team: str
    team_tab: str
    division: str = "Coed"
    age: int | float | None = None
    is_dual_entry: bool = False
    source_row: int = 0
    raw_age_group: str = ""
    raw_skill_level: str = ""

    @property
    def display_team(self) -> str:
        if self.team and self.team_tab and self.team.lower() != self.team_tab.lower():
            return f"{self.team} ({self.team_tab})"
        return self.team or self.team_tab or "Unattached"

    @property
    def team_key(self) -> str:
        """Canonical key used for teammate separation."""
        return (self.team_tab or self.team or "").strip().upper()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Wrestler:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            weight=float(data["weight"]),
            age_group=str(data["age_group"]),
            skill_level=str(data["skill_level"]),
            team=str(data.get("team", "")),
            team_tab=str(data.get("team_tab", "")),
            division=str(data.get("division", "Coed")),
            age=data.get("age"),
            is_dual_entry=bool(data.get("is_dual_entry", False)),
            source_row=int(data.get("source_row", 0)),
            raw_age_group=str(data.get("raw_age_group", "")),
            raw_skill_level=str(data.get("raw_skill_level", "")),
        )


@dataclass
class GroupRuleConfig:
    """Grouping configuration for a specific division, age group, and skill level."""

    mode: str = "madison"  # "madison" or "fixed_classes"
    target_group_size: int = 4
    min_group_size: int = 2
    max_group_size: int = 4
    max_weight_spread_pct: float = 10.0
    max_weight_spread_lbs: float | None = None
    progressive_spread: bool = True
    fixed_weight_classes: list[float] | None = None
    separate_teammates: bool = True
    bracket_format: str = "auto"  # "auto", "round_robin", "bracket_8"

    def effective_max_spread_pct(self, min_weight: float) -> float:
        """Return the maximum allowed % weight spread for a group starting at `min_weight`.

        When `progressive_spread` is True, heavier weight groups allow a slightly larger
        percentage spread (since upper weights are sparser) in addition to the naturally
        larger pound spread.
        """
        base = self.max_weight_spread_pct
        if not self.progressive_spread or min_weight <= 0:
            return base
        if min_weight < 50.0:
            return base
        if min_weight < 75.0:
            return round(base + 1.0, 2)
        if min_weight < 105.0:
            return round(base + 2.0, 2)
        if min_weight < 135.0:
            return round(base + 3.5, 2)
        return round(base + 5.0, 2)

    def effective_max_spread_lbs(self, min_weight: float) -> float:
        """Return the maximum allowed pound spread for a group starting at `min_weight`."""
        if self.max_weight_spread_lbs is not None:
            return self.max_weight_spread_lbs
        if min_weight <= 0:
            return 0.0
        pct = self.effective_max_spread_pct(min_weight)
        return round(min_weight * (pct / 100.0), 1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupRuleConfig:
        return cls(
            mode=str(data.get("mode", "madison")),
            target_group_size=int(data.get("target_group_size", 4)),
            min_group_size=int(data.get("min_group_size", 2)),
            max_group_size=int(data.get("max_group_size", 4)),
            max_weight_spread_pct=float(data.get("max_weight_spread_pct", 10.0)),
            max_weight_spread_lbs=(
                float(data["max_weight_spread_lbs"])
                if data.get("max_weight_spread_lbs") is not None
                else None
            ),
            progressive_spread=bool(data.get("progressive_spread", True)),
            fixed_weight_classes=data.get("fixed_weight_classes"),
            separate_teammates=bool(data.get("separate_teammates", True)),
            bracket_format=str(data.get("bracket_format", "auto")),
        )


@dataclass
class GroupFlag:
    """Warning, note, or recommendation attached to a generated bracket group."""

    code: str
    message: str
    severity: str = "warning"  # "info", "warning", "error"
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupFlag:
        return cls(
            code=str(data["code"]),
            message=str(data["message"]),
            severity=str(data.get("severity", "warning")),
            suggestion=data.get("suggestion"),
        )


@dataclass
class Bout:
    """A scheduled match within a bracket group."""

    bout_number: int
    round_number: int
    wrestler_a: Wrestler
    wrestler_b: Wrestler | None  # None indicates a BYE

    @property
    def is_teammate_match(self) -> bool:
        if self.wrestler_b is None:
            return False
        return bool(self.wrestler_a.team_key and self.wrestler_a.team_key == self.wrestler_b.team_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bout_number": self.bout_number,
            "round_number": self.round_number,
            "wrestler_a": self.wrestler_a.to_dict(),
            "wrestler_b": self.wrestler_b.to_dict() if self.wrestler_b else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bout:
        return cls(
            bout_number=int(data["bout_number"]),
            round_number=int(data["round_number"]),
            wrestler_a=Wrestler.from_dict(data["wrestler_a"]),
            wrestler_b=Wrestler.from_dict(data["wrestler_b"]) if data.get("wrestler_b") else None,
        )


@dataclass
class BracketGroup:
    """A formed bracket group (pod/weight class) of wrestlers."""

    group_id: str
    division: str
    age_group: str
    skill_level: str
    group_index: int
    wrestlers: list[Wrestler]
    rule: GroupRuleConfig
    bracket_format: str = "round_robin"
    bouts: list[Bout] = field(default_factory=list)
    flags: list[GroupFlag] = field(default_factory=list)
    fixed_class_label: str | None = None
    locked: bool = False
    manually_modified: bool = False

    @property
    def size(self) -> int:
        return len(self.wrestlers)

    @property
    def min_weight(self) -> float:
        return min((w.weight for w in self.wrestlers), default=0.0)

    @property
    def max_weight(self) -> float:
        return max((w.weight for w in self.wrestlers), default=0.0)

    @property
    def weight_spread_lbs(self) -> float:
        if len(self.wrestlers) <= 1:
            return 0.0
        return round(self.max_weight - self.min_weight, 2)

    @property
    def weight_spread_pct(self) -> float:
        if len(self.wrestlers) <= 1 or self.min_weight <= 0:
            return 0.0
        return round(((self.max_weight - self.min_weight) / self.min_weight) * 100.0, 2)

    @property
    def allowed_spread_pct(self) -> float:
        return self.rule.effective_max_spread_pct(self.min_weight)

    @property
    def allowed_spread_lbs(self) -> float:
        return self.rule.effective_max_spread_lbs(self.min_weight)

    @property
    def weight_label(self) -> str:
        if self.fixed_class_label:
            return self.fixed_class_label
        if not self.wrestlers:
            return "Empty"
        if len(self.wrestlers) == 1:
            return f"{self.min_weight:g} lbs"
        return f"{self.min_weight:g}–{self.max_weight:g} lbs"

    @property
    def team_counts(self) -> Counter[str]:
        return Counter(w.team_key for w in self.wrestlers if w.team_key)

    @property
    def teammate_pairs_count(self) -> int:
        """Number of same-team pairs inside this group."""
        counts = self.team_counts
        return sum(c * (c - 1) // 2 for c in counts.values() if c > 1)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity in ("warning", "error") for f in self.flags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "division": self.division,
            "age_group": self.age_group,
            "skill_level": self.skill_level,
            "group_index": self.group_index,
            "wrestlers": [w.to_dict() for w in self.wrestlers],
            "rule": self.rule.to_dict(),
            "bracket_format": self.bracket_format,
            "bouts": [b.to_dict() for b in self.bouts],
            "flags": [f.to_dict() for f in self.flags],
            "fixed_class_label": self.fixed_class_label,
            "locked": self.locked,
            "manually_modified": self.manually_modified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BracketGroup:
        return cls(
            group_id=str(data["group_id"]),
            division=str(data["division"]),
            age_group=str(data["age_group"]),
            skill_level=str(data["skill_level"]),
            group_index=int(data.get("group_index", 1)),
            wrestlers=[Wrestler.from_dict(w) for w in data.get("wrestlers", [])],
            rule=GroupRuleConfig.from_dict(data.get("rule", {})),
            bracket_format=str(data.get("bracket_format", "round_robin")),
            bouts=[Bout.from_dict(b) for b in data.get("bouts", [])],
            flags=[GroupFlag.from_dict(f) for f in data.get("flags", [])],
            fixed_class_label=data.get("fixed_class_label"),
            locked=bool(data.get("locked", False)),
            manually_modified=bool(data.get("manually_modified", False)),
        )


@dataclass
class TournamentResult:
    """Complete result of loading rosters and building bracket groups."""

    source: str
    wrestlers: list[Wrestler]
    groups: list[BracketGroup]
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def flagged_groups(self) -> list[BracketGroup]:
        return [g for g in self.groups if g.flags]

    @property
    def solo_groups(self) -> list[BracketGroup]:
        return [g for g in self.groups if g.size == 1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "wrestlers": [w.to_dict() for w in self.wrestlers],
            "groups": [g.to_dict() for g in self.groups],
            "skipped_rows": self.skipped_rows,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TournamentResult:
        return cls(
            source=str(data.get("source", "")),
            wrestlers=[Wrestler.from_dict(w) for w in data.get("wrestlers", [])],
            groups=[BracketGroup.from_dict(g) for g in data.get("groups", [])],
            skipped_rows=list(data.get("skipped_rows", [])),
            warnings=list(data.get("warnings", [])),
        )
