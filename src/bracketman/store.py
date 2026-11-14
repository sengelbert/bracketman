"""Persistent tournament storage, manual bracket tweaking, and targeted bracket regeneration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from bracketman.config import TournamentConfig
from bracketman.grouping.bouts import generate_bouts_for_group, resolve_bracket_format
from bracketman.grouping.madison import (
    _find_best_merge_candidate,
    _make_group_id,
    assign_mats_to_groups,
    build_tournament_groups,
    evaluate_group_flags,
    group_fixed_classes,
    optimize_adjacent_teammate_swaps,
    partition_madison_dp,
)
from bracketman.io.loader import load_wrestlers
from bracketman.models import BracketGroup, GroupFlag, GroupRuleConfig, TournamentResult, Wrestler


DEFAULT_STORE_DIR = Path(os.environ.get("BRACKETMAN_DATA_DIR", "data/tournaments"))


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
    group.flags = []
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

    # If auto_assign_mats is enabled and any groups are unassigned, assign mats to unassigned groups
    if cfg.auto_assign_mats and cfg.mat_count and cfg.mat_count >= 1 and ordered_groups:
        if any(g.mat_number is None for g in ordered_groups):
            # If no groups had mats yet, do a full balanced pass; otherwise assign only the missing ones
            if all(g.mat_number is None for g in ordered_groups):
                assign_mats_to_groups(ordered_groups, mat_count=cfg.mat_count, strategy="balanced")
            else:
                mat_bouts: dict[int, int] = {m: 0 for m in range(1, cfg.mat_count + 1)}
                for g in ordered_groups:
                    if g.mat_number is not None and 1 <= g.mat_number <= cfg.mat_count:
                        mat_bouts[g.mat_number] += max(1, len(g.bouts))
                for idx, g in enumerate(ordered_groups):
                    if g.mat_number is None:
                        # Inherit adjacent group's mat in same division/age if available, else least-loaded mat
                        adj_mat = None
                        for neighbor in (ordered_groups[idx - 1] if idx > 0 else None, ordered_groups[idx + 1] if idx + 1 < len(ordered_groups) else None):
                            if neighbor and neighbor.division == g.division and neighbor.age_group == g.age_group and neighbor.mat_number is not None:
                                adj_mat = neighbor.mat_number
                                break
                        chosen_mat = adj_mat or min(range(1, cfg.mat_count + 1), key=lambda m: (mat_bouts[m], m))
                        g.mat_number = chosen_mat
                        mat_bouts[chosen_mat] += max(1, len(g.bouts))

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
            # Map previous mat assignments by wrestler key and bucket so unlocked wrestlers stay on their prior mats
            prev_key_mat: dict[tuple[str, str, str], int] = {}
            prev_bucket_mats: dict[tuple[str, str], list[int]] = defaultdict(list)
            for g in tournament.result.groups:
                if g.mat_number is not None:
                    prev_bucket_mats[(g.division, g.age_group)].append(g.mat_number)
                    for w in g.wrestlers:
                        prev_key_mat[(w.name.lower(), w.team_key, w.division)] = g.mat_number

            partial_res = build_tournament_groups(
                wrestlers=unlocked_wrestlers,
                config=cfg,
                source=source_str,
                skipped_rows=skipped,
            )
            for ng in partial_res.groups:
                member_mats = [
                    prev_key_mat[(w.name.lower(), w.team_key, w.division)]
                    for w in ng.wrestlers
                    if (w.name.lower(), w.team_key, w.division) in prev_key_mat
                ]
                if member_mats:
                    ng.mat_number = max(set(member_mats), key=member_mats.count)
                elif prev_bucket_mats.get((ng.division, ng.age_group)):
                    b_mats = prev_bucket_mats[(ng.division, ng.age_group)]
                    ng.mat_number = max(set(b_mats), key=b_mats.count)
                else:
                    ng.mat_number = None

            tournament.result.source = source_str
            tournament.result.skipped_rows = skipped
            tournament.result.groups = locked_groups + partial_res.groups
            reindex_and_refresh_all_groups(tournament, renumber_ids=True)
            tournament.log(
                f"Synced spreadsheet ({len(wrestlers)} entries across {len(tabs)} tabs) "
                f"preserving {len(locked_groups)} locked/tweaked bracket(s) and mat assignments."
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
            mat_number=src_group.mat_number,
        )
        refresh_group(new_grp)
        tournament.result.groups.append(new_grp)
        dest_id_label = new_gid
    else:
        dst_group = next((g for g in tournament.result.groups if g.group_id == to_group_id), None)
        if dst_group is None:
            raise ValueError(f"Target bracket '{to_group_id}' not found.")
        # Ensure wrestler does not already have an active entry in dst_group.division
        existing_same_div = next(
            (
                g
                for g in tournament.result.groups
                if g.group_id != from_group_id
                and g.division == dst_group.division
                and any(
                    cw.name.strip().lower() == wrestler.name.strip().lower()
                    and cw.team_key == wrestler.team_key
                    for cw in g.wrestlers
                )
            ),
            None,
        )
        if existing_same_div is not None:
            raise ValueError(
                f"Cannot move {wrestler.name} into {dst_group.group_id} ({dst_group.division}) because "
                f"{wrestler.name} is already in {existing_same_div.group_id} ({existing_same_div.division}). "
                f"Each wrestler can be in at most 1 Coed and 1 Girls bracket."
            )
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

    # Guard against merging a wrestler into a division where they ALREADY have an active bracket
    for w in src.wrestlers:
        existing_same_div = next(
            (
                g
                for g in tournament.result.groups
                if g.group_id != source_group_id
                and g.division == dst.division
                and any(
                    cw.name.strip().lower() == w.name.strip().lower()
                    and cw.team_key == w.team_key
                    for cw in g.wrestlers
                )
            ),
            None,
        )
        if existing_same_div is not None:
            raise ValueError(
                f"Cannot merge {source_group_id} ({w.name}) into {target_group_id} ({dst.division}) "
                f"because {w.name} is already in {existing_same_div.group_id} ({existing_same_div.division}). "
                f"Each wrestler can be in at most 1 Coed and 1 Girls bracket."
            )

    names = ", ".join(w.name for w in src.wrestlers)
    dst.wrestlers.extend(src.wrestlers)
    if dst.mat_number is None and src.mat_number is not None:
        dst.mat_number = src.mat_number
    src.wrestlers = []
    dst.manually_modified = True
    dst.locked = True

    reindex_and_refresh_all_groups(tournament, renumber_ids=renumber_ids)
    tournament.log(f"Merged bracket {source_group_id} ({names}) into {target_group_id}.")
    save_tournament(tournament, base_dir)
    return tournament


def merge_multiple_brackets(
    tournament: SavedTournament,
    source_group_ids: list[str],
    target_group_id: str,
    renumber_ids: bool = False,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Atomically merge all wrestlers from one or more `source_group_ids` into `target_group_id`."""
    unique_sources = list(dict.fromkeys(gid for gid in source_group_ids if gid))
    if not unique_sources:
        raise ValueError("Select at least one source bracket to merge.")
    if target_group_id in unique_sources:
        raise ValueError("Target bracket cannot also be in the source brackets list.")

    dst = next((g for g in tournament.result.groups if g.group_id == target_group_id), None)
    if dst is None:
        raise ValueError(f"Target bracket '{target_group_id}' not found.")

    src_groups: list[BracketGroup] = []
    for sid in unique_sources:
        src = next((g for g in tournament.result.groups if g.group_id == sid), None)
        if src is None:
            raise ValueError(f"Source bracket '{sid}' not found.")
        src_groups.append(src)

    # Validate division uniqueness before mutating any group
    seen_incoming: dict[tuple[str, str], str] = {}
    for src in src_groups:
        for w in src.wrestlers:
            w_key = (w.name.strip().lower(), w.team_key)
            if w_key in seen_incoming:
                raise ValueError(
                    f"Cannot merge {src.group_id} ({w.name}) into {target_group_id} ({dst.division}) "
                    f"because {w.name} is also in {seen_incoming[w_key]}."
                )
            seen_incoming[w_key] = src.group_id

            existing_same_div = next(
                (
                    g
                    for g in tournament.result.groups
                    if g.group_id != src.group_id
                    and g.division == dst.division
                    and any(
                        cw.name.strip().lower() == w.name.strip().lower()
                        and cw.team_key == w.team_key
                        for cw in g.wrestlers
                    )
                ),
                None,
            )
            if existing_same_div is not None:
                raise ValueError(
                    f"Cannot merge {src.group_id} ({w.name}) into {target_group_id} ({dst.division}) "
                    f"because {w.name} is already in {existing_same_div.group_id} ({existing_same_div.division}). "
                    f"Each wrestler can be in at most 1 Coed and 1 Girls bracket."
                )

    merged_names: list[str] = []
    for src in src_groups:
        merged_names.extend(w.name for w in src.wrestlers)
        dst.wrestlers.extend(src.wrestlers)
        if dst.mat_number is None and src.mat_number is not None:
            dst.mat_number = src.mat_number
        src.wrestlers = []

    dst.manually_modified = True
    dst.locked = True

    reindex_and_refresh_all_groups(tournament, renumber_ids=renumber_ids)
    tournament.log(
        f"Merged {', '.join(unique_sources)} ({', '.join(merged_names)}) into {target_group_id}."
    )
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
    division: str | None = None,
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
        division=division if division is not None else old_w.division,
        age=old_w.age,
        is_dual_entry=old_w.is_dual_entry,
        source_row=old_w.source_row,
        raw_age_group=old_w.raw_age_group,
        raw_skill_level=old_w.raw_skill_level,
    )
    grp.wrestlers = [new_w if w.id == wrestler_id else w for w in grp.wrestlers]
    grp.manually_modified = True
    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    changes = [f"weight: {old_w.weight:g} -> {new_w.weight:g} lbs"]
    if old_w.skill_level != new_w.skill_level:
        changes.append(f"skill: {old_w.skill_level} -> {new_w.skill_level}")
    if old_w.age_group != new_w.age_group:
        changes.append(f"age: {old_w.age_group} -> {new_w.age_group}")
    if old_w.division != new_w.division:
        changes.append(f"division: {old_w.division} -> {new_w.division}")
    tournament.log(
        f"Updated wrestler {new_w.name} in {group_id} ({', '.join(changes)})."
    )
    save_tournament(tournament, base_dir)
    return tournament


def _resolve_inherited_mat(
    wrestlers: list[Wrestler],
    wrestler_mat_map: dict[str, int],
    fallback_mats: list[int],
    idx: int = 0,
) -> int | None:
    """Determine the best mat_number for a newly formed pod from its wrestlers' prior mat assignments."""
    member_mats = [wrestler_mat_map[w.id] for w in wrestlers if w.id in wrestler_mat_map]
    if member_mats:
        # Pick the modal (most common) mat among the wrestlers in this pod
        return max(set(member_mats), key=member_mats.count)
    if fallback_mats:
        return fallback_mats[min(idx, len(fallback_mats) - 1)]
    return None


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
    - Preserves the mat assignments (`mat_number`) of the selected brackets so regenerated
      pods stay on the same scoring table/mat.
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

    wrestler_mat_map: dict[str, int] = {
        w.id: g.mat_number
        for g in selected_groups
        if g.mat_number is not None
        for w in g.wrestlers
    }
    selected_mats = [g.mat_number for g in selected_groups if g.mat_number is not None]

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
            inherited_mat = _resolve_inherited_mat(sw, wrestler_mat_map, selected_mats, idx - 1)
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
                    mat_number=inherited_mat,
                )
            )
    else:
        buckets: dict[tuple[str, str, str], list[Wrestler]] = defaultdict(list)
        bucket_mats: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for g in selected_groups:
            buckets[(g.division, g.age_group, g.skill_level)].extend(g.wrestlers)
            if g.mat_number is not None:
                bucket_mats[(g.division, g.age_group, g.skill_level)].append(g.mat_number)

        for (div, age_grp, skill), pool in buckets.items():
            pool.sort(key=lambda w: (w.weight, w.team_key, w.name))
            rule = _apply_rule_overrides(cfg.resolve_rule(div, age_grp, skill))
            if rule.mode == "fixed_classes" and rule.fixed_weight_classes:
                slices = group_fixed_classes(pool, rule)
            else:
                raw_slices = partition_madison_dp(pool, rule)
                raw_slices = optimize_adjacent_teammate_swaps(raw_slices, rule)
                slices = [(None, s) for s in raw_slices]

            b_mats = bucket_mats.get((div, age_grp, skill), selected_mats)
            for idx, (flabel, sw) in enumerate(slices, start=1):
                gid = _make_group_id(div, age_grp, skill, 90 + idx)
                b_fmt = resolve_bracket_format(len(sw), rule.bracket_format)
                bouts = generate_bouts_for_group(sw, b_fmt)
                inherited_mat = _resolve_inherited_mat(sw, wrestler_mat_map, b_mats, idx - 1)
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
                        mat_number=inherited_mat,
                    )
                )

    tournament.result.groups = remaining_groups + new_groups
    reindex_and_refresh_all_groups(tournament, renumber_ids=renumber_ids)
    w_count = sum(len(g.wrestlers) for g in new_groups)
    tournament.log(
        f"Regenerated {len(selected_groups)} bracket(s) ({', '.join(g.group_id for g in selected_groups)}) "
        f"-> {len(new_groups)} bracket(s) covering {w_count} wrestlers (preserved mat assignments)."
    )
    save_tournament(tournament, base_dir)
    return tournament


def reoptimize_active_brackets(
    tournament: SavedTournament,
    division: str | None = None,
    age_group: str | None = None,
    preserve_locked: bool = True,
    target_group_size: int | None = None,
    max_group_size: int | None = None,
    min_group_size: int | None = None,
    max_weight_spread_pct: float | None = None,
    separate_teammates: bool | None = None,
    blend_skills: bool | None = None,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> tuple[SavedTournament, int, int]:
    """Re-run Madison grouping on active wrestlers in the specified scope (division/age or whole tournament).

    - Excludes scratched wrestlers (they are already removed from active groups).
    - Includes all active walk-ins.
    - If preserve_locked is True, brackets marked locked/manually modified are preserved untouched.
    - Regroups the unlocked active wrestlers using Madison dynamic programming while keeping
      each newly formed bracket on the mat its wrestlers/age-group were already assigned to.
    - Returns (tournament, original_bracket_count_in_scope, new_bracket_count_in_scope).
    """
    cfg = tournament.config

    matching_groups: list[BracketGroup] = []
    other_groups: list[BracketGroup] = []
    for g in tournament.result.groups:
        match_div = division is None or division == "ALL" or g.division == division
        match_age = age_group is None or age_group == "ALL" or g.age_group == age_group
        if match_div and match_age:
            matching_groups.append(g)
        else:
            other_groups.append(g)

    if not matching_groups:
        raise ValueError("No brackets match the selected division and age group.")

    if preserve_locked:
        locked_in_scope = [g for g in matching_groups if g.locked or g.manually_modified]
        unlocked_in_scope = [g for g in matching_groups if not (g.locked or g.manually_modified)]
    else:
        locked_in_scope = []
        unlocked_in_scope = matching_groups

    if not unlocked_in_scope:
        raise ValueError(
            "All matching brackets are currently locked. Unlock them or uncheck 'Preserve locked brackets' to re-optimize."
        )

    pool = [w for g in unlocked_in_scope for w in g.wrestlers]
    if not pool:
        raise ValueError("No active wrestlers found in the selected unlocked brackets.")

    # Capture existing mat assignments from unlocked_in_scope so re-optimized pods stay on their prior mats
    wrestler_mat_map: dict[str, int] = {
        w.id: g.mat_number
        for g in unlocked_in_scope
        if g.mat_number is not None
        for w in g.wrestlers
    }
    bucket_mats: dict[tuple[str, str], list[int]] = defaultdict(list)
    for g in matching_groups:
        if g.mat_number is not None:
            bucket_mats[(g.division, g.age_group)].append(g.mat_number)

    re_cfg = TournamentConfig.from_dict(cfg.to_dict())
    if target_group_size is not None:
        re_cfg.default_rule.target_group_size = target_group_size
    if max_group_size is not None:
        re_cfg.default_rule.max_group_size = max_group_size
    if min_group_size is not None:
        re_cfg.default_rule.min_group_size = min_group_size
    if max_weight_spread_pct is not None:
        re_cfg.default_rule.max_weight_spread_pct = max_weight_spread_pct
    if separate_teammates is not None:
        re_cfg.default_rule.separate_teammates = separate_teammates
    if blend_skills is not None:
        re_cfg.blend_skills_to_fill_brackets = blend_skills
        cfg.blend_skills_to_fill_brackets = blend_skills

    new_res = build_tournament_groups(
        wrestlers=pool,
        config=re_cfg,
        source=tournament.result.source,
    )

    # Restore sticky mat assignments onto new_res.groups so mats don't get reshuffled
    if wrestler_mat_map or bucket_mats:
        for idx, ng in enumerate(new_res.groups):
            b_mats = bucket_mats.get((ng.division, ng.age_group), [])
            inherited_mat = _resolve_inherited_mat(ng.wrestlers, wrestler_mat_map, b_mats, idx)
            if inherited_mat is not None:
                ng.mat_number = inherited_mat

    tournament.result.groups = other_groups + locked_in_scope + new_res.groups
    reindex_and_refresh_all_groups(tournament, renumber_ids=True)

    scope_parts = []
    if division and division != "ALL":
        scope_parts.append(division)
    if age_group and age_group != "ALL":
        scope_parts.append(age_group)
    scope_str = " ".join(scope_parts) if scope_parts else "Whole Tournament"

    tournament.log(
        f"Re-optimized {len(unlocked_in_scope)} bracket(s) in {scope_str} "
        f"({len(pool)} wrestlers) -> {len(new_res.groups)} bracket(s) "
        f"(preserved {len(locked_in_scope)} locked and kept mat assignments)."
    )
    save_tournament(tournament, base_dir)
    return tournament, len(unlocked_in_scope), len(new_res.groups)


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
                "mat_number": g.mat_number,
                "mat_label": g.mat_label,
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

        # Inherit mat from the closest-weight bracket in the same division/age if available
        same_age_groups = [
            g
            for g in tournament.result.groups
            if g.division == division and g.age_group == age_group and g.mat_number is not None
        ]
        inherited_mat = None
        if same_age_groups:
            closest_grp = min(same_age_groups, key=lambda g: abs(g.min_weight - wrestler.weight))
            inherited_mat = closest_grp.mat_number

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
            mat_number=inherited_mat,
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
    original_mats: dict[str, int | None] = {}
    affected_wrestlers: list[Wrestler] = []

    for g in list(tournament.result.groups):
        if group_id and g.group_id != group_id:
            continue
        found = next((w for w in g.wrestlers if w.id == wrestler_id), None)
        if found:
            g.wrestlers = [w for w in g.wrestlers if w.id != wrestler_id]
            g.manually_modified = True
            g.locked = True
            scratched_from_gids.append(g.group_id)
            original_mats[g.group_id] = g.mat_number
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
            "original_mats": original_mats,
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
    orig_gids = record.get("original_groups", [])
    orig_mats = record.get("original_mats", {}) or {}
    if chosen_gid == "AUTO":
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
        new_gid = (
            orig_gids[0]
            if (orig_gids and orig_gids[0] != "NO MATCH" and orig_gids[0] not in {g.group_id for g in tournament.result.groups})
            else _make_group_id(w.division, w.age_group, w.skill_level, next_idx)
        )
        restored_mat = next((orig_mats.get(og) for og in orig_gids if orig_mats.get(og) is not None), None)
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
            mat_number=restored_mat,
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


def assign_brackets_to_mats(
    tournament: SavedTournament,
    mat_count: int | None = None,
    strategy: str = "balanced",
    division: str | None = None,
    age_group: str | None = None,
    skill_level: str | None = None,
    preserve_locked: bool = False,
    lock_assigned: bool = False,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Assign brackets in `tournament` (or a division/age/skill subset) to mats `1..mat_count`."""
    if mat_count is not None and mat_count >= 1:
        tournament.config.mat_count = int(mat_count)
    effective_mats = max(1, int(tournament.config.mat_count))

    target_groups = [
        g
        for g in tournament.result.groups
        if (division is None or division in ("", "All", "ALL") or g.division == division)
        and (age_group is None or age_group in ("", "All", "ALL") or g.age_group == age_group)
        and (skill_level is None or skill_level in ("", "All", "ALL") or g.skill_level == skill_level)
    ]
    if not target_groups:
        raise ValueError("No brackets match the selected division/age/skill filter for mat assignment.")

    assign_mats_to_groups(
        target_groups,
        mat_count=effective_mats,
        strategy=strategy,
        preserve_existing_locked=preserve_locked,
    )
    if lock_assigned:
        for g in target_groups:
            if g.mat_number is not None:
                g.locked = True

    scope_lbl = "All Brackets"
    if division and division not in ("All", "ALL"):
        scope_lbl = division
    if age_group and age_group not in ("All", "ALL"):
        scope_lbl = f"{scope_lbl} {age_group}" if scope_lbl != "All Brackets" else age_group
    if skill_level and skill_level not in ("All", "ALL"):
        scope_lbl = f"{scope_lbl} {skill_level}" if scope_lbl != "All Brackets" else skill_level

    lock_note = ", locked assignments" if lock_assigned else ""
    tournament.log(
        f"Assigned {len(target_groups)} bracket(s) ({scope_lbl}) across {effective_mats} mat(s) "
        f"(strategy: {strategy}{lock_note})."
    )
    save_tournament(tournament, base_dir)
    return tournament


def set_bracket_mat(
    tournament: SavedTournament,
    group_ids: list[str] | str,
    mat_number: int | None,
    lock_bracket: bool = True,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> SavedTournament:
    """Manually assign one or more bracket IDs to a specific Mat / Table number (or None to unassign)."""
    if isinstance(group_ids, str):
        group_ids = [group_ids]
    target_set = set(group_ids)
    updated: list[str] = []
    for g in tournament.result.groups:
        if g.group_id in target_set:
            g.mat_number = int(mat_number) if mat_number is not None else None
            if lock_bracket and mat_number is not None:
                g.locked = True
            updated.append(g.group_id)

    if not updated:
        raise ValueError(f"Bracket(s) not found: {', '.join(group_ids)}")

    mat_str = f"Mat {mat_number}" if mat_number is not None else "Unassigned"
    tournament.log(f"Assigned bracket(s) {', '.join(updated)} -> {mat_str}.")
    save_tournament(tournament, base_dir)
    return tournament


def search_tournament_wrestlers(
    tournament: SavedTournament,
    query: str = "",
    division: str = "All",
    age_group: str = "All",
    skill_level: str = "All",
    team: str = "All",
    status: str = "All",
    mat_number: str | int = "All",
) -> list[dict[str, Any]]:
    """Search active and scratched wrestlers in `tournament` with full bracket, mat, and bout context.

    `status`:
      - `"All"`: Active and Scratched entries
      - `"Active"`: Only active entries in brackets
      - `"Scratched"`: Only scratched entries
      - `"Flagged"`: Only active entries in brackets with warnings/flags
      - `"Dual-Entry"`: Only dual-entry wrestlers
    """
    q = query.strip().lower()
    tokens = [tok for tok in q.split() if tok]
    results: list[dict[str, Any]] = []

    def _matches_query(fields: list[str]) -> bool:
        if not q:
            return True
        lowered_fields = [f.lower() for f in fields if f]
        combined = " ".join(lowered_fields)
        if q in combined:
            return True
        words = re.findall(r"[a-z0-9.\-]+", combined)
        return all(
            any((w == tok if len(tok) == 1 else tok in w) for w in words)
            for tok in tokens
        )

    if status in ("All", "Active", "Flagged", "Dual-Entry"):
        for g in tournament.result.groups:
            if division != "All" and g.division != division:
                continue
            if age_group != "All" and g.age_group != age_group:
                continue
            if skill_level != "All" and g.skill_level != skill_level:
                continue
            if status == "Flagged" and not g.has_warnings:
                continue
            if mat_number != "All":
                if str(mat_number) == "Unassigned":
                    if g.mat_number is not None:
                        continue
                else:
                    mat_int = int(str(mat_number).replace("Mat", "").strip())
                    if g.mat_number != mat_int:
                        continue

            for seed_idx, w in enumerate(g.wrestlers, start=1):
                if status == "Dual-Entry" and not w.is_dual_entry:
                    continue
                if team != "All" and w.display_team != team and w.team != team:
                    continue
                mat_search_token = f"mat {g.mat_number} mat{g.mat_number}" if g.mat_number else "unassigned"
                if not _matches_query(
                    [
                        w.id,
                        w.name,
                        w.team,
                        w.team_tab,
                        w.display_team,
                        g.group_id,
                        g.division,
                        g.age_group,
                        g.skill_level,
                        f"{w.weight:g}",
                        mat_search_token,
                    ]
                ):
                    continue

                w_bouts: list[dict[str, Any]] = []
                for b in g.bouts:
                    if b.wrestler_a.id == w.id:
                        opp = b.wrestler_b
                        w_bouts.append(
                            {
                                "bout_number": b.bout_number,
                                "round_number": b.round_number,
                                "opponent_name": opp.name if opp else "BYE",
                                "opponent_weight": opp.weight if opp else None,
                                "opponent_team": opp.display_team if opp else "",
                                "is_teammate": b.is_teammate_match,
                            }
                        )
                    elif b.wrestler_b and b.wrestler_b.id == w.id:
                        opp = b.wrestler_a
                        w_bouts.append(
                            {
                                "bout_number": b.bout_number,
                                "round_number": b.round_number,
                                "opponent_name": opp.name,
                                "opponent_weight": opp.weight,
                                "opponent_team": opp.display_team,
                                "is_teammate": b.is_teammate_match,
                            }
                        )

                results.append(
                    {
                        "status": "Active",
                        "wrestler": w,
                        "group": g,
                        "group_id": g.group_id,
                        "mat_number": g.mat_number,
                        "seed": seed_idx,
                        "bouts": w_bouts,
                        "scratch_index": None,
                        "scratch_record": None,
                    }
                )

    if status in ("All", "Scratched", "No Match", "Dual-Entry", "Flagged") and mat_number == "All":
        for s_idx, rec in enumerate(tournament.scratched_wrestlers):
            is_no_match = rec.get("entry_status") == "no_match"
            rec_status_label = "No Match" if is_no_match else "Scratched"
            if status == "Scratched" and is_no_match:
                continue
            if status in ("No Match", "Flagged") and not is_no_match:
                continue
            if status == "Dual-Entry" and not rec.get("is_dual_entry", False):
                continue
            r_div = str(rec.get("division", "Coed"))
            r_age = str(rec.get("age_group", ""))
            r_skill = str(rec.get("skill_level", ""))
            r_team = str(rec.get("team", ""))
            if division != "All" and r_div != division:
                continue
            if age_group != "All" and r_age != age_group:
                continue
            if skill_level != "All" and r_skill != skill_level:
                continue
            if team != "All" and r_team != team:
                continue

            orig_groups_str = "NO MATCH" if is_no_match else " ".join(rec.get("original_groups", []))
            if not _matches_query(
                [
                    str(rec.get("id", "")),
                    str(rec.get("name", "")),
                    r_team,
                    orig_groups_str,
                    "no match" if is_no_match else "scratched",
                    r_div,
                    r_age,
                    r_skill,
                    str(rec.get("weight", "")),
                    str(rec.get("reason", "")),
                ]
            ):
                continue

            w_scratched = Wrestler(
                id=str(rec.get("id", "")),
                name=str(rec.get("name", "")),
                weight=float(rec.get("weight", 0.0)),
                age_group=r_age,
                skill_level=r_skill,
                team=r_team,
                team_tab="No Match" if is_no_match else "Scratched",
                division=r_div,
                age=rec.get("age"),
                is_dual_entry=bool(rec.get("is_dual_entry", False)),
            )
            results.append(
                {
                    "status": rec_status_label,
                    "wrestler": w_scratched,
                    "group": None,
                    "group_id": "NO MATCH" if is_no_match else ", ".join(rec.get("original_groups", [])),
                    "mat_number": None,
                    "seed": None,
                    "bouts": [],
                    "scratch_index": s_idx,
                    "scratch_record": rec,
                }
            )

    results.sort(
        key=lambda item: (
            0 if item["status"] in ("Active", "No Match") else 1,
            item["wrestler"].name.lower(),
            item["wrestler"].division,
            item["wrestler"].weight,
        )
    )
    return results


def find_duplicate_division_entries(
    tournament: SavedTournament,
) -> list[dict[str, Any]]:
    """Find any wrestler who appears in more than 1 active bracket of the same division (Coed or Girls)."""
    by_w_div: dict[tuple[str, str, str], list[tuple[BracketGroup, Wrestler]]] = {}
    for g in tournament.result.groups:
        for w in g.wrestlers:
            key = (w.name.strip().lower(), w.team_key, g.division)
            by_w_div.setdefault(key, []).append((g, w))

    duplicates: list[dict[str, Any]] = []
    for (name_lower, team_key, bracket_div), entries in by_w_div.items():
        if len(entries) > 1:
            duplicates.append(
                {
                    "name": entries[0][1].name,
                    "team_key": team_key,
                    "bracket_division": bracket_div,
                    "entries": entries,
                }
            )
    return duplicates


def enforce_max_one_bracket_per_division(
    tournament: SavedTournament,
    base_dir: Path = DEFAULT_STORE_DIR,
) -> tuple[SavedTournament, list[str]]:
    """Ensure every wrestler is in at most 1 Coed bracket and at most 1 Girls bracket.

    - If a dual-entry wrestler had their Girls entry merged into a Coed bracket while already
      in another Coed bracket (e.g. Kai McBride or Kenlea McBride), removes the misplaced
      Girls entry from the second Coed bracket and either:
        1. Places it into the best compatible Girls bracket (same or adjacent age group within
           weight spread tolerance), OR
        2. Marks the unmatched entry with `entry_status="no_match"` (`NO MATCH`) if no Girls
           bracket is within safe weight range.
    - If a wrestler has two identical-division entries in the same division, removes the duplicate.
    """
    cfg = tournament.config
    age_order = {ag: i for i, ag in enumerate(cfg.age_groups)}
    actions: list[str] = []

    duplicates = find_duplicate_division_entries(tournament)
    if not duplicates:
        return tournament, actions

    for dup_info in duplicates:
        bracket_div = dup_info["bracket_division"]
        entries: list[tuple[BracketGroup, Wrestler]] = dup_info["entries"]
        # Sort so native entry (w.division == g.division) is kept first
        entries_sorted = sorted(
            entries,
            key=lambda gw: (0 if gw[1].division == gw[0].division else 1, gw[0].group_id),
        )
        kept_group, kept_w = entries_sorted[0]

        for dup_group, dup_w in entries_sorted[1:]:
            dup_group.wrestlers = [w for w in dup_group.wrestlers if w.id != dup_w.id]
            dup_group.manually_modified = True
            dup_group.locked = True

            # Check if dup_w was originally registered for another division (e.g. Girls)
            # and whether this wrestler already has an active bracket in dup_w.division
            already_in_native_div = any(
                g.division == dup_w.division
                and g.size > 0
                and any(
                    cw.name.strip().lower() == dup_w.name.strip().lower()
                    and cw.team_key == dup_w.team_key
                    for cw in g.wrestlers
                )
                for g in tournament.result.groups
            )

            if dup_w.division != bracket_div and not already_in_native_div:
                # Find best compatible bracket in dup_w.division (e.g. Girls)
                w_age_idx = age_order.get(dup_w.age_group, -99)
                best_cand: BracketGroup | None = None
                best_score = 999999.0
                for cand in tournament.result.groups:
                    if cand.division != dup_w.division or cand.size == 0:
                        continue
                    if cand.size >= cand.rule.max_group_size:
                        continue
                    cand_age_idx = age_order.get(cand.age_group, -99)
                    age_diff = abs(cand_age_idx - w_age_idx)
                    if age_diff > 1:
                        continue
                    new_min = min(cand.min_weight, dup_w.weight)
                    new_max = max(cand.max_weight, dup_w.weight)
                    spread_pct = ((new_max - new_min) / new_min * 100.0) if new_min > 0 else 0.0
                    max_pct = cand.rule.effective_max_spread_pct(new_min) or 12.0
                    if spread_pct > max_pct * 1.35:
                        continue
                    score = age_diff * 25.0 + (0.0 if cand.skill_level == dup_w.skill_level else 10.0) + spread_pct * 2.0
                    if score < best_score:
                        best_score = score
                        best_cand = cand

                if best_cand is not None:
                    best_cand.wrestlers.append(dup_w)
                    best_cand.manually_modified = True
                    best_cand.locked = True
                    msg = (
                        f"Re-homed {dup_w.name} ({dup_w.id}, {dup_w.weight:g} lbs {dup_w.division}) "
                        f"from duplicate {bracket_div} bracket {dup_group.group_id} -> {best_cand.group_id} "
                        f"(keeping {kept_w.name} in {kept_group.group_id})."
                    )
                    actions.append(msg)
                    tournament.log(msg)
                else:
                    tournament.scratched_wrestlers.append(
                        {
                            "id": dup_w.id,
                            "name": dup_w.name,
                            "weight": dup_w.weight,
                            "age_group": dup_w.age_group,
                            "skill_level": dup_w.skill_level,
                            "team": dup_w.team_key,
                            "division": dup_w.division,
                            "age": dup_w.age,
                            "is_dual_entry": dup_w.is_dual_entry,
                            "entry_status": "no_match",
                            "original_groups": ["NO MATCH"],
                            "original_mats": {},
                            "reason": (
                                f"NO MATCH — No {dup_w.division} opponent within weight range "
                                f"(active in {kept_group.group_id})"
                            ),
                            "scratched_at": _now_iso(),
                        }
                    )
                    msg = (
                        f"Marked {dup_w.name} ({dup_w.id}, {dup_w.weight:g} lbs {dup_w.division}) as NO MATCH "
                        f"(removed duplicate {bracket_div} entry from {dup_group.group_id}; kept active in {kept_group.group_id})."
                    )
                    actions.append(msg)
                    tournament.log(msg)
            else:
                msg = (
                    f"Removed duplicate {bracket_div} entry for {dup_w.name} ({dup_w.id}, {dup_w.weight:g} lbs) "
                    f"from {dup_group.group_id} (kept in {kept_group.group_id})."
                )
                actions.append(msg)
                tournament.log(msg)

    reindex_and_refresh_all_groups(tournament, renumber_ids=False)
    save_tournament(tournament, base_dir)
    return tournament, actions


def verify_tournament_roster_and_brackets(
    tournament: SavedTournament,
) -> dict[str, Any]:
    """Verify tournament integrity:

    1. Checks all registered/active wrestlers are in at least one bracket.
    2. Identifies any unbracketed wrestlers (in result.wrestlers but missing from groups).
    3. Identifies NO MATCH entries in scratched_wrestlers (entry_status == 'no_match').
    4. Identifies solo (1-man) brackets where a wrestler has no opponents.
    5. Identifies duplicate division entries (more than 1 Coed or Girls bracket).
    """
    dup_div_entries = find_duplicate_division_entries(tournament)

    # Map wrestler ids to brackets
    bracketed_wrestler_ids: dict[str, list[BracketGroup]] = defaultdict(list)
    for g in tournament.result.groups:
        for w in g.wrestlers:
            bracketed_wrestler_ids[w.id].append(g)

    # Check for unbracketed in tournament.result.wrestlers
    unbracketed: list[Wrestler] = []
    seen_unbracketed_ids = set()
    for w in tournament.result.wrestlers:
        if w.id not in bracketed_wrestler_ids and w.id not in seen_unbracketed_ids:
            unbracketed.append(w)
            seen_unbracketed_ids.add(w.id)

    # Check NO MATCH entries in scratched_wrestlers
    no_match_entries: list[dict[str, Any]] = [
        sc for sc in tournament.scratched_wrestlers if sc.get("entry_status") == "no_match"
    ]

    # Check solo (1-man) brackets
    solo_brackets: list[BracketGroup] = [g for g in tournament.result.groups if g.size == 1]

    # Scratches (excluding no_match)
    actual_scratches = [
        sc for sc in tournament.scratched_wrestlers if sc.get("entry_status") != "no_match"
    ]

    total_active_wrestlers = sum(g.size for g in tournament.result.groups)
    all_clear = (
        len(dup_div_entries) == 0
        and len(unbracketed) == 0
        and len(no_match_entries) == 0
        and len(solo_brackets) == 0
    )

    return {
        "all_clear": all_clear,
        "total_active_wrestlers": total_active_wrestlers,
        "total_brackets": len(tournament.result.groups),
        "dup_div_entries": dup_div_entries,
        "unbracketed_wrestlers": unbracketed,
        "no_match_entries": no_match_entries,
        "solo_brackets": solo_brackets,
        "scratched_count": len(actual_scratches),
    }



