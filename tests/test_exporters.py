"""Tests for console, CSV, XLSX, and printable HTML exporters."""

from pathlib import Path

from bracketman.config import TournamentConfig
from bracketman.exporters.console import format_summary_report
from bracketman.exporters.csv_xlsx import export_csv_files, export_xlsx_workbook
from bracketman.exporters.html import (
    export_blank_bracket_html,
    export_printable_html,
    export_printable_roster_html,
    render_blank_bracket_preview_html,
    render_single_bracket_preview_html,
)
from bracketman.grouping.madison import build_tournament_groups
from bracketman.io.xlsx import read_xlsx_sheets
from bracketman.models import Wrestler


def test_exporters_create_valid_outputs(tmp_path: Path):
    cfg = TournamentConfig()
    wrestlers = [
        Wrestler("W01", "Alice", 40.0, "6U", "Beginner", "AR", "Arapahoe", "Coed"),
        Wrestler("W02", "Bob", 41.0, "6U", "Beginner", "ASC", "Ascent", "Coed"),
        Wrestler("W03", "Charlie", 42.0, "6U", "Beginner", "COL", "Columbine", "Coed"),
        Wrestler("W04", "David", 43.0, "6U", "Beginner", "ENG", "Englewood", "Coed"),
    ]
    result = build_tournament_groups(wrestlers, config=cfg, source="test")

    report = format_summary_report(result, show_rosters=True)
    assert "COED-6U-BEG-01" in report
    assert "Alice" in report

    csv_paths = export_csv_files(result, tmp_path)
    assert csv_paths["summary_csv"].exists()
    assert csv_paths["rosters_csv"].exists()
    assert csv_paths["bouts_csv"].exists()

    xlsx_path = export_xlsx_workbook(result, tmp_path / "out.xlsx")
    assert xlsx_path.exists()
    sheets = read_xlsx_sheets(xlsx_path)
    sheet_names = [s[0] for s in sheets]
    assert "Summary" in sheet_names
    assert "Coed_6U" in sheet_names

    html_path = export_printable_html(
        result,
        tmp_path / "brackets.html",
        tournament_name="Example Tournament",
        tournament_date="October 25, 2026",
    )
    assert html_path.exists()
    html_text = html_path.read_text(encoding="utf-8")
    assert "COED-6U-BEG-01" in html_text
    assert "Example Tournament" in html_text
    assert "October 25, 2026" in html_text
    assert "AGE GROUP:" in html_text
    assert "EXPERIENCE:" in html_text
    assert "WEIGHTS:" in html_text
    assert "1<sup>ST</sup> PERIOD" in html_text
    assert "WRESTLER WIN / LOSS TALLY" in html_text
    assert "OFFICIAL BRACKET PLACEMENT &amp; AWARDS" in html_text
    assert "WINNER KEEP-SHEET" not in html_text
    assert "flags-box" not in html_text
    assert "1ST PLACE:" in html_text
    assert "ROUND-ROBIN TIE-BREAKER CRITERIA" in html_text
    assert "MATCH SCORING POINTS (PERIOD BOXES)" in html_text
    assert "Takedown (T3)" in html_text
    assert "3 points" in html_text
    assert "Reversal (R2)" in html_text
    assert 'onclick="resetBracketFilters()"' in html_text
    assert "Escape (E1)" in html_text
    assert "Near Fall (NF2 / NF3 / NF4)" in html_text
    assert "4 pts</strong> (4+ sec)" in html_text
    assert "Warn, 1pt, 1pt, 2pt, DQ" in html_text
    assert ".col-name { width: 18.5%; }" in html_text
    assert ".col-period { width: 20.33%; }" in html_text
    assert "bracket-tree-svg" in html_text
    assert "MAT 1" in html_text
    assert 'id="f-mat"' in html_text
    assert 'onclick="saveBracketsPdf()"' in html_text
    assert 'onclick="saveBracketsPrintout()"' in html_text
    assert "Mat #" in csv_paths["summary_csv"].read_text(encoding="utf-8")


def test_two_wrestler_best_of_3_bracket_and_html(tmp_path: Path):
    cfg = TournamentConfig()
    wrestlers = [
        Wrestler("W01", "Alice", 40.0, "6U", "Beginner", "AR", "Arapahoe", "Coed"),
        Wrestler("W02", "Bob", 41.0, "6U", "Beginner", "ASC", "Ascent", "Coed"),
    ]
    result = build_tournament_groups(wrestlers, config=cfg, source="test")
    assert len(result.groups) == 1
    grp = result.groups[0]
    assert grp.size == 2
    assert grp.bracket_format == "best_of_3"
    assert len(grp.bouts) == 3
    assert [b.bout_number for b in grp.bouts] == [1, 2, 3]

    html_path = export_printable_html(result, tmp_path / "two_man.html")
    html_text = html_path.read_text(encoding="utf-8")
    assert "BEST 2 OUT OF 3 SERIES" in html_text
    assert "BOUT 3* (IF SPLIT 1-1)" in html_text
    assert "1ST PLACE (2 OF 3)" in html_text
    assert '<td class="cell-bout">3*</td>' in html_text


def test_blank_bracket_sheet_html(tmp_path: Path):
    blank_path = export_blank_bracket_html(
        tmp_path / "blank_brackets.html",
        tournament_name="Walk-In Classic",
        tournament_date="November 11, 2026",
    )
    assert blank_path.exists()
    text = blank_path.read_text(encoding="utf-8")
    assert "Walk-In Classic" in text
    assert "BRACKET ID: ______________" in text
    assert "WRESTLER WIN / LOSS TALLY (WRITE IN ROSTER)" in text
    assert "MATCH SCORING POINTS (PERIOD BOXES)" in text
    assert "4-Wrestler Round Robin (1 Page)" in text
    assert "2-Wrestler Best 2-of-3 (1 Page)" in text
    assert 'onclick="saveBlankPdf()"' in text
    assert 'onclick="saveBlankPrintout()"' in text

    preview_html = render_blank_bracket_preview_html(pod_size=4, tournament_name="Walk-In Classic")
    assert "WRESTLER WIN / LOSS TALLY (WRITE IN ROSTER)" in preview_html


def test_bout_sheet_only_layout_without_bracket_diagram(tmp_path: Path):
    cfg = TournamentConfig()
    wrestlers = [
        Wrestler("W01", "Alice", 40.0, "6U", "Beginner", "AR", "Arapahoe", "Coed"),
        Wrestler("W02", "Bob", 41.0, "6U", "Beginner", "ASC", "Ascent", "Coed"),
        Wrestler("W03", "Charlie", 42.0, "6U", "Beginner", "COL", "Columbine", "Coed"),
        Wrestler("W04", "David", 43.0, "6U", "Beginner", "ENG", "Englewood", "Coed"),
    ]
    result = build_tournament_groups(wrestlers, config=cfg, source="test")
    grp = result.groups[0]

    # Single bracket preview without top bracket diagram
    preview_bout_only = render_single_bracket_preview_html(
        grp, tournament_name="Example Tournament", include_bracket_diagram=False
    )
    assert "bout-only-sheet" in preview_bout_only
    assert '<svg class="bracket-tree-svg"' not in preview_bout_only
    assert "height: 42px;" in preview_bout_only

    # Printable HTML exported in Bout-Sheet-Only mode
    bout_only_path = export_printable_html(
        result,
        tmp_path / "bout_sheets_only.html",
        tournament_name="Example Tournament",
        include_bracket_diagram=False,
    )
    bout_only_doc = bout_only_path.read_text(encoding="utf-8")
    assert 'class="bracket-sheet bout-only-sheet"' in bout_only_doc
    assert 'value="bout-only" selected="selected"' in bout_only_doc
    assert "Bout Sheet Only (No Bracket Drawing" in bout_only_doc
    assert ".bracket-sheet.bout-only-sheet .bout-score-table td" in bout_only_doc


def test_printable_roster_directory_html(tmp_path: Path):
    cfg = TournamentConfig(mat_count=2, allow_skill_merge_for_stragglers=True)
    wrestlers = [
        Wrestler("W01", "Alice", 40.0, "6U", "Beginner", "AR", "Arapahoe", "Coed"),
        Wrestler("W02", "Bob", 41.0, "6U", "Beginner", "ASC", "Ascent", "Coed"),
        Wrestler("W03", "Charlie", 41.5, "6U", "Advanced", "COL", "Columbine", "Coed"),  # Solo Advanced -> merged into 6U Beginner
        Wrestler("W04", "David", 56.0, "8U", "Intermediate", "ENG", "Englewood", "Coed"),  # Solo 8U wrestler
    ]
    result = build_tournament_groups(wrestlers, config=cfg, source="test")

    roster_path = export_printable_roster_html(
        result,
        tmp_path / "roster_directory.html",
        tournament_name="Mat Handout Classic",
        tournament_date="November 14, 2026",
        scratched_wrestlers=[
            {
                "name": "Evan NoShow",
                "team": "Beta",
                "weight": 42.0,
                "division": "Coed",
                "age_group": "6U",
                "skill_level": "Beginner",
                "original_brackets": ["COED-6U-BEG-01"],
                "original_mats": {"COED-6U-BEG-01": 1},
                "reason": "Illness",
            }
        ],
    )
    assert roster_path.exists()
    doc = roster_path.read_text(encoding="utf-8")
    assert "Mat Handout Classic" in doc
    assert "MASTER WRESTLER &amp; MAT DIRECTORY" in doc
    assert "COED-6U-BEG-01" in doc
    assert "COED-8U-INT-01" in doc
    assert "MAT 1" in doc
    assert "MAT 2" in doc
    assert "Alice" in doc
    assert "Evan NoShow" in doc
    assert 'id="view-alpha"' in doc
    assert 'id="view-by-age-team"' in doc
    assert "CHECK-IN TABLE: 6U AGE GROUP &mdash; BY SCHOOL / CLUB" in doc
    assert "6U &bull; SCHOOL / CLUB: AR" in doc
    assert 'id="view-by-gid"' in doc
    assert 'id="r-sort"' in doc
    assert '<option value="gid" selected="selected">' in doc
    assert 'onclick="resetRosterFilters()"' in doc
    assert 'id="r-size"' in doc
    assert 'data-size="3"' in doc
    assert 'data-size="1"' in doc
    assert 'value="size-asc"' in doc
    assert 'value="le2"' in doc
    assert 'id="view-by-mat"' in doc
    assert 'id="view-by-team"' in doc
    assert 'id="view-by-bracket"' in doc
    assert 'onclick="saveRosterPdf()"' in doc
    assert 'onclick="saveRosterPrintout()"' in doc
    assert "⚠ MERGED SKILL" in doc
    assert "⚠ SOLO WRESTLER" in doc

    xlsx_path = export_xlsx_workbook(result, tmp_path / "out_roster.xlsx")
    sheet_names = [s[0] for s in read_xlsx_sheets(xlsx_path)]
    assert "Master_Roster" in sheet_names





