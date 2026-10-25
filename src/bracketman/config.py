"""Configuration loading and hierarchical rule resolution for Bracketman."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

from bracketman.models import GroupRuleConfig


DEFAULT_AGE_GROUPS = ["4U", "6U", "8U", "10U", "12U", "15U"]
DEFAULT_SKILL_LEVELS = ["Beginner", "Advanced"]
DEFAULT_DIVISIONS = ["Coed", "Girls"]

DEFAULT_SKILL_ALIASES: dict[str, list[str]] = {
    "Beginner": [
        "beginner",
        "novice",
        "beg",
        "nov",
        "rookie",
        "b",
        "1",
        "tier 2",
        "rec",
    ],
    "Advanced": [
        "advanced",
        "experienced",
        "experianced",  # Common typo found in real sheets
        "adv",
        "exp",
        "open",
        "elite",
        "competitive",
        "a",
        "2",
        "tier 1",
    ],
}

DEFAULT_AGE_GROUP_ALIASES: dict[str, list[str]] = {
    "4U": ["4u", "4 & under", "4 and under", "tot", "tots"],
    "6U": ["6u", "6 & under", "6 and under", "bantam"],
    "8U": ["8u", "8 & under", "8 and under", "midget", "intermediate"],
    "10U": ["10u", "10 & under", "10 and under", "novice age"],
    "12U": ["12u", "12 & under", "12 and under", "schoolboy"],
    "15U": ["15u", "15 & under", "15 and under", "14u", "14U", "14 & under", "14 and under", "cadet"],
}

DEFAULT_COLUMN_ALIASES: dict[str, list[str]] = {
    "weight": ["weight", "wt", "lbs", "actual weight", "scale weight"],
    "name": ["wrestlers name", "wrestler name", "wrestler's name", "name", "wrestler", "full name", "athlete"],
    "age_group": ["age group", "age division", "age div", "division", "group"],
    "team": ["school", "team", "club", "program", "organization", "org"],
    "age": ["age", "years old", "wrestler age"],
    "skill_level": [
        "ability (novice or experienced)",
        "ability",
        "skill level",
        "skill",
        "experience",
        "experience level",
        "level",
    ],
    "coed_bracket": [
        "boys / coed bracket",
        "boys/coed bracket",
        "coed bracket",
        "boys / coed",
        "coed",
        "boys bracket",
    ],
    "girls_bracket": [
        "girls only bracket",
        "girls bracket",
        "girls only",
        "girls",
    ],
}


@dataclass
class TournamentConfig:
    """Top-level configuration for reading sheets and building brackets."""

    tournament_name: str = "Wrestling Tournament"
    age_groups: list[str] = field(default_factory=lambda: list(DEFAULT_AGE_GROUPS))
    skill_levels: list[str] = field(default_factory=lambda: list(DEFAULT_SKILL_LEVELS))
    divisions: list[str] = field(default_factory=lambda: list(DEFAULT_DIVISIONS))
    skill_aliases: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_SKILL_ALIASES))
    age_group_aliases: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_AGE_GROUP_ALIASES))
    column_aliases: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_COLUMN_ALIASES))
    ignored_tabs: list[str] = field(default_factory=lambda: ["Instructions", "Summary", "Template", "Master"])
    default_rule: GroupRuleConfig = field(default_factory=GroupRuleConfig)
    division_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    age_group_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    allow_skill_merge_for_stragglers: bool = False
    allow_age_merge_for_stragglers: bool = False

    def normalize_skill(self, raw_value: str) -> str:
        """Map raw skill/ability string (e.g. 'Novice', 'experianced') to canonical skill level."""
        cleaned = raw_value.strip().lower()
        if not cleaned:
            return self.skill_levels[0] if self.skill_levels else "Beginner"
        for canonical in self.skill_levels:
            if cleaned == canonical.lower():
                return canonical
        for canonical, aliases in self.skill_aliases.items():
            if cleaned == canonical.lower() or cleaned in [a.lower() for a in aliases]:
                return canonical
        # Partial match fallback
        for canonical, aliases in self.skill_aliases.items():
            for alias in aliases:
                if len(alias) >= 3 and alias.lower() in cleaned:
                    return canonical
        return raw_value.strip().title()

    def normalize_age_group(self, raw_value: str, age: float | int | None = None) -> str:
        """Map raw age group string (e.g. '6u', '10U') to canonical age group."""
        cleaned = raw_value.strip().lower()
        if cleaned:
            for canonical in self.age_groups:
                if cleaned == canonical.lower():
                    return canonical
            for canonical in self.age_groups:
                aliases = self.age_group_aliases.get(canonical, [])
                if cleaned in [a.lower() for a in aliases]:
                    return canonical
            for canonical, aliases in self.age_group_aliases.items():
                if cleaned == canonical.lower() or cleaned in [a.lower() for a in aliases]:
                    return canonical
        # Fallback: infer from numeric age if available
        if age is not None:
            for canonical in self.age_groups:
                digits = "".join(ch for ch in canonical if ch.isdigit())
                if digits and age <= int(digits):
                    return canonical
        return raw_value.strip().upper() or "UNKNOWN"

    def resolve_rule(self, division: str, age_group: str, skill_level: str) -> GroupRuleConfig:
        """Resolve the effective GroupRuleConfig for (division, age_group, skill_level)."""
        params: dict[str, Any] = {
            "mode": self.default_rule.mode,
            "target_group_size": self.default_rule.target_group_size,
            "min_group_size": self.default_rule.min_group_size,
            "max_group_size": self.default_rule.max_group_size,
            "max_weight_spread_pct": self.default_rule.max_weight_spread_pct,
            "max_weight_spread_lbs": self.default_rule.max_weight_spread_lbs,
            "progressive_spread": self.default_rule.progressive_spread,
            "fixed_weight_classes": (
                list(self.default_rule.fixed_weight_classes)
                if self.default_rule.fixed_weight_classes
                else None
            ),
            "separate_teammates": self.default_rule.separate_teammates,
            "bracket_format": self.default_rule.bracket_format,
        }

        def _apply_dict(d: dict[str, Any]) -> None:
            for k in params:
                if k in d and d[k] is not None:
                    params[k] = d[k]

        # 1. Age-group overrides (e.g. 6U)
        age_cfg = self.age_group_overrides.get(age_group, {})
        _apply_dict(age_cfg)

        # 2. Skill-level nested overrides inside age_group (e.g. age_groups.10U.skills.Advanced)
        skills_in_age = age_cfg.get("skills", {})
        if isinstance(skills_in_age, dict) and skill_level in skills_in_age:
            _apply_dict(skills_in_age[skill_level])

        # 3. Division-level overrides (e.g. Girls)
        div_cfg = self.division_overrides.get(division, {})
        _apply_dict(div_cfg)

        # 4. Division + Age-group nested overrides inside division
        age_in_div = div_cfg.get("age_groups", {})
        if isinstance(age_in_div, dict) and age_group in age_in_div:
            _apply_dict(age_in_div[age_group])

        return GroupRuleConfig(**params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tournament_name": self.tournament_name,
            "age_groups": list(self.age_groups),
            "skill_levels": list(self.skill_levels),
            "divisions": list(self.divisions),
            "skill_aliases": dict(self.skill_aliases),
            "age_group_aliases": dict(self.age_group_aliases),
            "column_aliases": dict(self.column_aliases),
            "ignored_tabs": list(self.ignored_tabs),
            "defaults": self.default_rule.to_dict(),
            "division_rules": dict(self.division_overrides),
            "age_group_rules": dict(self.age_group_overrides),
            "allow_skill_merge_for_stragglers": self.allow_skill_merge_for_stragglers,
            "allow_age_merge_for_stragglers": self.allow_age_merge_for_stragglers,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TournamentConfig:
        """Construct a TournamentConfig from a parsed YAML/JSON dictionary."""
        cfg = cls()
        if "tournament_name" in data:
            cfg.tournament_name = str(data["tournament_name"])
        if "age_groups" in data and isinstance(data["age_groups"], list):
            cfg.age_groups = [str(x) for x in data["age_groups"]]
        if "skill_levels" in data and isinstance(data["skill_levels"], list):
            cfg.skill_levels = [str(x) for x in data["skill_levels"]]
        if "divisions" in data and isinstance(data["divisions"], list):
            cfg.divisions = [str(x) for x in data["divisions"]]
        if "skill_aliases" in data and isinstance(data["skill_aliases"], dict):
            cfg.skill_aliases.update(data["skill_aliases"])
        if "age_group_aliases" in data and isinstance(data["age_group_aliases"], dict):
            cfg.age_group_aliases.update(data["age_group_aliases"])
        if "column_aliases" in data and isinstance(data["column_aliases"], dict):
            cfg.column_aliases.update(data["column_aliases"])
        if "ignored_tabs" in data and isinstance(data["ignored_tabs"], list):
            cfg.ignored_tabs = [str(x) for x in data["ignored_tabs"]]

        if "defaults" in data and isinstance(data["defaults"], dict):
            d = data["defaults"]
            cfg.default_rule = GroupRuleConfig(
                mode=d.get("mode", cfg.default_rule.mode),
                target_group_size=int(d.get("target_group_size", cfg.default_rule.target_group_size)),
                min_group_size=int(d.get("min_group_size", cfg.default_rule.min_group_size)),
                max_group_size=int(d.get("max_group_size", cfg.default_rule.max_group_size)),
                max_weight_spread_pct=float(d.get("max_weight_spread_pct", cfg.default_rule.max_weight_spread_pct)),
                max_weight_spread_lbs=(
                    float(d["max_weight_spread_lbs"])
                    if d.get("max_weight_spread_lbs") is not None
                    else None
                ),
                progressive_spread=bool(d.get("progressive_spread", cfg.default_rule.progressive_spread)),
                fixed_weight_classes=d.get("fixed_weight_classes"),
                separate_teammates=bool(d.get("separate_teammates", cfg.default_rule.separate_teammates)),
                bracket_format=str(d.get("bracket_format", cfg.default_rule.bracket_format)),
            )

        if "age_group_rules" in data and isinstance(data["age_group_rules"], dict):
            cfg.age_group_overrides = data["age_group_rules"]
        elif "age_groups" in data and isinstance(data["age_groups"], dict):
            cfg.age_group_overrides = data["age_groups"]
            cfg.age_groups = list(data["age_groups"].keys())

        if "division_rules" in data and isinstance(data["division_rules"], dict):
            cfg.division_overrides = data["division_rules"]

        if "allow_skill_merge_for_stragglers" in data:
            cfg.allow_skill_merge_for_stragglers = bool(data["allow_skill_merge_for_stragglers"])
        if "allow_age_merge_for_stragglers" in data:
            cfg.allow_age_merge_for_stragglers = bool(data["allow_age_merge_for_stragglers"])

        return cfg

    @classmethod
    def from_yaml(cls, path: str | Path) -> TournamentConfig:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls.from_dict(raw)
