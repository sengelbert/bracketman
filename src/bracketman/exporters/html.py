"""Printable HTML bracket and bout-sheet generator for Bracketman.

Designed to match the classic mat-table bout sheet layout (BOUT | WT | WRESTLERS NAME |
1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS) paired with a Wrestler
Win/Loss Tally table, official 1st–4th placement awards lines for the championship keep-sheet,
and condensed round-robin tiebreaker rules & activity point spreads.
All rendered with crisp black borders, zero grey shading, and locked to 1 single page.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from bracketman.models import BracketGroup, TournamentResult


def _render_bout_and_tally_sheet(
    group: BracketGroup,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
) -> str:
    """Render the full single-page printable bracket sheet:

    1. Header: Tournament Name, Date, Division, Age Group, Experience, Weights, Mat #, Table #
    2. Main Bout Score Table: 3 periods, unshaded, bout numbers
    3. Wrestler Win/Loss Tally Table: wins, losses, tiebreaker points, place
    4. Official Bracket Placement & Awards Section (Championship Keep-Sheet)
    5. Condensed Round-Robin Tiebreaker & Point Spread Reference Box
    """
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")
    parts: list[str] = []

    # 0. Sheet Header with Tournament Name, Date, Age, Weight, and Experience Level
    parts.append('<header class="sheet-header">')
    parts.append('<div class="header-top-row">')
    parts.append(
        f'<div class="header-title-block">'
        f'<span class="tourney-name">{escape(tournament_name)}</span>'
        f'<span class="header-sep">&bull;</span>'
        f'<span class="tourney-date">{escape(date_display)}</span>'
        f"</div>"
    )
    parts.append(
        '<div class="header-table-info">'
        '<span class="table-field"><strong class="field-lbl">MAT #:</strong> <span class="field-blank mat-blank"></span></span>'
        '<span class="table-field"><strong class="field-lbl">TABLE / SCORER:</strong> <span class="field-blank scorer-blank"></span></span>'
        "</div>"
    )
    parts.append("</div>")

    # Metadata Strip (Bracket ID, Division, Age Group, Experience Level, Weight Range & Spread)
    parts.append(
        '<div class="header-meta-row">'
        f'<span class="meta-gid"><strong>{escape(group.group_id)}</strong></span>'
        f'<span class="meta-tag"><strong>DIVISION:</strong> {escape(group.division.upper())}</span>'
        f'<span class="meta-tag"><strong>AGE GROUP:</strong> {escape(group.age_group)}</span>'
        f'<span class="meta-tag"><strong>EXPERIENCE:</strong> {escape(group.skill_level.upper())}</span>'
        f'<span class="meta-tag meta-wt"><strong>WEIGHTS:</strong> {escape(group.weight_label)} '
        f"({group.weight_spread_lbs:g} lb / {group.weight_spread_pct:.1f}% spread)</span>"
        "</div>"
    )
    parts.append("</header>")

    # 1. Main Bout Score Sheet (BOUT | WT | WRESTLERS NAME | 1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS)
    parts.append('<div class="bout-table-wrap">')
    parts.append('<table class="bout-score-table">')
    parts.append(
        "<colgroup>"
        '<col class="col-bout" /><col class="col-wt" /><col class="col-name" />'
        '<col class="col-period" /><col class="col-pts" /><col class="col-period" />'
        '<col class="col-pts" /><col class="col-period" /><col class="col-pts" />'
        "</colgroup>"
        "<thead><tr>"
        '<th class="th-bout">B<br/>O<br/>U<br/>T</th><th>WT</th><th>WRESTLERS NAME</th>'
        '<th>1<sup>ST</sup> PERIOD</th><th class="th-pts">P<br/>T<br/>S</th>'
        '<th>2<sup>ND</sup> PERIOD</th><th class="th-pts">P<br/>T<br/>S</th>'
        '<th>3<sup>RD</sup> PERIOD</th><th class="th-pts">P<br/>T<br/>S</th>'
        "</tr></thead><tbody>"
    )

    if group.bouts:
        for b in group.bouts:
            wa = b.wrestler_a
            wb = b.wrestler_b
            wa_label = f"{escape(wa.name)} ({escape(wa.team)})"
            wb_label = f"{escape(wb.name)} ({escape(wb.team)})" if wb else "BYE"
            wb_wt = f"{wb.weight:g}" if wb else ""

            # Row 1 of the bout (Wrestler A)
            parts.append(
                f'<tr class="bout-row-top">'
                f'<td class="cell-bout">{b.bout_number}</td>'
                f'<td class="cell-wt">{wa.weight:g}</td>'
                f'<td class="cell-name">{wa_label}</td>'
                f'<td class="cell-period"></td>'
                f'<td class="cell-pts"></td>'
                f'<td class="cell-period"></td>'
                f'<td class="cell-pts"></td>'
                f'<td class="cell-period"></td>'
                f'<td class="cell-pts"></td>'
                f"</tr>"
            )
            # Row 2 of the bout (Wrestler B) — thick bottom border separates this bout from next
            parts.append(
                f'<tr class="bout-row-bottom">'
                f'<td class="cell-bout"></td>'
                f'<td class="cell-wt">{wb_wt}</td>'
                f'<td class="cell-name">{wb_label}</td>'
                f'<td class="cell-period"></td>'
                f'<td class="cell-pts"></td>'
                f'<td class="cell-period"></td>'
                f'<td class="cell-pts"></td>'
                f'<td class="cell-period"></td>'
                f'<td class="cell-pts"></td>'
                f"</tr>"
            )

        # For 2-wrestler groups (Best 2 of 3), add a 3rd tiebreaker bout pair ("Bout 3 - If Needed")
        if group.size == 2 and len(group.bouts) == 2:
            w1, w2 = group.wrestlers[0], group.wrestlers[1]
            parts.append(
                f'<tr class="bout-row-top">'
                f'<td class="cell-bout">3*</td>'
                f'<td class="cell-wt">{w1.weight:g}</td>'
                f'<td class="cell-name">{escape(w1.name)} ({escape(w1.team)})</td>'
                f'<td class="cell-period"></td><td class="cell-pts"></td>'
                f'<td class="cell-period"></td><td class="cell-pts"></td>'
                f'<td class="cell-period"></td><td class="cell-pts"></td>'
                f"</tr>"
                f'<tr class="bout-row-bottom">'
                f'<td class="cell-bout"></td>'
                f'<td class="cell-wt">{w2.weight:g}</td>'
                f'<td class="cell-name">{escape(w2.name)} ({escape(w2.team)})</td>'
                f'<td class="cell-period"></td><td class="cell-pts"></td>'
                f'<td class="cell-period"></td><td class="cell-pts"></td>'
                f'<td class="cell-period"></td><td class="cell-pts"></td>'
                f"</tr>"
            )
    else:
        # Uncontested / solo wrestler: render 2 blank bout pairs for exhibition matches
        w = group.wrestlers[0]
        parts.append(
            f'<tr class="bout-row-top">'
            f'<td class="cell-bout">1</td>'
            f'<td class="cell-wt">{w.weight:g}</td>'
            f'<td class="cell-name">{escape(w.name)} ({escape(w.team)})</td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f"</tr>"
            f'<tr class="bout-row-bottom">'
            f'<td class="cell-bout"></td>'
            f'<td class="cell-wt"></td>'
            f'<td class="cell-name"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f"</tr>"
        )

    parts.append("</tbody></table></div>")

    # 2. Wrestler Win / Loss Tally Area
    parts.append('<div class="tally-section">')
    parts.append('<div class="tally-title">WRESTLER WIN / LOSS TALLY</div>')
    parts.append(
        '<table class="tally-table">'
        "<colgroup>"
        '<col class="col-seed" /><col class="col-wt" /><col class="col-tally-name" />'
        '<col class="col-club" /><col class="col-wl" /><col class="col-wl" />'
        '<col class="col-tb" /><col class="col-place" />'
        "</colgroup>"
        "<thead><tr>"
        "<th>#</th><th>WT</th><th>WRESTLERS NAME</th><th>SCHOOL / CLUB</th>"
        "<th>WINS</th><th>LOSSES</th><th>TIEBREAKER / PTS</th><th>PLACE</th>"
        "</tr></thead><tbody>"
    )
    for idx, w in enumerate(group.wrestlers, start=1):
        parts.append(
            f"<tr>"
            f'<td class="cell-center">{idx}</td>'
            f'<td class="cell-wt">{w.weight:g}</td>'
            f'<td class="cell-name">{escape(w.name)}</td>'
            f"<td>{escape(w.display_team)}</td>"
            f'<td class="cell-tally-box"></td>'
            f'<td class="cell-tally-box"></td>'
            f'<td class="cell-tally-box"></td>'
            f'<td class="cell-tally-box"></td>'
            f"</tr>"
        )
    parts.append("</tbody></table></div>")

    # 3. Official Bracket Placement & Awards Section (Championship Keep-Sheet)
    parts.append(
        '<div class="awards-section">'
        '<div class="awards-title">&#127942; OFFICIAL BRACKET PLACEMENT &amp; AWARDS &mdash; 1ST PLACE WINNER KEEP-SHEET</div>'
        '<table class="awards-table">'
        "<tbody>"
        "<tr>"
        '<td class="col-award"><span class="award-place">1ST PLACE:</span> <span class="award-name-line"></span> <span class="award-club-lbl">CLUB:</span> <span class="award-club-line"></span></td>'
        '<td class="col-award"><span class="award-place">2ND PLACE:</span> <span class="award-name-line"></span> <span class="award-club-lbl">CLUB:</span> <span class="award-club-line"></span></td>'
        "</tr>"
        "<tr>"
        '<td class="col-award"><span class="award-place">3RD PLACE:</span> <span class="award-name-line"></span> <span class="award-club-lbl">CLUB:</span> <span class="award-club-line"></span></td>'
        '<td class="col-award"><span class="award-place">4TH PLACE:</span> <span class="award-name-line"></span> <span class="award-club-lbl">CLUB:</span> <span class="award-club-line"></span></td>'
        "</tr>"
        "</tbody>"
        "</table>"
        "</div>"
    )

    # 4. Condensed Round-Robin Tie-Breaker Criteria & Activity / Advancement Points Reference
    parts.append(
        '<div class="criteria-section">'
        '<table class="criteria-table">'
        "<thead><tr>"
        '<th class="col-crit-half">ROUND-ROBIN TIE-BREAKER CRITERIA (TABLE REFERENCE)</th>'
        '<th class="col-crit-half">ACTIVITY / ADVANCEMENT POINTS &amp; DECISION SPREADS</th>'
        "</tr></thead>"
        "<tbody><tr>"
        '<td class="criteria-cell">'
        '<div class="crit-line"><strong>1. Win/Loss Record:</strong> Best overall match record in bracket.</div>'
        '<div class="crit-line"><strong>2. Head-to-Head:</strong> Direct bout winner (applies for 2-way ties).</div>'
        '<div class="crit-line"><strong>3. Activity Points:</strong> Most total match advancement points earned.</div>'
        '<div class="crit-line"><strong>4. Most Falls (Pins):</strong> Most pins in least cumulative pin time.</div>'
        '<div class="crit-line"><strong>5. Tech Falls</strong> &bull; <strong>6. Major Decisions</strong> &bull; <strong>7. Total Match Pts</strong></div>'
        "</td>"
        '<td class="criteria-cell">'
        '<div class="crit-line"><strong>&bull; Fall / Forfeit / Default / DQ:</strong> <strong>6 points</strong></div>'
        '<div class="crit-line"><strong>&bull; Technical Fall (TF):</strong> <strong>5 points</strong> &mdash; <em>Win by <strong>15+ match points</strong></em></div>'
        '<div class="crit-line"><strong>&bull; Major Decision (MD):</strong> <strong>4 points</strong> &mdash; <em>Win by <strong>8 to 14 pt spread</strong> (e.g. 10&ndash;2, 9&ndash;1)</em></div>'
        '<div class="crit-line"><strong>&bull; Decision (DEC):</strong> <strong>3 points</strong> &mdash; <em>Win by <strong>1 to 7 pt spread</strong> (e.g. 5&ndash;2, 7&ndash;1, 4&ndash;3)</em></div>'
        '<div class="crit-note"><em>* Point spread rule: 1&ndash;7 pts = DEC (3 pts) &bull; 8&ndash;14 pts = MD (4 pts) &bull; 15+ pts = TF (5 pts).</em></div>'
        "</td>"
        "</tr></tbody>"
        "</table>"
        "</div>"
    )

    return "\n".join(parts)


def render_single_bracket_preview_html(
    group: BracketGroup,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
) -> str:
    """Return a self-styled HTML snippet for rendering a single bracket sheet inside Streamlit."""
    body = _render_bout_and_tally_sheet(group, tournament_name=tournament_name, tournament_date=tournament_date)
    return f"""
    <style>
      .bm-preview-wrap {{
        font-family: Arial, Helvetica, sans-serif;
        color: #000;
        background: #fff;
        padding: 8px 10px;
        border: 1.5px solid #000;
        margin-top: 4px;
        margin-bottom: 8px;
        box-sizing: border-box;
      }}
      .bm-preview-wrap * {{ box-sizing: border-box; }}
      .bm-preview-wrap .sheet-header {{
        border-bottom: 1.5px solid #000;
        padding-bottom: 4px;
        margin-bottom: 6px;
      }}
      .bm-preview-wrap .header-top-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1.5px solid #000;
        padding-bottom: 3px;
        margin-bottom: 4px;
      }}
      .bm-preview-wrap .tourney-name {{
        font-size: 14px;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.02em;
      }}
      .bm-preview-wrap .header-sep {{
        margin: 0 6px;
        font-size: 11px;
      }}
      .bm-preview-wrap .tourney-date {{
        font-size: 12px;
        font-weight: 700;
      }}
      .bm-preview-wrap .header-table-info {{
        font-size: 11px;
        font-weight: 700;
      }}
      .bm-preview-wrap .table-field {{
        margin-left: 10px;
      }}
      .bm-preview-wrap .field-blank {{
        display: inline-block;
        border-bottom: 1.2px solid #000;
        vertical-align: bottom;
      }}
      .bm-preview-wrap .mat-blank {{ width: 45px; }}
      .bm-preview-wrap .scorer-blank {{ width: 75px; }}
      .bm-preview-wrap .header-meta-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
        font-size: 10.5px;
      }}
      .bm-preview-wrap .meta-gid {{
        background: #000;
        color: #fff;
        padding: 1px 5px;
        font-weight: 800;
        font-size: 11px;
        border-radius: 2px;
      }}
      .bm-preview-wrap .meta-tag {{
        padding: 1px 4px;
        border: 1px solid #000;
      }}
      .bm-preview-wrap .meta-wt {{
        font-weight: 600;
      }}
      .bm-preview-wrap .bout-score-table,
      .bm-preview-wrap .tally-table,
      .bm-preview-wrap .awards-table,
      .bm-preview-wrap .criteria-table {{
        width: 100%;
        border-collapse: collapse;
        border: 1.5px solid #000;
        background: #fff;
        margin-bottom: 6px;
      }}
      .bm-preview-wrap th {{
        border: 1px solid #000;
        border-bottom: 1.5px solid #000;
        background: #fff !important;
        color: #000 !important;
        font-size: 10px;
        font-weight: 700;
        text-align: center;
        padding: 3px 2px;
        line-height: 1.15;
      }}
      .bm-preview-wrap td {{
        border: 1px solid #000;
        background: #fff !important;
        color: #000 !important;
        font-size: 11px;
        padding: 3px 4px;
        height: 22px;
      }}
      .bm-preview-wrap tr.bout-row-bottom td {{
        border-bottom: 2px solid #000;
      }}
      .bm-preview-wrap .col-bout {{ width: 5%; }}
      .bm-preview-wrap .col-wt {{ width: 6%; }}
      .bm-preview-wrap .col-name {{ width: 25%; }}
      .bm-preview-wrap .col-period {{ width: 17%; }}
      .bm-preview-wrap .col-pts {{ width: 4.3%; }}
      .bm-preview-wrap .cell-bout, .bm-preview-wrap .cell-center {{
        text-align: center;
        font-weight: 700;
      }}
      .bm-preview-wrap .cell-wt {{
        text-align: center;
        font-weight: 600;
      }}
      .bm-preview-wrap .cell-name {{
        font-weight: 600;
      }}
      .bm-preview-wrap .tally-title {{
        font-size: 10.5px;
        font-weight: 800;
        margin-bottom: 2px;
        letter-spacing: 0.04em;
        color: #000;
      }}
      .bm-preview-wrap .col-seed {{ width: 4%; }}
      .bm-preview-wrap .col-tally-name {{ width: 26%; }}
      .bm-preview-wrap .col-club {{ width: 18%; }}
      .bm-preview-wrap .col-wl {{ width: 13%; }}
      .bm-preview-wrap .col-tb {{ width: 16%; }}
      .bm-preview-wrap .col-place {{ width: 10%; }}

      .bm-preview-wrap .awards-section {{
        border: 1.5px solid #000;
        padding: 3px 6px;
        margin-bottom: 6px;
        background: #fff;
      }}
      .bm-preview-wrap .awards-title {{
        font-size: 10px;
        font-weight: 800;
        margin-bottom: 3px;
        letter-spacing: 0.03em;
      }}
      .bm-preview-wrap .awards-table {{
        margin-bottom: 0;
        border: none;
      }}
      .bm-preview-wrap .awards-table td {{
        border: none;
        padding: 2px 4px;
        height: 18px;
        font-size: 10.5px;
      }}
      .bm-preview-wrap .award-place {{
        font-weight: 800;
        display: inline-block;
        min-width: 68px;
      }}
      .bm-preview-wrap .award-name-line {{
        display: inline-block;
        border-bottom: 1.2px solid #000;
        width: 48%;
        height: 14px;
        vertical-align: bottom;
        margin-right: 4px;
      }}
      .bm-preview-wrap .award-club-lbl {{
        font-weight: 700;
        font-size: 9.5px;
      }}
      .bm-preview-wrap .award-club-line {{
        display: inline-block;
        border-bottom: 1.2px solid #000;
        width: 25%;
        height: 14px;
        vertical-align: bottom;
      }}

      .bm-preview-wrap .criteria-table {{
        margin-bottom: 0;
      }}
      .bm-preview-wrap .criteria-table th {{
        text-align: left;
        padding: 2px 4px;
        font-size: 9px;
      }}
      .bm-preview-wrap .criteria-cell {{
        vertical-align: top;
        font-size: 9px;
        line-height: 1.25;
        padding: 2px 4px;
        height: auto;
      }}
      .bm-preview-wrap .col-crit-half {{ width: 50%; }}
      .bm-preview-wrap .crit-line {{ margin-bottom: 1px; }}
      .bm-preview-wrap .crit-note {{ font-size: 8.5px; margin-top: 1px; }}
    </style>
    <div class="bm-preview-wrap">
      {body}
    </div>
    """


def export_printable_html(
    result: TournamentResult,
    output_path: str | Path,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
) -> Path:
    """Generate a self-contained printable HTML file with unshaded bout score sheets and W/L tally areas."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")

    divisions = sorted({g.division for g in result.groups})
    age_groups = list(dict.fromkeys(g.age_group for g in result.groups))
    skills = list(dict.fromkeys(g.skill_level for g in result.groups))

    cards_html: list[str] = []
    for g in result.groups:
        flags_html = ""
        if g.flags:
            items = []
            for fl in g.flags:
                sugg = f" — <em>{escape(fl.suggestion)}</em>" if fl.suggestion else ""
                items.append(
                    f'<div class="flag-item">'
                    f"<strong>[{escape(fl.code)}]</strong> {escape(fl.message)}{sugg}</div>"
                )
            flags_html = f'<div class="flags-box no-print">{"".join(items)}</div>'

        body_html = _render_bout_and_tally_sheet(g, tournament_name=tournament_name, tournament_date=date_display)

        card = f"""
        <section class="bracket-sheet"
                 data-division="{escape(g.division)}"
                 data-age="{escape(g.age_group)}"
                 data-skill="{escape(g.skill_level)}"
                 data-flagged="{'true' if g.has_warnings else 'false'}">
          {flags_html}
          {body_html}
        </section>
        """
        cards_html.append(card)

    div_opts = "".join(f'<option value="{escape(d)}">{escape(d)}</option>' for d in divisions)
    age_opts = "".join(f'<option value="{escape(a)}">{escape(a)}</option>' for a in age_groups)
    skill_opts = "".join(f'<option value="{escape(s)}">{escape(s)}</option>' for s in skills)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{escape(tournament_name)} - Printable Brackets</title>
  <style>
    * {{ box-sizing: border-box; }}
    @page {{
      size: letter portrait;
      margin: 0.25in 0.3in;
    }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #000;
      margin: 0;
      padding: 12px;
      background: #fff;
    }}
    .toolbar {{
      background: #fff;
      border: 1.5px solid #000;
      padding: 8px 12px;
      margin-bottom: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      max-width: 960px;
      margin-left: auto;
      margin-right: auto;
    }}
    .toolbar-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .toolbar select, .toolbar button {{
      padding: 4px 8px;
      font-size: 12px;
      border: 1px solid #000;
      background: #fff;
      color: #000;
    }}
    .toolbar button {{
      font-weight: 700;
      cursor: pointer;
      border: 2px solid #000;
    }}
    .bracket-sheet {{
      background: #fff;
      border: 1.5px solid #000;
      padding: 12px 14px;
      margin-bottom: 20px;
      max-width: 960px;
      margin-left: auto;
      margin-right: auto;
      box-sizing: border-box;
    }}
    .sheet-header {{
      border-bottom: 1.5px solid #000;
      padding-bottom: 4px;
      margin-bottom: 6px;
    }}
    .header-top-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1.5px solid #000;
      padding-bottom: 3px;
      margin-bottom: 4px;
    }}
    .tourney-name {{
      font-size: 15px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .header-sep {{
      margin: 0 8px;
      font-size: 12px;
    }}
    .tourney-date {{
      font-size: 13px;
      font-weight: 700;
      color: #111;
    }}
    .header-table-info {{
      font-size: 12px;
      font-weight: 700;
    }}
    .table-field {{
      margin-left: 12px;
    }}
    .field-blank {{
      display: inline-block;
      border-bottom: 1.5px solid #000;
      vertical-align: bottom;
    }}
    .mat-blank {{ width: 50px; }}
    .scorer-blank {{ width: 85px; }}

    .header-meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      font-size: 11px;
    }}
    .meta-gid {{
      background: #000;
      color: #fff;
      padding: 2px 6px;
      font-weight: 800;
      font-size: 11.5px;
      border-radius: 2px;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .meta-tag {{
      padding: 1px 5px;
      border: 1px solid #000;
      background: #fff;
    }}
    .meta-wt {{
      font-weight: 600;
    }}

    /* Main Bout Score Table — Unshaded, Crisp Black Borders */
    .bout-score-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1.5px solid #000;
      margin-bottom: 6px;
      background: #fff;
    }}
    .bout-score-table th {{
      border: 1px solid #000;
      border-bottom: 1.5px solid #000;
      background: #fff;
      color: #000;
      font-size: 10.5px;
      font-weight: 700;
      text-align: center;
      padding: 3px 2px;
      line-height: 1.15;
    }}
    .bout-score-table td {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 11px;
      padding: 3px 5px;
      height: 22px;
      vertical-align: middle;
    }}
    /* Thick divider line between each 2-row bout pair so no shading is needed */
    .bout-score-table tr.bout-row-bottom td {{
      border-bottom: 2px solid #000;
    }}
    .col-bout {{ width: 5%; }}
    .col-wt {{ width: 6%; }}
    .col-name {{ width: 25%; }}
    .col-period {{ width: 17%; }}
    .col-pts {{ width: 4.3%; }}

    .th-bout, .th-pts {{
      font-size: 9.5px;
      padding: 2px 1px;
    }}
    .cell-bout {{
      text-align: center;
      font-weight: 700;
      font-size: 11.5px;
    }}
    .cell-wt {{
      text-align: center;
      font-weight: 600;
    }}
    .cell-name {{
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* Wrestler Win / Loss Tally Table */
    .tally-section {{
      margin-bottom: 6px;
    }}
    .tally-title {{
      font-size: 10.5px;
      font-weight: 800;
      letter-spacing: 0.04em;
      margin-bottom: 2px;
    }}
    .tally-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1.5px solid #000;
      background: #fff;
    }}
    .tally-table th {{
      border: 1px solid #000;
      border-bottom: 1.5px solid #000;
      background: #fff;
      color: #000;
      font-size: 10px;
      font-weight: 700;
      text-align: center;
      padding: 3px 3px;
    }}
    .tally-table td {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 11px;
      padding: 3px 6px;
      height: 22px;
    }}
    .col-seed {{ width: 4%; }}
    .col-tally-name {{ width: 26%; }}
    .col-club {{ width: 18%; }}
    .col-wl {{ width: 13%; }}
    .col-tb {{ width: 16%; }}
    .col-place {{ width: 10%; }}
    .cell-center {{
      text-align: center;
      font-weight: 700;
    }}

    /* Official Placement & Awards Section (Championship Keep-Sheet) */
    .awards-section {{
      border: 1.5px solid #000;
      padding: 4px 8px;
      margin-bottom: 6px;
      background: #fff;
    }}
    .awards-title {{
      font-size: 10.5px;
      font-weight: 800;
      letter-spacing: 0.03em;
      margin-bottom: 3px;
    }}
    .awards-table {{
      width: 100%;
      border-collapse: collapse;
      border: none;
      background: #fff;
    }}
    .awards-table td {{
      border: none;
      padding: 2px 4px;
      height: 20px;
      font-size: 11px;
      vertical-align: middle;
    }}
    .col-award {{ width: 50%; }}
    .award-place {{
      font-weight: 800;
      display: inline-block;
      min-width: 72px;
    }}
    .award-name-line {{
      display: inline-block;
      border-bottom: 1.2px solid #000;
      width: 52%;
      height: 15px;
      vertical-align: bottom;
      margin-right: 6px;
    }}
    .award-club-lbl {{
      font-weight: 700;
      font-size: 10px;
    }}
    .award-club-line {{
      display: inline-block;
      border-bottom: 1.2px solid #000;
      width: 25%;
      height: 15px;
      vertical-align: bottom;
    }}

    /* Condensed Round-Robin Tie-Breaker & Activity Points Section */
    .criteria-section {{
      margin-bottom: 0;
    }}
    .criteria-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1.5px solid #000;
      background: #fff;
    }}
    .criteria-table th {{
      border: 1px solid #000;
      border-bottom: 1.5px solid #000;
      background: #fff;
      color: #000;
      font-size: 9.5px;
      font-weight: 700;
      text-align: left;
      padding: 3px 6px;
    }}
    .criteria-table td.criteria-cell {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 9.5px;
      line-height: 1.25;
      padding: 3px 6px;
      vertical-align: top;
      height: auto;
    }}
    .col-crit-half {{ width: 50%; }}
    .crit-line {{ margin-bottom: 1.5px; }}
    .crit-note {{
      font-size: 9px;
      margin-top: 1.5px;
      color: #222;
    }}

    .flags-box {{
      margin-bottom: 6px;
      padding: 4px 8px;
      border: 1px dashed #000;
      background: #fff;
      font-size: 11px;
    }}

    @media print {{
      body {{
        background: #fff;
        padding: 0;
        margin: 0;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .no-print, .toolbar {{ display: none !important; }}
      .bracket-sheet {{
        border: none;
        margin: 0;
        padding: 0;
        page-break-inside: avoid;
        page-break-after: always;
        page-break-before: auto;
        height: 10.45in;
        max-height: 10.45in;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }}
    }}
  </style>
</head>
<body>
  <div class="toolbar no-print">
    <div class="toolbar-filters">
      <strong>{escape(tournament_name)} ({len(result.groups)} Brackets)</strong>
      <label>Division:
        <select id="f-div" onchange="applyFilters()">
          <option value="">All</option>{div_opts}
        </select>
      </label>
      <label>Age Group:
        <select id="f-age" onchange="applyFilters()">
          <option value="">All</option>{age_opts}
        </select>
      </label>
      <label>Skill:
        <select id="f-skill" onchange="applyFilters()">
          <option value="">All</option>{skill_opts}
        </select>
      </label>
      <label>
        <input type="checkbox" id="f-flag" onchange="applyFilters()" /> Flagged Only
      </label>
      <span id="visible-count"></span>
    </div>
    <button onclick="window.print()">Print Visible Brackets</button>
  </div>

  <main id="sheets-container">
    {"".join(cards_html)}
  </main>

  <script>
    function applyFilters() {{
      const div = document.getElementById('f-div').value;
      const age = document.getElementById('f-age').value;
      const skill = document.getElementById('f-skill').value;
      const flagOnly = document.getElementById('f-flag').checked;
      const sheets = document.querySelectorAll('.bracket-sheet');
      let shown = 0;
      sheets.forEach(s => {{
        const matchDiv = !div || s.dataset.division === div;
        const matchAge = !age || s.dataset.age === age;
        const matchSkill = !skill || s.dataset.skill === skill;
        const matchFlag = !flagOnly || s.dataset.flagged === 'true';
        if (matchDiv && matchAge && matchSkill && matchFlag) {{
          s.style.display = '';
          shown++;
        }} else {{
          s.style.display = 'none';
        }}
      }});
      document.getElementById('visible-count').textContent = `Showing ${{shown}} of ${{sheets.length}} brackets`;
    }}
    applyFilters();
  </script>
</body>
</html>
"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
