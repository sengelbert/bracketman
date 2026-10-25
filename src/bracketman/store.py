"""Persistent tournament storage, manual bracket tweaking, and targeted bracket regeneration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any

from bracketman.config import TournamentConfig
from bracketman.grouping.bouts import generate_bouts_for_group, resolve_bracket_format
from bracketman.grouping.madison import (
    _find_best_merge_candidate,
    _make_group_id,
    build_tournament_groups,
    evaluate_group_flags,
    group_fixed_classes,
    optimize_adjacent_teammate_swaps,
    partition_madison_dp,
)
from bracketman.io.loader import load_wrestlers
from bracketman.models import BracketGroup, GroupFlag, GroupRuleConfig, TournamentResult, Wrestler


DEFAULT_STORE_DIR = Path("data/tournaments")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "tournament"


@dataclass
class SavedTournament:
    """Represents a persisted tournament with configuration, rosters, brackets, and edit history."""

    slug: str
    name: str
    created_at: str
    updated_at: str
    sheet_url: str = ""
    config: TournamentConfig = field(default_factory=TournamentConfig)
    result: TournamentResult = field(
        default_factory=lambda: TournamentResult(source="", wrestlers=[], groups=[])
    )
    history: list[str] = field(default_factory=list)
    scratched_wrestlers: list[dict[str, Any]] = field(default_factory=list)

    def log(self, message: str) -> None:
        ts = _now_iso()
        self.updated_at = ts
        self.history.insert(0, f"[{ts}] {message}")
        self.history = self.history[:100]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sheet_url": self.sheet_url,
            "config": self.config.to_dict(),
            "result": self.result.to_dict(),
            "history": self.history,
            "scratched_wrestlers": self.scratched_wrestlers,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavedTournament:
        cfg = TournamentConfig.from_dict(data.get("config", {}))
        res = TournamentResult.from_dict(data.get("result", {}))
        return cls(
            slug=str(data["slug"]),
            name=str(data["name"]),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            sheet_url=str(data.get("sheet_url", "")),
            config=cfg,
            result=res,
            history=list(data.get("history", [])),
            scratched_wrestlers=list(data.get("scratched_wrestlers", [])),
        )


def _tournament_dir(slug: str, base_dir: Path = DEFAULT_STORE_DIR) -> Path:
    return base_dir / slug


def _tournament_json_path(slug: str, base_dir: Path = DEFAULT_STORE_DIR) -> Path:
    return _tournament_dir(slug, base_dir) / "tournament.json"


def save_tournament(tournament: SavedTournament, base_dir: Path = DEFAULT_STORE_DIR) -> Path:
    """Save tournament state to disk."""
    t_dir = _tournament_dir(tournament.slug, base_dir)
    t_dir.mkdir(parents=True, exist_ok=True)
    path = _tournament_json_path(tournament.slug, base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tournament.to_dict(), f, indent=2)
    return path


def load_tournament(slug: str, base_dir: Path = DEFAULT_STORE_DIR) -> SavedTournament:
    """Load a saved tournament by slug."""
    path = _tournament_json_path(slug, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Tournament '{slug}' not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return SavedTournament.from_dict(data)


def list_tournaments(base_dir: Path = DEFAULT_STORE_DIR) -> list[SavedTournament]:
    """Return all saved tournaments sorted by most recently updated."""
    if not base_dir.exists():
        return []
    items: list[SavedTournament] = []
    for sub in sorted(base_dir.iterdir()):
        jpath = sub / "tournament.json"
        if sub.is_dir() and jpath.exists():
            try:
                items.append(load_tournament(sub.name, base_dir))
            except Exception:
                continue
    items.sort(key=lambda t: t.updated_at, reverse=True)
    return items


def create_tournament(
    name: str,
    sheet_url: str = "",
    config: TournamentConfig | None = None,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Create and persist a new tournament."""
    base_slug = slugify(name)
    slug = base_slug
    counter = 2
    while _tournament_json_path(slug, base_dir).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    cfg = config or TournamentConfig(tournament_name=name)
    cfg.tournament_name = name
    now = _now_iso()
    t = SavedTournament(
        slug=slug,
        name=name,
        created_at=now,
        updated_at=now,
        sheet_url=sheet_url.strip(),
        config=cfg,
    )
    t.log(f"Created tournament '{name}'.")
    save_tournament(t, base_dir)
    return t


def delete_tournament(slug: str, base_dir: Path = DEFAULT_STORE_DIR) -> None:
    """Delete a tournament directory from disk."""
    t_dir = _tournament_dir(slug, base_dir)
    if t_dir.exists():
        shutil.rmtree(t_dir)


def refresh_group(group: BracketGroup) -> None:
    """Sort wrestlers by weight, regenerate bouts, and re-evaluate flags for a single group."""
    group.wrestlers.sort(key=lambda w: (w.weight, w.team_key, w.name))
    group.bracket_format = resolve_bracket_format(len(group.wrestlers), group.rule.bracket_format)
    group.bouts = generate_bouts_for_group(group.wrestlers, group.bracket_format)
    preserved_info = [f for f in group.flags if f.code == "SKILL_MERGED"]
    group.flags = preserved_info
    group.flags = evaluate_group_flags(group)


def reindex_and_refresh_all_groups(tournament: SavedTournament, renumber_ids: bool = True) -> None:
    """Remove empty groups, sort groups canonically, optionally renumber IDs, and refresh flags/suggestions."""
    cfg = tournament.config
    non_empty = [g for g in tournament.result.groups if g.size > 0]

    div_order = {d: i for i, d in enumerate(cfg.divisions)}
    age_order = {a: i for i, a in enumerate(cfg.age_groups)}
    skill_order = {s: i for i, s in enumerate(cfg.skill_levels)}

    buckets: dict[tuple[str, str, str], list[BracketGroup]] = defaultdict(list)
    for g in non_empty:
        refresh_group(g)
        buckets[(g.division, g.age_group, g.skill_level)].append(g)

    sorted_keys = sorted(
        buckets.keys(),
        key=lambda k: (
            div_order.get(k[0], 99),
            age_order.get(k[1], 99),
            skill_order.get(k[2], 99),
            k,
        ),
    )

    ordered_groups: list[BracketGroup] = []
    for key in sorted_keys:
        div, age_grp, skill = key
        grps = buckets[key]
        grps.sort(key=lambda g: (g.min_weight, g.max_weight, g.group_index))
        for idx, g in enumerate(grps, start=1):
            g.group_index = idx
            if renumber_ids:
                g.group_id = _make_group_id(div, age_grp, skill, idx)
            ordered_groups.append(g)

    # Update solo wrestler merge suggestions across all groups
    for g in ordered_groups:
        if g.size == 1:
            _, suggestion = _find_best_merge_candidate(g, ordered_groups, cfg)
            for fl in g.flags:
                if fl.code == "SOLO_WRESTLER":
                    fl.suggestion = suggestion

    tournament.result.groups = ordered_groups
    # Keep flat wrestler list synchronized with groups
    tournament.result.wrestlers = [w for g in ordered_groups for w in g.wrestlers]


def import_spreadsheet_to_tournament(
    tournament: SavedTournament,
    source: str | Path,
    mode: str = "full_overwrite",
    merge_skills: bool | None = None,
    merge_ages: bool | None = None,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Import a Google Sheet URL or local spreadsheet into `tournament`.

    `mode`:
      - `"full_overwrite"`: Rebuild all brackets from the spreadsheet, discarding previous brackets.
      - `"preserve_locked"`: Keep all locked / manually tweaked brackets intact and only build
        new brackets for wrestlers not already placed in a locked bracket.
    """
    cfg = tournament.config
    if merge_skills is not None:
        cfg.allow_skill_merge_for_stragglers = merge_skills
    if merge_ages is not None:
        cfg.allow_age_merge_for_stragglers = merge_ages

    wrestlers, skipped, tabs = load_wrestlers(source, config=cfg)
    source_str = str(source)
    if source_str.startswith("http"):
        tournament.sheet_url = source_str

    if mode == "preserve_locked" and tournament.result.groups:
        locked_groups = [g for g in tournament.result.groups if g.locked or g.manually_modified]
        if locked_groups:
            # Map incoming wrestlers by (name.lower(), team_key, division) to update weights in locked groups
            incoming_by_key: dict[tuple[str, str, str], Wrestler] = {
                (w.name.lower(), w.team_key, w.division): w for w in wrestlers
            }
            locked_keys: set[tuple[str, str, str]] = set()
            for lg in locked_groups:
                updated_members: list[Wrestler] = []
                for w in lg.wrestlers:
                    k = (w.name.lower(), w.team_key, w.division)
                    locked_keys.add(k)
                    if k in incoming_by_key:
                        updated_members.append(incoming_by_key[k])
                    else:
                        updated_members.append(w)
                lg.wrestlers = updated_members
                refresh_group(lg)

            unlocked_wrestlers = [
                w for w in wrestlers if (w.name.lower(), w.team_key, w.division) not in locked_keys
            ]
            partial_res = build_tournament_groups(
                wrestlers=unlocked_wrestlers,
                config=cfg,
                source=source_str,
                skipped_rows=skipped,
            )
            tournament.result.source = source_str
            tournament.result.skipped_rows = skipped
            tournament.result.groups = locked_groups + partial_res.groups
            reindex_and_refresh_all_groups(tournament, renumber_ids=True)
            tournament.log(
                f"Synced spreadsheet ({len(wrestlers)} entries across {len(tabs)} tabs) "
                f"preserving {len(locked_groups)} locked/tweaked bracket(s)."
            )
            save_tournament(tournament, base_dir)
            return tournament

    # Full overwrite mode
    tournament.result = build_tournament_groups(
        wrestlers=wrestlers,
        config=cfg,
        source=source_str,
        skipped_rows=skipped,
    )
    tournament.log(
        f"Imported & built {len(tournament.result.groups)} brackets from {len(wrestlers)} entries "
        f"({len(tabs)} tabs, full overwrite)."
    )
    save_tournament(tournament, base_dir)
    return tournament


def move_wrestler(
    tournament: SavedTournament,
    wrestler_id: str,
    from_group_id: str,
    to_group_id: str,
    renumber_ids: bool = False,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Move a wrestler from `from_group_id` to `to_group_id` (or '__NEW__' to create a new bracket)."""
    src_group = next((g for g in tournament.result.groups if g.group_id == from_group_id), None)
    if src_group is None:
        raise ValueError(f"Source bracket '{from_group_id}' not found.")

    wrestler = next((w for w in src_group.wrestlers if w.id == wrestler_id), None)
    if wrestler is None:
        raise ValueError(f"Wrestler '{wrestler_id}' not found in '{from_group_id}'.")

    src_group.wrestlers = [w for w in src_group.wrestlers if w.id != wrestler_id]
    src_group.manually_modified = True
    src_group.locked = True

    if to_group_id == "__NEW__":
        bucket_groups = [
            g
            for g in tournament.result.groups
            if (g.division, g.age_group, g.skill_level)
            == (src_group.division, src_group.age_group, src_group.skill_level)
        ]
        next_idx = max((g.group_index for g in bucket_groups), default=0) + 1
        new_gid = _make_group_id(src_group.division, src_group.age_group, src_group.skill_level, next_idx)
        existing_ids = {g.group_id for g in tournament.result.groups}
        while new_gid in existing_ids:
            next_idx += 1
            new_gid = _make_group_id(
                src_group.division, src_group.age_group, src_group.skill_level, next_idx
            )
        new_grp = BracketGroup(
            group_id=new_gid,
            division=src_group.division,
            age_group=src_group.age_group,
            skill_level=src_group.skill_level,
            group_index=next_idx,
            wrestlers=[wrestler],
            rule=src_group.rule,
            locked=True,
            manually_modified=True,
        )
        refresh_group(new_grp)
        tournament.result.groups.append(new_grp)
        dest_id_label = new_gid
    else:
        dst_group = next((g for g in tournament.result.groups if g.group_id == to_group_id), None)
        if dst_group is None:
            raise ValueError(f"Target bracket '{to_group_id}' not found.")
        dst_group.wrestlers.append(wrestler)
        dst_group.manually_modified = True
        dst_group.locked = True
        dest_id_label = dst_group.group_id

    reindex_and_refresh_all_groups(tournament, renumber_ids=renumber_ids)
    tournament.log(
        f"Moved {wrestler.name} ({wrestler.weight:g} lbs) from {from_group_id} -> {dest_id_label}."
    )
    save_tournament(tournament, base_dir)
    return tournament


def swap_wrestlers(
    tournament: SavedTournament,
    group_a_id: str,
    wrestler_a_id: str,
    group_b_id: str,
    wrestler_b_id: str,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Swap two wrestlers between two brackets."""
    ga = next((g for g in tournament.result.groups if g.group_id == group_a_id), None)
    gb = next((g for g in tournament.result.groups if g.group_id == group_b_id), None)
    if ga is None or gb is None:
        raise ValueError("Both brackets must exist to swap wrestlers.")

    wa = next((w for w in ga.wrestlers if w.id == wrestler_a_id), None)
    wb = next((w for w in gb.wrestlers if w.id == wrestler_b_id), None)
    if wa is None or wb is None:
        raise ValueError("Selected wrestlers not found in the specified brackets.")

    ga.wrestlers = [wb if w.id == wrestler_a_id else w for w in ga.wrestlers]
    gb.wrestlers = [wa if w.id == wrestler_b_id else w for w in gb.wrestlers]
    ga.manually_modified = True
    ga.locked = True
    gb.manually_modified = True
    gb.locked = True

    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    tournament.log(
        f"Swapped {wa.name} ({ga.group_id}) <-> {wb.name} ({gb.group_id})."
    )
    save_tournament(tournament, base_dir)
    return tournament


def merge_brackets(
    tournament: SavedTournament,
    source_group_id: str,
    target_group_id: str,
    renumber_ids: bool = False,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Merge all wrestlers from `source_group_id` into `target_group_id`."""
    if source_group_id == target_group_id:
        raise ValueError("Cannot merge a bracket into itself.")
    src = next((g for g in tournament.result.groups if g.group_id == source_group_id), None)
    dst = next((g for g in tournament.result.groups if g.group_id == target_group_id), None)
    if src is None or dst is None:
        raise ValueError("Source or target bracket not found.")

    names = ", ".join(w.name for w in src.wrestlers)
    dst.wrestlers.extend(src.wrestlers)
    src.wrestlers = []
    dst.manually_modified = True
    dst.locked = True

    reindex_and_refresh_all_groups(tournament, renumber_ids=renumber_ids)
    tournament.log(f"Merged bracket {source_group_id} ({names}) into {target_group_id}.")
    save_tournament(tournament, base_dir)
    return tournament


def toggle_bracket_lock(
    tournament: SavedTournament,
    group_ids: list[str],
    locked: bool,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Lock or unlock one or more brackets by ID."""
    target_set = set(group_ids)
    changed = 0
    for g in tournament.result.groups:
        if g.group_id in target_set:
            g.locked = locked
            changed += 1
    state_str = "Locked" if locked else "Unlocked"
    tournament.log(f"{state_str} {changed} bracket(s): {', '.join(group_ids)}.")
    save_tournament(tournament, base_dir)
    return tournament


def update_wrestler_in_bracket(
    tournament: SavedTournament,
    group_id: str,
    wrestler_id: str,
    name: str | None = None,
    weight: float | None = None,
    team: str | None = None,
    skill_level: str | None = None,
    age_group: str | None = None,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Update a wrestler's attributes (e.g. scale weight check adjustment) inside a bracket."""
    grp = next((g for g in tournament.result.groups if g.group_id == group_id), None)
    if grp is None:
        raise ValueError(f"Bracket '{group_id}' not found.")
    old_w = next((w for w in grp.wrestlers if w.id == wrestler_id), None)
    if old_w is None:
        raise ValueError(f"Wrestler '{wrestler_id}' not found in '{group_id}'.")

    new_w = Wrestler(
        id=old_w.id,
        name=name.strip() if name is not None else old_w.name,
        weight=round(float(weight), 2) if weight is not None else old_w.weight,
        age_group=age_group if age_group is not None else old_w.age_group,
        skill_level=skill_level if skill_level is not None else old_w.skill_level,
        team=team.strip() if team is not None else old_w.team,
        team_tab=old_w.team_tab,
        division=old_w.division,
        age=old_w.age,
        is_dual_entry=old_w.is_dual_entry,
        source_row=old_w.source_row,
        raw_age_group=old_w.raw_age_group,
        raw_skill_level=old_w.raw_skill_level,
    )
    grp.wrestlers = [new_w if w.id == wrestler_id else w for w in grp.wrestlers]
    grp.manually_modified = True
    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    tournament.log(
        f"Updated wrestler {new_w.name} in {group_id} (weight: {old_w.weight:g} -> {new_w.weight:g} lbs)."
    )
    save_tournament(tournament, base_dir)
    return tournament


def regenerate_brackets_by_ids(
    tournament: SavedTournament,
    group_ids: list[str],
    target_group_size: int | None = None,
    max_group_size: int | None = None,
    min_group_size: int | None = None,
    max_weight_spread_pct: float | None = None,
    separate_teammates: bool | None = None,
    combine_across_skills_or_ages: bool = False,
    renumber_ids: bool = True,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Regenerate specific bracket(s) by their ID(s) using the Madison grouping engine.

    - Collects all wrestlers from the specified `group_ids`.
    - If `combine_across_skills_or_ages` is True, pools all wrestlers from the selected
      bracket IDs together into the first selected bracket's (division, age_group, skill_level)
      and re-runs Madison partitioning on the combined pool.
    - Otherwise, regroups them within each (division, age_group, skill_level) bucket.
    - Applies any custom rule overrides (target size, max size, spread %) to the regenerated brackets.
    """
    cleaned_ids = [gid.strip().upper() for gid in group_ids if gid.strip()]
    id_set = set(cleaned_ids)
    selected_groups = [g for g in tournament.result.groups if g.group_id.upper() in id_set]
    if not selected_groups:
        raise ValueError(f"No matching brackets found for ID(s): {', '.join(group_ids)}")

    remaining_groups = [g for g in tournament.result.groups if g.group_id.upper() not in id_set]
    cfg = tournament.config

    def _apply_rule_overrides(base_rule: GroupRuleConfig) -> GroupRuleConfig:
        r = GroupRuleConfig.from_dict(base_rule.to_dict())
        if target_group_size is not None:
            r.target_group_size = target_group_size
        if max_group_size is not None:
            r.max_group_size = max_group_size
        if min_group_size is not None:
            r.min_group_size = min_group_size
        if max_weight_spread_pct is not None:
            r.max_weight_spread_pct = max_weight_spread_pct
        if separate_teammates is not None:
            r.separate_teammates = separate_teammates
        return r

    new_groups: list[BracketGroup] = []

    if combine_across_skills_or_ages:
        primary = selected_groups[0]
        div, age_grp, skill = primary.division, primary.age_group, primary.skill_level
        rule = _apply_rule_overrides(cfg.resolve_rule(div, age_grp, skill))
        pool = [w for g in selected_groups for w in g.wrestlers]
        pool.sort(key=lambda w: (w.weight, w.team_key, w.name))
        if rule.mode == "fixed_classes" and rule.fixed_weight_classes:
            slices = group_fixed_classes(pool, rule)
        else:
            raw_slices = partition_madison_dp(pool, rule)
            raw_slices = optimize_adjacent_teammate_swaps(raw_slices, rule)
            slices = [(None, s) for s in raw_slices]

        for idx, (flabel, sw) in enumerate(slices, start=1):
            gid = _make_group_id(div, age_grp, skill, 90 + idx)
            b_fmt = resolve_bracket_format(len(sw), rule.bracket_format)
            bouts = generate_bouts_for_group(sw, b_fmt)
            new_groups.append(
                BracketGroup(
                    group_id=gid,
                    division=div,
                    age_group=age_grp,
                    skill_level=skill,
                    group_index=90 + idx,
                    wrestlers=sw,
                    rule=rule,
                    bracket_format=b_fmt,
                    bouts=bouts,
                    fixed_class_label=flabel,
                )
            )
    else:
        buckets: dict[tuple[str, str, str], list[Wrestler]] = defaultdict(list)
        for g in selected_groups:
            buckets[(g.division, g.age_group, g.skill_level)].extend(g.wrestlers)

        for (div, age_grp, skill), pool in buckets.items():
            pool.sort(key=lambda w: (w.weight, w.team_key, w.name))
            rule = _apply_rule_overrides(cfg.resolve_rule(div, age_grp, skill))
            if rule.mode == "fixed_classes" and rule.fixed_weight_classes:
                slices = group_fixed_classes(pool, rule)
            else:
                raw_slices = partition_madison_dp(pool, rule)
                raw_slices = optimize_adjacent_teammate_swaps(raw_slices, rule)
                slices = [(None, s) for s in raw_slices]

            for idx, (flabel, sw) in enumerate(slices, start=1):
                gid = _make_group_id(div, age_grp, skill, 90 + idx)
                b_fmt = resolve_bracket_format(len(sw), rule.bracket_format)
                bouts = generate_bouts_for_group(sw, b_fmt)
                new_groups.append(
                    BracketGroup(
                        group_id=gid,
                        division=div,
                        age_group=age_grp,
                        skill_level=skill,
                        group_index=90 + idx,
                        wrestlers=sw,
                        rule=rule,
                        bracket_format=b_fmt,
                        bouts=bouts,
                        fixed_class_label=flabel,
                    )
                )

    tournament.result.groups = remaining_groups + new_groups
    reindex_and_refresh_all_groups(tournament, renumber_ids=renumber_ids)
    w_count = sum(len(g.wrestlers) for g in new_groups)
    tournament.log(
        f"Regenerated {len(selected_groups)} bracket(s) ({', '.join(g.group_id for g in selected_groups)}) "
        f"-> {len(new_groups)} bracket(s) covering {w_count} wrestlers."
    )
    save_tournament(tournament, base_dir)
    return tournament


def find_candidate_brackets_for_walkin(
    tournament: SavedTournament,
    weight: float,
    division: str,
    age_group: str,
    skill_level: str,
    team: str = "",
) -> list[dict[str, Any]]:
    """Return matching brackets ranked by suitability for a walk-in wrestler."""
    candidates: list[dict[str, Any]] = []
    clean_team_key = team.strip().upper()

    for g in tournament.result.groups:
        if (g.division, g.age_group, g.skill_level) != (division, age_group, skill_level):
            continue

        new_min = min(g.min_weight, weight)
        new_max = max(g.max_weight, weight)
        spread_lbs = round(new_max - new_min, 2)
        spread_pct = round(((new_max - new_min) / new_min) * 100.0, 2) if new_min > 0 else 0.0
        allowed_pct = g.rule.effective_max_spread_pct(new_min)
        allowed_lbs = g.rule.effective_max_spread_lbs(new_min)
        fits_pct = spread_pct <= allowed_pct
        fits_lbs = g.rule.max_weight_spread_lbs is None or spread_lbs <= g.rule.max_weight_spread_lbs

        has_teammate = bool(clean_team_key and clean_team_key in g.team_counts)

        # Score lower is better
        score = spread_pct * 2.0
        if g.size >= g.rule.max_group_size:
            score += 200.0
        if not (fits_pct and fits_lbs):
            score += 500.0
        if has_teammate:
            score += 35.0
        score += abs((g.size + 1) - g.rule.target_group_size) * 10.0

        candidates.append(
            {
                "group_id": g.group_id,
                "current_size": g.size,
                "max_size": g.rule.max_group_size,
                "current_weights": g.weight_label,
                "new_weights": f"{new_min:g}–{new_max:g} lbs",
                "new_spread_lbs": spread_lbs,
                "new_spread_pct": spread_pct,
                "allowed_pct": allowed_pct,
                "allowed_lbs": allowed_lbs,
                "fits_spread": fits_pct and fits_lbs,
                "has_teammate": has_teammate,
                "score": score,
            }
        )

    candidates.sort(key=lambda c: c["score"])
    return candidates


def add_walkin_wrestler(
    tournament: SavedTournament,
    name: str,
    weight: float,
    team: str,
    division: str,
    age_group: str,
    skill_level: str,
    age: float | int | None = None,
    target_group_id: str = "AUTO",
    is_dual_entry: bool = False,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> tuple[SavedTournament, Wrestler, str]:
    """Add an unannounced/unregistered walk-in wrestler and place them into a bracket."""
    # Compute next unique wrestler ID
    existing_nums = [
        int(w.id.lstrip("W"))
        for w in tournament.result.wrestlers
        if w.id.startswith("W") and w.id[1:].isdigit()
    ]
    next_num = (max(existing_nums) + 1) if existing_nums else (len(tournament.result.wrestlers) + 1)
    new_wid = f"W{next_num:04d}"

    wrestler = Wrestler(
        id=new_wid,
        name=name.strip(),
        weight=round(float(weight), 2),
        age_group=age_group,
        skill_level=skill_level,
        team=team.strip() or "Unattached",
        team_tab="Walk-In",
        division=division,
        age=age,
        is_dual_entry=is_dual_entry,
        source_row=0,
        raw_age_group=age_group,
        raw_skill_level=skill_level,
    )

    placed_gid = ""

    if target_group_id == "AUTO":
        candidates = find_candidate_brackets_for_walkin(
            tournament,
            weight=wrestler.weight,
            division=division,
            age_group=age_group,
            skill_level=skill_level,
            team=wrestler.team,
        )
        # Select best candidate that has room and doesn't severely break spread
        valid_candidate = next((c for c in candidates if c["current_size"] < c["max_size"]), None)
        if valid_candidate is not None:
            target_group_id = valid_candidate["group_id"]
        else:
            target_group_id = "__NEW__"

    if target_group_id == "__NEW__":
        bucket_groups = [
            g
            for g in tournament.result.groups
            if (g.division, g.age_group, g.skill_level) == (division, age_group, skill_level)
        ]
        next_idx = max((g.group_index for g in bucket_groups), default=0) + 1
        new_gid = _make_group_id(division, age_group, skill_level, next_idx)
        existing_ids = {g.group_id for g in tournament.result.groups}
        while new_gid in existing_ids:
            next_idx += 1
            new_gid = _make_group_id(division, age_group, skill_level, next_idx)

        rule = tournament.config.resolve_rule(division, age_group, skill_level)
        new_grp = BracketGroup(
            group_id=new_gid,
            division=division,
            age_group=age_group,
            skill_level=skill_level,
            group_index=next_idx,
            wrestlers=[wrestler],
            rule=rule,
            locked=True,
            manually_modified=True,
        )
        refresh_group(new_grp)
        tournament.result.groups.append(new_grp)
        placed_gid = new_gid
    else:
        dst = next((g for g in tournament.result.groups if g.group_id == target_group_id), None)
        if dst is None:
            raise ValueError(f"Target bracket '{target_group_id}' not found.")
        dst.wrestlers.append(wrestler)
        dst.manually_modified = True
        dst.locked = True
        placed_gid = dst.group_id

    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    tournament.log(
        f"Added walk-in wrestler {wrestler.name} ({wrestler.weight:g} lbs, {wrestler.team}) "
        f"into {placed_gid} ({division} {age_group} {skill_level})."
    )
    save_tournament(tournament, base_dir)
    return tournament, wrestler, placed_gid


def scratch_wrestler(
    tournament: SavedTournament,
    wrestler_id: str,
    group_id: str | None = None,
    scratch_all_divisions: bool = True,
    reason: str = "No-show / Scratch",
    base_dir: Path = DEFAULT_STORE_DIR,
) -> tuple[SavedTournament, list[str]]:
    """Scratch/remove a wrestler from bracket(s) and save to scratched records."""
    scratched_from_gids: list[str] = []
    affected_wrestlers: list[Wrestler] = []

    for g in list(tournament.result.groups):
        if group_id and g.group_id != group_id:
            continue
        found = next((w for w in g.wrestlers if w.id == wrestler_id), None)
        if found:
            g.wrestlers = [w for w in g.wrestlers if w.id != wrestler_id]
            g.manually_modified = True
            scratched_from_gids.append(g.group_id)
            affected_wrestlers.append(found)
            if not scratch_all_divisions:
                break

    if not affected_wrestlers:
        raise ValueError(f"Wrestler '{wrestler_id}' not found in specified bracket(s).")

    # Record in scratched log
    w = affected_wrestlers[0]
    tournament.scratched_wrestlers.append(
        {
            "id": w.id,
            "name": w.name,
            "weight": w.weight,
            "team": w.team,
            "division": w.division,
            "age_group": w.age_group,
            "skill_level": w.skill_level,
            "age": w.age,
            "is_dual_entry": w.is_dual_entry,
            "original_groups": scratched_from_gids,
            "scratched_at": _now_iso(),
            "reason": reason,
        }
    )

    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    tournament.log(
        f"Scratched {w.name} ({w.weight:g} lbs, {w.team}) from {', '.join(scratched_from_gids)}. Reason: {reason}."
    )
    save_tournament(tournament, base_dir)
    return tournament, scratched_from_gids


def restore_scratched_wrestler(
    tournament: SavedTournament,
    scratch_index: int,
    target_group_id: str = "AUTO",
    base_dir: Path = DEFAULT_STORE_DIR,
) -> tuple[SavedTournament, str]:
    """Restore a previously scratched wrestler back into active brackets."""
    if scratch_index < 0 or scratch_index >= len(tournament.scratched_wrestlers):
        raise IndexError("Invalid scratch record index.")

    record = tournament.scratched_wrestlers.pop(scratch_index)
    w = Wrestler(
        id=record["id"],
        name=record["name"],
        weight=record["weight"],
        age_group=record["age_group"],
        skill_level=record["skill_level"],
        team=record["team"],
        team_tab="Restored",
        division=record["division"],
        age=record.get("age"),
        is_dual_entry=record.get("is_dual_entry", False),
    )

    # If AUTO, try restoring to one of their original brackets if still present
    chosen_gid = target_group_id
    if chosen_gid == "AUTO":
        orig_gids = record.get("original_groups", [])
        existing_gids = {g.group_id for g in tournament.result.groups}
        for og in orig_gids:
            if og in existing_gids:
                chosen_gid = og
                break
        if chosen_gid == "AUTO":
            chosen_gid = "__NEW__"

    if chosen_gid == "__NEW__":
        bucket_groups = [
            g
            for g in tournament.result.groups
            if (g.division, g.age_group, g.skill_level) == (w.division, w.age_group, w.skill_level)
        ]
        next_idx = max((g.group_index for g in bucket_groups), default=0) + 1
        new_gid = _make_group_id(w.division, w.age_group, w.skill_level, next_idx)
        rule = tournament.config.resolve_rule(w.division, w.age_group, w.skill_level)
        new_grp = BracketGroup(
            group_id=new_gid,
            division=w.division,
            age_group=w.age_group,
            skill_level=w.skill_level,
            group_index=next_idx,
            wrestlers=[w],
            rule=rule,
            locked=True,
            manually_modified=True,
        )
        refresh_group(new_grp)
        tournament.result.groups.append(new_grp)
        chosen_gid = new_gid
    else:
        target = next((g for g in tournament.result.groups if g.group_id == chosen_gid), None)
        if target is None:
            raise ValueError(f"Bracket '{chosen_gid}' not found for restoration.")
        target.wrestlers.append(w)
        target.manually_modified = True
        target.locked = True

    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    tournament.log(f"Restored previously scratched wrestler {w.name} back into {chosen_gid}.")
    save_tournament(tournament, base_dir)
    return tournament, chosen_gid

