"""Printable HTML bracket and bout-sheet generator for Bracketman.

Designed to match the classic mat-table bout sheet layout (BOUT | WT | WRESTLERS NAME |
1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS) paired with a Wrestler
Win/Loss Tally table, using crisp black borders and zero grey shading.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from bracketman.models import BracketGroup, TournamentResult


def _render_bout_and_tally_sheet(group: BracketGroup) -> str:
    """Render the unshaded 3-period bout score sheet + wrestler Win/Loss tally table."""
    parts: list[str] = []

    # 1. Main Bout Score Sheet (BOUT | WT | WRESTLERS NAME | 1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS)
    parts.append('<table class="bout-score-table">')
    parts.append(
        '<colgroup>'
        '<col class="col-bout" /><col class="col-wt" /><col class="col-name" />'
        '<col class="col-period" /><col class="col-pts" /><col class="col-period" />'
        '<col class="col-pts" /><col class="col-period" /><col class="col-pts" />'
        '</colgroup>'
        '<thead><tr>'
        '<th class="th-bout">B<br/>O<br/>U<br/>T</th><th>WT</th><th>WRESTLERS<br/>NAME</th>'
        '<th>1<sup>ST</sup> PERIOD</th><th class="th-pts">P<br/>T<br/>S</th>'
        '<th>2<sup>ND</sup> PERIOD</th><th class="th-pts">P<br/>T<br/>S</th>'
        '<th>3<sup>RD</sup> PERIOD</th><th class="th-pts">P<br/>T<br/>S</th>'
        '</tr></thead><tbody>'
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
            # Row 2 of the bout (Wrestler B) — thick bottom border separates this bout from the next
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
        # Uncontested / solo wrestler: still render 2 blank bout pairs for exhibition/walk-on matches
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

    parts.append("</tbody></table>")

    # 2. Wrestler Win / Loss Tally Area
    parts.append('<div class="tally-section">')
    parts.append('<div class="tally-title">WRESTLER WIN / LOSS TALLY &amp; PLACEMENT</div>')
    parts.append(
        '<table class="tally-table">'
        '<thead><tr>'
        '<th class="col-seed">#</th><th class="col-wt">WT</th>'
        '<th class="col-tally-name">WRESTLERS NAME</th><th class="col-club">SCHOOL / CLUB</th>'
        '<th class="col-wl">WINS</th><th class="col-wl">LOSSES</th>'
        '<th class="col-tb">TIEBREAKER / PTS</th><th class="col-place">PLACE</th>'
        '</tr></thead><tbody>'
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

    # 3. Round-Robin Tie-Breaker Criteria & Activity / Advancement Points Reference
    parts.append(
        '<div class="criteria-section">'
        '<table class="criteria-table">'
        '<thead><tr>'
        '<th class="col-crit-half">ROUND-ROBIN TIE-BREAKER CRITERIA (TABLE REFERENCE)</th>'
        '<th class="col-crit-half">ACTIVITY / ADVANCEMENT POINTS &amp; DECISION SPREADS</th>'
        '</tr></thead>'
        '<tbody><tr>'
        '<td class="criteria-cell">'
        '<strong>1. Win / Loss Record:</strong> Best overall match record in the bracket.<br/>'
        '<strong>2. Head-to-Head:</strong> Winner of direct bout (applies when 2 wrestlers are tied).<br/>'
        '<strong>3. Activity Points:</strong> Most total advancement / activity points earned across all bouts.<br/>'
        '<strong>4. Most Falls (Pins):</strong> Most pins in least combined pin time.<br/>'
        '<strong>5. Most Tech Falls:</strong> Most wins by technical fall.<br/>'
        '<strong>6. Most Major Decisions:</strong> Most wins by major decision.<br/>'
        '<strong>7. Match Points:</strong> Most total match points scored across all bouts (then first takedown).'
        '</td>'
        '<td class="criteria-cell">'
        '<strong>&bull; Fall (Pin) / Forfeit / Default / Disqualification:</strong> <strong>6 points</strong><br/>'
        '<strong>&bull; Technical Fall (TF):</strong> <strong>5 points</strong> &mdash; <em>Win by <strong>15 or more points</strong> (match stops)</em><br/>'
        '<strong>&bull; Major Decision (MD):</strong> <strong>4 points</strong> &mdash; <em>Win by <strong>8 to 14 point spread</strong> (e.g., 10&ndash;2, 12&ndash;1, 9&ndash;0)</em><br/>'
        '<strong>&bull; Decision (DEC):</strong> <strong>3 points</strong> &mdash; <em>Win by <strong>1 to 7 point spread</strong> (e.g., 5&ndash;3, 7&ndash;1, 4&ndash;2)</em><br/>'
        '<div class="criteria-note">'
        '<strong>* POINT SPREAD RULE:</strong> If victory margin is <strong>1&ndash;7 pts</strong> = <strong>Decision (3 pts)</strong>. '
        'If victory margin is <strong>8&ndash;14 pts</strong> = <strong>Major Decision (4 pts)</strong>. '
        'Record activity points in the <strong>TIEBREAKER / PTS</strong> column after each bout.'
        '</div>'
        '</td>'
        '</tr></tbody>'
        '</table>'
        '</div>'
    )

    return "\n".join(parts)


def render_single_bracket_preview_html(group: BracketGroup) -> str:
    """Return a self-styled HTML snippet for rendering a single bracket sheet inside Streamlit."""
    body = _render_bout_and_tally_sheet(group)
    return f"""
    <style>
      .bm-preview-wrap {{
        font-family: Arial, Helvetica, sans-serif;
        color: #000;
        background: #fff;
        padding: 10px;
        border: 1.5px solid #000;
        margin-top: 6px;
        margin-bottom: 10px;
      }}
      .bm-preview-wrap .bout-score-table,
      .bm-preview-wrap .tally-table,
      .bm-preview-wrap .criteria-table {{
        width: 100%;
        border-collapse: collapse;
        border: 2px solid #000;
        background: #fff;
        margin-bottom: 10px;
      }}
      .bm-preview-wrap .criteria-cell {{
        vertical-align: top;
        font-size: 11px;
        line-height: 1.45;
        padding: 6px 8px;
        height: auto;
      }}
      .bm-preview-wrap .col-crit-half {{ width: 50%; }}
      .bm-preview-wrap .criteria-note {{
        font-size: 10.5px;
      }}
      .bm-preview-wrap th {{
        border: 1.5px solid #000;
        border-bottom: 2px solid #000;
        background: #fff !important;
        color: #000 !important;
        font-size: 11px;
        font-weight: 700;
        text-align: center;
        padding: 4px 4px;
        line-height: 1.15;
      }}
      .bm-preview-wrap td {{
        border: 1px solid #000;
        background: #fff !important;
        color: #000 !important;
        font-size: 12px;
        padding: 5px 6px;
        height: 28px;
      }}
      .bm-preview-wrap tr.bout-row-bottom td {{
        border-bottom: 2.2px solid #000;
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
        font-size: 11px;
        font-weight: 700;
        margin-bottom: 4px;
        color: #000;
      }}
    </style>
    <div class="bm-preview-wrap">
      {body}
    </div>
    """


def export_printable_html(
    result: TournamentResult,
    output_path: str | Path,
    tournament_name: str = "Wrestling Tournament",
) -> Path:
    """Generate a self-contained printable HTML file with unshaded bout score sheets and W/L tally areas."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

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

        body_html = _render_bout_and_tally_sheet(g)

        card = f"""
        <section class="bracket-sheet"
                 data-division="{escape(g.division)}"
                 data-age="{escape(g.age_group)}"
                 data-skill="{escape(g.skill_level)}"
                 data-flagged="{'true' if g.has_warnings else 'false'}">
          <header class="sheet-header">
            <div class="header-left">
              <h2>{escape(g.group_id)} &mdash; {escape(g.division)} {escape(g.age_group)} ({escape(g.skill_level)})</h2>
              <div class="sheet-sub">{escape(tournament_name)} &bull; Weights: <strong>{escape(g.weight_label)}</strong> (Spread: {g.weight_spread_lbs:g} lbs / {g.weight_spread_pct:.1f}%)</div>
            </div>
            <div class="header-right">
              <div><strong>MAT #:</strong> ____________</div>
              <div><strong>TABLE:</strong> ____________</div>
            </div>
          </header>
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
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #000;
      margin: 0;
      padding: 16px;
      background: #fff;
    }}
    .toolbar {{
      background: #fff;
      border: 1.5px solid #000;
      padding: 10px 14px;
      margin-bottom: 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      justify-content: space-between;
      max-width: 1000px;
      margin-left: auto;
      margin-right: auto;
    }}
    .toolbar-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }}
    .toolbar select, .toolbar button {{
      padding: 5px 10px;
      font-size: 13px;
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
      border: 2px solid #000;
      padding: 18px;
      margin-bottom: 28px;
      max-width: 1000px;
      margin-left: auto;
      margin-right: auto;
    }}
    .sheet-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      border-bottom: 2px solid #000;
      padding-bottom: 8px;
      margin-bottom: 14px;
    }}
    .sheet-header h2 {{
      margin: 0 0 4px 0;
      font-size: 18px;
      letter-spacing: 0.02em;
    }}
    .sheet-sub {{
      font-size: 13px;
    }}
    .header-right {{
      text-align: right;
      font-size: 13px;
      line-height: 1.7;
    }}

    /* Main Bout Score Table — Unshaded, Crisp Black Borders */
    .bout-score-table {{
      width: 100%;
      border-collapse: collapse;
      border: 2px solid #000;
      margin-bottom: 18px;
      background: #fff;
    }}
    .bout-score-table th {{
      border: 1.5px solid #000;
      border-bottom: 2px solid #000;
      background: #fff;
      color: #000;
      font-size: 12px;
      font-weight: 700;
      text-align: center;
      padding: 6px 4px;
      line-height: 1.15;
    }}
    .bout-score-table td {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 13px;
      padding: 6px 6px;
      height: 34px;
      vertical-align: middle;
    }}
    /* Thick divider line between each 2-row bout pair so no shading is needed */
    .bout-score-table tr.bout-row-bottom td {{
      border-bottom: 2.2px solid #000;
    }}
    .col-bout {{ width: 5%; }}
    .col-wt {{ width: 6%; }}
    .col-name {{ width: 25%; }}
    .col-period {{ width: 17%; }}
    .col-pts {{ width: 4.3%; }}

    .th-bout, .th-pts {{
      font-size: 11px;
      padding: 4px 2px;
    }}
    .cell-bout {{
      text-align: center;
      font-weight: 700;
      font-size: 13px;
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
      margin-top: 10px;
    }}
    .tally-title {{
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      margin-bottom: 4px;
    }}
    .tally-table {{
      width: 100%;
      border-collapse: collapse;
      border: 2px solid #000;
      background: #fff;
    }}
    .tally-table th {{
      border: 1.5px solid #000;
      border-bottom: 2px solid #000;
      background: #fff;
      color: #000;
      font-size: 11px;
      font-weight: 700;
      text-align: center;
      padding: 5px 6px;
    }}
    .tally-table td {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 13px;
      padding: 6px 8px;
      height: 32px;
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

    /* Round-Robin Tie-Breaker & Activity Points Section */
    .criteria-section {{
      margin-top: 14px;
    }}
    .criteria-table {{
      width: 100%;
      border-collapse: collapse;
      border: 2px solid #000;
      background: #fff;
    }}
    .criteria-table th {{
      border: 1.5px solid #000;
      border-bottom: 2px solid #000;
      background: #fff;
      color: #000;
      font-size: 11px;
      font-weight: 700;
      text-align: left;
      padding: 5px 8px;
    }}
    .criteria-table td.criteria-cell {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 11.5px;
      line-height: 1.45;
      padding: 6px 8px;
      vertical-align: top;
      height: auto;
    }}
    .col-crit-half {{ width: 50%; }}
    .criteria-note {{
      display: inline-block;
      margin-top: 4px;
      font-size: 10.5px;
      color: #222;
    }}

    .flags-box {{
      margin-bottom: 10px;
      padding: 6px 10px;
      border: 1px dashed #000;
      background: #fff;
      font-size: 12px;
    }}

    @media print {{
      body {{ background: #fff; padding: 0; }}
      .no-print, .toolbar {{ display: none !important; }}
      .bracket-sheet {{
        border: none;
        margin: 0;
        padding: 4px 0;
        page-break-inside: avoid;
        page-break-after: always;
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
