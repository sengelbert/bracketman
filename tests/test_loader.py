"""Tests for spreadsheet parsing, header auto-detection, and normalization."""

from pathlib import Path

from bracketman.config import TournamentConfig
from bracketman.io.loader import (
    detect_header_row,
    extract_google_sheet_id,
    load_wrestlers,
    parse_sheet_rows,
)
from bracketman.io.xlsx import read_xlsx_sheets, write_xlsx_sheets


def test_extract_google_sheet_id():
    url = "https://docs.google.com/spreadsheets/d/1VWSHOuqCDildUjOL7BdS7CQ4OdJ6K78m8Osr3RjqoLY/edit?usp=drivesdk"
    assert extract_google_sheet_id(url) == "1VWSHOuqCDildUjOL7BdS7CQ4OdJ6K78m8Osr3RjqoLY"
    assert extract_google_sheet_id("local_file.xlsx") is None


def test_detect_header_row_with_instruction_preamble():
    cfg = TournamentConfig()
    rows = [
        ["Age groups: 6U, 8U, 10U, 12U & 14U"],
        ["Ability: Novice = 1st & 2nd year wrestlers"],
        [],
        ["Bracket: Place an X indicating division"],
        [
            "Weight",
            "Wrestlers Name",
            "Age Group",
            "School",
            "Age",
            "Ability (Novice or experienced)",
            "Boys / COED Bracket",
            "Girls only Bracket",
        ],
        ["45.0", "Alex Smith", "6u", "AR", "6", "Novice", "X", ""],
    ]
    res = detect_header_row(rows, cfg.column_aliases)
    assert res is not None
    header_idx, col_map = res
    assert header_idx == 4
    assert col_map["weight"] == 0
    assert col_map["name"] == 1
    assert col_map["age_group"] == 2
    assert col_map["team"] == 3
    assert col_map["skill_level"] == 5
    assert col_map["coed_bracket"] == 6
    assert col_map["girls_bracket"] == 7


def test_parse_sheet_rows_normalizes_typos_and_dual_entries():
    cfg = TournamentConfig()
    rows = [
        [
            "Weight",
            "Wrestlers Name",
            "Age Group",
            "School",
            "Age",
            "Ability (Novice or experienced)",
            "Boys / COED Bracket",
            "Girls only Bracket",
        ],
        ["37.5", "Jaxon Bloemen", "6u", "AR", "4.0", "Novice", "Coed Bracket", ""],
        ["70.0", "Nora Kim", "10u", "ASC", "10.0", "experianced", "x", "x"],
        ["62.0", "Olivia Alex", "8U", "AR", "8.0", "Experienced", "Girls only Bracket", "Girls Only"],
        ["", "", "", "AR", "", "", "", ""],  # Pre-filled template row with no wrestler
    ]
    wrestlers, skipped = parse_sheet_rows("Arapahoe", rows, cfg)
    assert len(skipped) == 0
    # Row 1 -> 1 Coed entry; Row 2 -> 2 entries (Coed + Girls); Row 3 -> 1 Girls entry
    assert len(wrestlers) == 4

    w1 = wrestlers[0]
    assert w1.name == "Jaxon Bloemen"
    assert w1.age_group == "6U"
    assert w1.skill_level == "Beginner"
    assert w1.division == "Coed"
    assert not w1.is_dual_entry

    w2_coed, w2_girls = wrestlers[1], wrestlers[2]
    assert w2_coed.name == "Nora Kim"
    assert w2_coed.age_group == "10U"
    assert w2_coed.skill_level == "Advanced"
    assert w2_coed.division == "Coed"
    assert w2_coed.is_dual_entry
    assert w2_girls.division == "Girls"
    assert w2_girls.is_dual_entry

    w3 = wrestlers[3]
    assert w3.name == "Olivia Alex"
    assert w3.division == "Girls"
    assert not w3.is_dual_entry


def test_xlsx_roundtrip_and_loader(tmp_path: Path):
    xlsx_file = tmp_path / "sample_rosters.xlsx"
    sheets = [
        (
            "Team Alpha",
            [
                ["Weight", "Wrestlers Name", "Age Group", "School", "Ability"],
                [40.0, "Kid One", "4U", "ALP", "Beginner"],
                [42.5, "Kid Two", "4U", "ALP", "Novice"],
            ],
        ),
        (
            "Team Beta",
            [
                ["Weight", "Wrestlers Name", "Age Group", "School", "Ability"],
                [41.0, "Kid Three", "4U", "BET", "Beginner"],
                [95.0, "Kid Four", "15U", "BET", "Advanced"],
            ],
        ),
    ]
    write_xlsx_sheets(xlsx_file, sheets)
    read_back = read_xlsx_sheets(xlsx_file)
    assert len(read_back) == 2

    wrestlers, skipped, tabs = load_wrestlers(xlsx_file)
    assert tabs == ["Team Alpha", "Team Beta"]
    assert len(wrestlers) == 4
    assert len(skipped) == 0
