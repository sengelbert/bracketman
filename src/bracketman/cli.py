"""Command-line interface for Bracketman."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
import subprocess
import sys

import click

from bracketman.config import TournamentConfig
from bracketman.exporters.console import format_summary_report
from bracketman.exporters.csv_xlsx import export_csv_files, export_xlsx_workbook
from bracketman.exporters.html import export_printable_html
from bracketman.grouping.madison import build_tournament_groups
from bracketman.io.loader import load_wrestlers
from bracketman.store import load_tournament, regenerate_brackets_by_ids


def _load_config(config_path: str | None) -> TournamentConfig:
    if config_path:
        return TournamentConfig.from_yaml(config_path)
    default_cfg_path = Path("configs/default.yaml")
    if default_cfg_path.exists():
        return TournamentConfig.from_yaml(default_cfg_path)
    return TournamentConfig()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="bracketman")
def main() -> None:
    """Bracketman: Build wrestling tournament groups and printable brackets from Google Sheets."""


@main.command("inspect")
@click.argument("source")
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True),
    help="Path to YAML configuration file.",
)
def inspect_cmd(source: str, config_path: str | None) -> None:
    """Inspect a Google Sheet URL or local file and display roster counts by tab, age, and skill."""
    cfg = _load_config(config_path)
    wrestlers, skipped, tabs = load_wrestlers(source, config=cfg)

    click.echo("=" * 76)
    click.echo(f"ROSTER INSPECTION: {source}")
    click.echo("=" * 76)
    click.echo(f"Detected Team Tabs ({len(tabs)}): {', '.join(tabs)}")
    click.echo(f"Total Wrestler Entries : {len(wrestlers)}")
    click.echo("")

    tab_counts = Counter(w.team_tab for w in wrestlers)
    click.echo("Entries per Tab:")
    for tab in tabs:
        click.echo(f"  - {tab:<22}: {tab_counts[tab]:>4} entries")

    click.echo("")
    click.echo("Entries by Division / Age Group / Skill Level:")
    bucket_counts = Counter((w.division, w.age_group, w.skill_level) for w in wrestlers)
    for (div, age, skill), count in sorted(bucket_counts.items()):
        weights = [w.weight for w in wrestlers if (w.division, w.age_group, w.skill_level) == (div, age, skill)]
        click.echo(
            f"  - {div:<6} | {age:<4} | {skill:<10} : {count:>4} wrestlers "
            f"({min(weights):g}–{max(weights):g} lbs)"
        )

    if skipped:
        click.echo("")
        click.echo(f"Skipped Rows ({len(skipped)}):")
        for sr in skipped[:15]:
            click.echo(f"  - Tab '{sr.get('sheet')}' Row {sr.get('row')}: {sr.get('reason')}")


@main.command("build")
@click.argument("source")
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True),
    help="Path to YAML configuration file (defaults to configs/default.yaml if present).",
)
@click.option(
    "-o",
    "--output-dir",
    default="output",
    show_default=True,
    help="Directory to write CSV, XLSX, and printable HTML bracket files.",
)
@click.option(
    "--show-rosters",
    is_flag=True,
    help="Print individual wrestler rosters under each group in the console output.",
)
@click.option(
    "--merge-skills",
    is_flag=True,
    help="Automatically merge solo straggler wrestlers into adjacent skill groups of the same age.",
)
@click.option(
    "--merge-ages",
    is_flag=True,
    help="Automatically merge solo straggler wrestlers into adjacent age groups if within weight spread.",
)
@click.option(
    "--map-14u-to-15u",
    is_flag=True,
    help="Map 14U entries into the 15U age group.",
)
@click.option(
    "--max-size",
    type=int,
    default=None,
    help="Override maximum bracket size across all groups (default in config is 4).",
)
@click.option(
    "--target-size",
    type=int,
    default=None,
    help="Override target bracket size across all groups (default in config is 4).",
)
def build_cmd(
    source: str,
    config_path: str | None,
    output_dir: str,
    show_rosters: bool,
    merge_skills: bool,
    merge_ages: bool,
    map_14u_to_15u: bool,
    max_size: int | None,
    target_size: int | None,
) -> None:
    """Read rosters from SOURCE (Google Sheet URL or file) and build groups + brackets."""
    cfg = _load_config(config_path)
    if merge_skills:
        cfg.allow_skill_merge_for_stragglers = True
    if merge_ages:
        cfg.allow_age_merge_for_stragglers = True
    if map_14u_to_15u:
        if "14U" in cfg.age_groups:
            cfg.age_groups.remove("14U")
        cfg.age_group_aliases.pop("14U", None)
        cfg.age_group_aliases.setdefault("15U", []).extend(["14u", "14U", "14 & under"])
    if max_size is not None:
        cfg.default_rule.max_group_size = max_size
        for ag_cfg in cfg.age_group_overrides.values():
            ag_cfg["max_group_size"] = max_size
            for sk_cfg in ag_cfg.get("skills", {}).values():
                sk_cfg["max_group_size"] = max_size
    if target_size is not None:
        cfg.default_rule.target_group_size = target_size
        for ag_cfg in cfg.age_group_overrides.values():
            ag_cfg["target_group_size"] = target_size
            for sk_cfg in ag_cfg.get("skills", {}).values():
                sk_cfg["target_group_size"] = target_size

    wrestlers, skipped, _ = load_wrestlers(source, config=cfg)
    result = build_tournament_groups(
        wrestlers=wrestlers,
        config=cfg,
        source=source,
        skipped_rows=skipped,
    )

    report = format_summary_report(result, show_rosters=show_rosters)
    click.echo(report)

    out_path = Path(output_dir)
    csv_paths = export_csv_files(result, out_path)
    xlsx_path = export_xlsx_workbook(result, out_path / "brackets_workbook.xlsx")
    html_path = export_printable_html(
        result,
        out_path / "brackets.html",
        tournament_name=cfg.tournament_name,
    )

    click.echo("")
    click.echo("EXPORTED FILES")
    click.echo("-" * 88)
    click.echo(f"  Summary CSV         : {csv_paths['summary_csv']}")
    click.echo(f"  Bracket Rosters CSV : {csv_paths['rosters_csv']}")
    click.echo(f"  Bout Schedule CSV   : {csv_paths['bouts_csv']}")
    click.echo(f"  Multi-Tab Workbook  : {xlsx_path}")
    click.echo(f"  Printable Brackets  : {html_path}")


@main.command("init-config")
@click.option(
    "-o",
    "--output",
    default="tournament_config.yaml",
    show_default=True,
    help="Output path for generated YAML configuration.",
)
def init_config_cmd(output: str) -> None:
    """Generate a starter YAML tournament configuration file."""
    out_path = Path(output)
    src_default = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"
    if src_default.exists():
        shutil.copyfile(src_default, out_path)
    else:
        out_path.write_text("# Bracketman Configuration\ntournament_name: Wrestling Tournament\n", encoding="utf-8")
    click.echo(f"Created configuration file at: {out_path}")


@main.command("regenerate")
@click.argument("tournament_slug")
@click.argument("bracket_ids", nargs=-1, required=True)
@click.option("--target-size", type=int, default=None, help="Target group size override.")
@click.option("--max-size", type=int, default=None, help="Maximum group size override.")
@click.option("--max-spread-pct", type=float, default=None, help="Base max weight spread % override.")
@click.option("--combine-pool", is_flag=True, help="Pool selected brackets together across skills/ages.")
def regenerate_cmd(
    tournament_slug: str,
    bracket_ids: tuple[str, ...],
    target_size: int | None,
    max_size: int | None,
    max_spread_pct: float | None,
    combine_pool: bool,
) -> None:
    """Regenerate specific bracket ID(s) within a saved tournament."""
    t = load_tournament(tournament_slug)
    regenerate_brackets_by_ids(
        t,
        group_ids=list(bracket_ids),
        target_group_size=target_size,
        max_group_size=max_size,
        max_weight_spread_pct=max_spread_pct,
        combine_across_skills_or_ages=combine_pool,
    )
    click.echo(f"Regenerated bracket(s) {', '.join(bracket_ids)} in tournament '{t.name}'.")


@main.command("ui")
@click.option("--port", default=8503, show_default=True, help="Port to run the Streamlit UI on.")
@click.option("--headless", is_flag=True, help="Run Streamlit in headless mode.")
def ui_cmd(port: int, headless: bool) -> None:
    """Launch the interactive Bracketman Streamlit web application."""
    app_path = Path(__file__).resolve().parent / "web" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)]
    if headless:
        cmd.extend(["--server.headless", "true"])
    subprocess.run(cmd, check=True)
