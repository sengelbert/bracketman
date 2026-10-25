"""Tests for console, CSV, XLSX, and printable HTML exporters."""

from pathlib import Path

from bracketman.config import TournamentConfig
from bracketman.exporters.console import format_summary_report
from bracketman.exporters.csv_xlsx import export_csv_files, export_xlsx_workbook
from bracketman.exporters.html import export_printable_html
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
        tournament_name="SSWL Qualifier",
        tournament_date="October 25, 2026",
    )
    assert html_path.exists()
    html_text = html_path.read_text(encoding="utf-8")
    assert "COED-6U-BEG-01" in html_text
    assert "SSWL Qualifier" in html_text
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
