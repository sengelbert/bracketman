"""Google Sheets and local spreadsheet roster loader and normalizer."""

from __future__ import annotations

import csv
from pathlib import Path
import re
from typing import Any
import urllib.request

from bracketman.config import TournamentConfig
from bracketman.io.xlsx import read_xlsx_sheets
from bracketman.models import Wrestler


GOOGLE_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def extract_google_sheet_id(url_or_id: str) -> str | None:
    """Extract the spreadsheet ID from a Google Sheets URL or bare ID string."""
    match = GOOGLE_SHEET_ID_RE.search(url_or_id)
    if match:
        return match.group(1)
    # If it looks like a bare Google Sheet ID (alphanumeric/hyphens, 25+ chars, not a local path)
    if (
        not Path(url_or_id).exists()
        and "/" not in url_or_id
        and "." not in url_or_id
        and len(url_or_id) >= 25
    ):
        return url_or_id
    return None


def download_google_sheet_xlsx(sheet_id: str, timeout: int = 30) -> bytes:
    """Download a public/link-shared Google Spreadsheet as .xlsx bytes (preserving all tabs)."""
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    req = urllib.request.Request(
        export_url,
        headers={"User-Agent": "Bracketman/0.1 (+https://github.com/bracketman)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _match_column_role(header_text: str, column_aliases: dict[str, list[str]]) -> str | None:
    """Match a header cell string to a canonical column role."""
    cleaned = " ".join(header_text.strip().lower().split())
    if not cleaned:
        return None
    # Exact match first
    for role, aliases in column_aliases.items():
        if cleaned == role.lower() or cleaned in [a.lower() for a in aliases]:
            return role
    # Substring match fallback
    for role, aliases in column_aliases.items():
        for alias in aliases:
            if len(alias) >= 4 and alias.lower() in cleaned:
                return role
    return None


def detect_header_row(
    rows: list[list[str]],
    column_aliases: dict[str, list[str]],
    max_scan_rows: int = 25,
) -> tuple[int, dict[str, int]] | None:
    """Scan the top rows of a sheet to find the header row and map role -> column index."""
    best_row_idx = -1
    best_mapping: dict[str, int] = {}

    for r_idx, row in enumerate(rows[:max_scan_rows]):
        mapping: dict[str, int] = {}
        for c_idx, cell in enumerate(row):
            role = _match_column_role(cell, column_aliases)
            if role and role not in mapping:
                mapping[role] = c_idx
        if "weight" in mapping and "name" in mapping and len(mapping) > len(best_mapping):
            best_row_idx = r_idx
            best_mapping = mapping

    if best_row_idx >= 0:
        return best_row_idx, best_mapping
    return None


def _resolve_divisions_for_row(
    coed_raw: str,
    girls_raw: str,
    configured_divisions: list[str],
) -> list[str]:
    """Determine which bracket division(s) a wrestler row belongs to."""
    default_div = configured_divisions[0] if configured_divisions else "Coed"
    girls_div = "Girls" if "Girls" in configured_divisions else default_div

    c_low = coed_raw.strip().lower()
    g_low = girls_raw.strip().lower()

    if "both" in c_low or "both" in g_low:
        return [default_div, girls_div] if default_div != girls_div else [default_div]

    # Handle case where someone wrote "Girls only Bracket" inside the Coed column
    if "girl" in c_low and "coed" not in c_low and "boy" not in c_low:
        return [girls_div]

    wants_coed = bool(c_low) and c_low not in ("no", "false", "0", "n")
    wants_girls = bool(g_low) and g_low not in ("no", "false", "0", "n")

    if wants_coed and wants_girls and default_div != girls_div:
        return [default_div, girls_div]
    if wants_girls:
        return [girls_div]
    return [default_div]


def parse_sheet_rows(
    sheet_name: str,
    rows: list[list[str]],
    config: TournamentConfig,
    start_id_counter: int = 1,
) -> tuple[list[Wrestler], list[dict[str, Any]]]:
    """Parse a single sheet tab into Wrestler objects and a list of skipped row diagnostics."""
    header_info = detect_header_row(rows, config.column_aliases)
    if header_info is None:
        return [], [{"sheet": sheet_name, "row": 0, "reason": "Could not detect header row"}]

    header_row_idx, col_map = header_info
    wrestlers: list[Wrestler] = []
    skipped: list[dict[str, Any]] = []
    counter = start_id_counter

    def _cell(row: list[str], role: str) -> str:
        idx = col_map.get(role)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        row_num = r_idx + 1  # 1-based spreadsheet row number

        raw_weight = _cell(row, "weight")
        raw_name = _cell(row, "name")
        raw_age_group = _cell(row, "age_group")
        raw_team = _cell(row, "team")
        raw_age = _cell(row, "age")
        raw_skill = _cell(row, "skill_level")
        raw_coed = _cell(row, "coed_bracket")
        raw_girls = _cell(row, "girls_bracket")

        # Skip template/blank rows where both name and weight are empty
        if not raw_name and not raw_weight:
            continue

        if not raw_name:
            skipped.append(
                {
                    "sheet": sheet_name,
                    "row": row_num,
                    "reason": "Missing wrestler name",
                    "weight": raw_weight,
                }
            )
            continue

        # Clean weight string (e.g. "45.5 lbs" -> 45.5)
        weight_clean = re.sub(r"[^0-9.]", "", raw_weight)
        try:
            weight = round(float(weight_clean), 2)
            if weight <= 0:
                raise ValueError("Weight must be positive")
        except ValueError:
            skipped.append(
                {
                    "sheet": sheet_name,
                    "row": row_num,
                    "name": raw_name,
                    "reason": f"Invalid or missing weight: {raw_weight!r}",
                }
            )
            continue

        age_val: float | int | None = None
        if raw_age:
            try:
                f_age = float(re.sub(r"[^0-9.]", "", raw_age))
                age_val = int(f_age) if f_age.is_integer() else f_age
            except ValueError:
                age_val = None

        age_group = config.normalize_age_group(raw_age_group, age=age_val)
        skill_level = config.normalize_skill(raw_skill)
        team = raw_team or sheet_name

        divisions = _resolve_divisions_for_row(raw_coed, raw_girls, config.divisions)
        is_dual = len(divisions) > 1

        for div in divisions:
            wrestler = Wrestler(
                id=f"W{counter:04d}",
                name=" ".join(raw_name.split()),
                weight=weight,
                age_group=age_group,
                skill_level=skill_level,
                team=team,
                team_tab=sheet_name,
                division=div,
                age=age_val,
                is_dual_entry=is_dual,
                source_row=row_num,
                raw_age_group=raw_age_group,
                raw_skill_level=raw_skill,
            )
            wrestlers.append(wrestler)
            counter += 1

    return wrestlers, skipped


def load_wrestlers(
    source: str | Path,
    config: TournamentConfig | None = None,
) -> tuple[list[Wrestler], list[dict[str, Any]], list[str]]:
    """Load wrestlers from a Google Sheet URL/ID, local .xlsx file, or local .csv file.

    Returns (wrestlers, skipped_rows, sheet_tab_names).
    """
    cfg = config or TournamentConfig()
    source_str = str(source)
    sheet_id = extract_google_sheet_id(source_str)

    raw_sheets: list[tuple[str, list[list[str]]]] = []
    if sheet_id is not None:
        xlsx_bytes = download_google_sheet_xlsx(sheet_id)
        raw_sheets = read_xlsx_sheets(xlsx_bytes)
    else:
        path = Path(source_str)
        if not path.exists():
            raise FileNotFoundError(f"Source file or Google Sheet not found: {source_str}")
        if path.suffix.lower() == ".csv":
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            raw_sheets = [(path.stem, rows)]
        else:
            raw_sheets = read_xlsx_sheets(path)

    ignored_lower = {t.lower() for t in cfg.ignored_tabs}
    all_wrestlers: list[Wrestler] = []
    all_skipped: list[dict[str, Any]] = []
    loaded_tabs: list[str] = []

    next_id = 1
    for sheet_name, rows in raw_sheets:
        if sheet_name.strip().lower() in ignored_lower:
            continue
        wrestlers, skipped = parse_sheet_rows(
            sheet_name=sheet_name,
            rows=rows,
            config=cfg,
            start_id_counter=next_id,
        )
        if wrestlers:
            loaded_tabs.append(sheet_name)
        all_wrestlers.extend(wrestlers)
        all_skipped.extend(skipped)
        next_id += len(wrestlers)

    return all_wrestlers, all_skipped, loaded_tabs
