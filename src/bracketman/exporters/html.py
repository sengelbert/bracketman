"""Printable HTML bracket and bout-sheet generator for Bracketman.

Designed to match the classic mat-table bout sheet layout (BOUT | WT | WRESTLERS NAME |
1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS) paired with a combined
Official Placement & Awards + Wrestler Win/Loss Tally section placed prominently at the top,
and condensed round-robin tiebreaker rules & activity point spreads at the bottom.
All rendered with crisp black borders, zero grey shading, and locked to 1 single page.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re

from bracketman.models import BracketGroup, TournamentResult


def _fs_safe_slug(text: str, fallback: str = "tournament") -> str:
    """Return a clean lowercase filesystem-safe slug using only alphanumeric characters and underscores."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return cleaned or fallback


def _render_visual_bracket_diagram(group: BracketGroup) -> str:
    """Render the symmetric double-sided bracket diagram (or Best 2-of-3 series diagram for 2 wrestlers)."""
    wrestlers = group.wrestlers

    # Dedicated Best 2 out of 3 bracket diagram for 2-wrestler groups
    if len(wrestlers) == 2:
        w1, w2 = wrestlers[0], wrestlers[1]
        w1_lbl = f"{escape(w1.name)} ({escape(w1.team)}, {w1.weight:g})"
        w2_lbl = f"{escape(w2.name)} ({escape(w2.team)}, {w2.weight:g})"
        return f"""
    <div class="bracket-tree-section">
      <svg class="bracket-tree-svg" viewBox="0 0 880 112" width="100%" height="96" xmlns="http://www.w3.org/2000/svg">
        <!-- Left Side: 2nd Place / Runner-Up (label under line) -->
        <line x1="12" y1="60" x2="138" y2="60" stroke="#000" stroke-width="1.6" />
        <text x="75" y="73" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">2ND PLACE</text>
        <line x1="138" y1="60" x2="158" y2="60" stroke="#000" stroke-width="1.4" stroke-dasharray="3,2" />

        <!-- Series Title Banner -->
        <text x="440" y="13" font-family="Arial, sans-serif" font-size="9.5" font-weight="900" text-anchor="middle" fill="#000">BEST 2 OUT OF 3 SERIES</text>

        <!-- Bout 1 Box -->
        <rect x="158" y="20" width="176" height="78" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="246" y="33" font-family="Arial, sans-serif" font-size="8.5" font-weight="900" text-anchor="middle" fill="#000">BOUT 1</text>
        <line x1="158" y1="38" x2="334" y2="38" stroke="#000" stroke-width="1.0" />
        <text x="164" y="54" font-family="Arial, sans-serif" font-size="8.2" font-weight="700" fill="#000">{w1_lbl}</text>
        <line x1="158" y1="66" x2="334" y2="66" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="164" y="84" font-family="Arial, sans-serif" font-size="8.2" font-weight="700" fill="#000">{w2_lbl}</text>

        <!-- Connector 1 -> 2 -->
        <line x1="334" y1="59" x2="352" y2="59" stroke="#000" stroke-width="1.5" />

        <!-- Bout 2 Box -->
        <rect x="352" y="20" width="176" height="78" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="440" y="33" font-family="Arial, sans-serif" font-size="8.5" font-weight="900" text-anchor="middle" fill="#000">BOUT 2</text>
        <line x1="352" y1="38" x2="528" y2="38" stroke="#000" stroke-width="1.0" />
        <text x="358" y="54" font-family="Arial, sans-serif" font-size="8.2" font-weight="700" fill="#000">{w2_lbl}</text>
        <line x1="352" y1="66" x2="528" y2="66" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="358" y="84" font-family="Arial, sans-serif" font-size="8.2" font-weight="700" fill="#000">{w1_lbl}</text>

        <!-- Connector 2 -> 3 -->
        <line x1="528" y1="59" x2="546" y2="59" stroke="#000" stroke-width="1.5" />

        <!-- Bout 3 Box (If Needed) -->
        <rect x="546" y="20" width="176" height="78" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="634" y="33" font-family="Arial, sans-serif" font-size="8.5" font-weight="900" text-anchor="middle" fill="#000">BOUT 3* (IF SPLIT 1-1)</text>
        <line x1="546" y1="38" x2="722" y2="38" stroke="#000" stroke-width="1.0" />
        <text x="552" y="54" font-family="Arial, sans-serif" font-size="8.2" font-weight="700" fill="#000">{w1_lbl}</text>
        <line x1="546" y1="66" x2="722" y2="66" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="552" y="84" font-family="Arial, sans-serif" font-size="8.2" font-weight="700" fill="#000">{w2_lbl}</text>

        <!-- Right Side: 1st Place / Champion (label under line) -->
        <line x1="722" y1="60" x2="742" y2="60" stroke="#000" stroke-width="1.6" />
        <line x1="742" y1="60" x2="868" y2="60" stroke="#000" stroke-width="1.6" />
        <text x="805" y="73" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">1ST PLACE (2 OF 3)</text>
      </svg>
    </div>
    """

    # Match Round 1 pairings (Bout 1: top box, Bout 2: bottom box) if 4 wrestlers, else seed order
    if len(wrestlers) == 4 and len(group.bouts) >= 2:
        b1, b2 = group.bouts[0], group.bouts[1]
        s1_a = f"{escape(b1.wrestler_a.name)} ({escape(b1.wrestler_a.team)}, {b1.wrestler_a.weight:g})"
        s1_b = (
            f"{escape(b1.wrestler_b.name)} ({escape(b1.wrestler_b.team)}, {b1.wrestler_b.weight:g})"
            if b1.wrestler_b
            else "BYE"
        )
        s2_a = f"{escape(b2.wrestler_a.name)} ({escape(b2.wrestler_a.team)}, {b2.wrestler_a.weight:g})"
        s2_b = (
            f"{escape(b2.wrestler_b.name)} ({escape(b2.wrestler_b.team)}, {b2.wrestler_b.weight:g})"
            if b2.wrestler_b
            else "BYE"
        )
    else:
        def _fmt_slot(idx: int) -> str:
            if idx < len(wrestlers):
                w = wrestlers[idx]
                return f"{escape(w.name)} ({escape(w.team)}, {w.weight:g})"
            return "BYE" if len(wrestlers) == 3 and idx == 3 else ""

        s1_a = _fmt_slot(0)
        s1_b = _fmt_slot(3) if len(wrestlers) >= 3 else _fmt_slot(1)
        s2_a = _fmt_slot(1) if len(wrestlers) >= 3 else ""
        s2_b = _fmt_slot(2) if len(wrestlers) >= 3 else ""

    return f"""
    <div class="bracket-tree-section">
      <svg class="bracket-tree-svg" viewBox="0 0 880 112" width="100%" height="96" xmlns="http://www.w3.org/2000/svg">
        <!-- Left Side: 3rd Place / Consolation -->
        <line x1="14" y1="56" x2="152" y2="56" stroke="#000" stroke-width="1.6" />
        <text x="83" y="69" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">3RD PLACE</text>
        <polyline points="275,28 152,28 152,84 275,84" fill="none" stroke="#000" stroke-width="1.5" />

        <!-- Center Top Box (Bout 1) -->
        <rect x="275" y="6" width="330" height="44" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="284" y="21" font-family="Arial, sans-serif" font-size="9.5" font-weight="700" fill="#000">{s1_a}</text>
        <text x="284" y="43" font-family="Arial, sans-serif" font-size="9.5" font-weight="700" fill="#000">{s1_b}</text>

        <!-- Center Bottom Box (Bout 2) -->
        <rect x="275" y="62" width="330" height="44" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="284" y="77" font-family="Arial, sans-serif" font-size="9.5" font-weight="700" fill="#000">{s2_a}</text>
        <text x="284" y="99" font-family="Arial, sans-serif" font-size="9.5" font-weight="700" fill="#000">{s2_b}</text>

        <!-- Right Side: 1st Place / Championship -->
        <polyline points="605,28 728,28 728,84 605,84" fill="none" stroke="#000" stroke-width="1.5" />
        <line x1="728" y1="56" x2="866" y2="56" stroke="#000" stroke-width="1.6" />
        <text x="797" y="69" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">1ST PLACE</text>
      </svg>
    </div>
    """


_BW_TROPHY_SVG = (
    '<svg class="bw-trophy-icon" width="11" height="11" viewBox="0 0 16 16" '
    'style="vertical-align:-1.5px;margin-right:3px;" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M4 2h8v4a4 4 0 0 1-8 0V2zm-2 1h2v3H2a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm10 0h2a1 1 0 0 1 1 1v1a1 1 0 0 1-1 1h-2V3zM7 10h2v2.5H7V10zm-2.5 2.5h7V14h-7v-1.5z" fill="#000"/>'
    "</svg>"
)


def _render_bout_and_tally_sheet(
    group: BracketGroup,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    include_bracket_diagram: bool = True,
) -> str:
    """Render the full single-page printable bracket sheet:

    1. Header: Tournament Name, Date, Division, Age Group, Experience, Weights, Mat #
    2. Symmetric Visual Bracket Progression Diagram (optional; omitted in Bout-Sheet-Only mode)
    3. Combined Awards & Tally Section:
       - Official Bracket Placement & Awards (1st–4th Place keep-sheet lines, no club)
       - Wrestler Win/Loss Tally Table
    4. Main Bout Score Table: 3 periods, unshaded, bout numbers, double-height rows (extra-tall in Bout-Sheet-Only mode)
    5. Condensed Round-Robin Tiebreaker & Point Spread Reference Box
    """
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")
    parts: list[str] = []

    # 0. Sheet Header matching Master Wrestler & Mat Directory Handout Header
    parts.append('<header class="sheet-header">')
    parts.append('<div class="header-top-row">')
    parts.append(
        f'<div class="header-title-block">'
        f'<span class="tourney-name">{escape(tournament_name)} &bull; {escape(date_display)}</span>'
        f"</div>"
    )
    mat_display_html = (
        f'<span class="mat-badge">MAT {group.mat_number}</span>'
        if group.mat_number is not None
        else '<span class="field-blank mat-blank"></span>'
    )
    parts.append(
        '<div class="header-table-info">'
        '<span class="doc-subtitle-badge">'
        '<span class="lbl-full">OFFICIAL BRACKET &amp; BOUT SHEET</span>'
        '<span class="lbl-bout-only">OFFICIAL BOUT SHEET</span>'
        "</span>"
        f'<span class="table-field"><strong class="field-lbl">MAT #:</strong> {mat_display_html}</span>'
        "</div>"
    )
    parts.append("</div>")

    # Metadata Strip (Bracket ID, Division, Age Group, Experience Level, Format, Weight Range & Spread)
    fmt_str = (
        "BEST 2 OF 3"
        if group.size == 2 or group.bracket_format == "best_of_3"
        else f"{group.size}-MAN ROUND ROBIN"
    )
    parts.append(
        '<div class="header-meta-row">'
        f'<span class="meta-gid"><strong>{escape(group.group_id)}</strong></span>'
        f'<span class="meta-tag"><strong>DIVISION:</strong> {escape(group.division.upper())}</span>'
        f'<span class="meta-tag"><strong>AGE GROUP:</strong> {escape(group.age_group)}</span>'
        f'<span class="meta-tag"><strong>EXPERIENCE:</strong> {escape(group.skill_level.upper())}</span>'
        f'<span class="meta-tag"><strong>FORMAT:</strong> {fmt_str}</span>'
        f'<span class="meta-tag meta-wt"><strong>WEIGHTS:</strong> {escape(group.weight_label)} '
        f"({group.weight_spread_lbs:g} lb / {group.weight_spread_pct:.1f}% spread)</span>"
        "</div>"
    )
    parts.append("</header>")

    # 1. Visual Bracket Progression Diagram (Directly under header, above Placement & Awards)
    if include_bracket_diagram:
        parts.append(_render_visual_bracket_diagram(group))

    # 2. Combined Section: Official Placement Awards + Win / Loss Tally Table
    parts.append('<div class="combined-tally-awards">')

    # 2A. Official Bracket Placement & Awards Section (club removed)
    parts.append(
        '<div class="awards-section">'
        f'<div class="awards-title">{_BW_TROPHY_SVG}OFFICIAL BRACKET PLACEMENT &amp; AWARDS</div>'
        '<table class="awards-table">'
        "<tbody>"
        "<tr>"
        '<td class="col-award"><span class="award-place">1ST PLACE:</span> <span class="award-name-line"></span></td>'
        '<td class="col-award"><span class="award-place">2ND PLACE:</span> <span class="award-name-line"></span></td>'
        "</tr>"
        "<tr>"
        '<td class="col-award"><span class="award-place">3RD PLACE:</span> <span class="award-name-line"></span></td>'
        '<td class="col-award"><span class="award-place">4TH PLACE:</span> <span class="award-name-line"></span></td>'
        "</tr>"
        "</tbody>"
        "</table>"
        "</div>"
    )

    # 2B. Wrestler Win / Loss Tally Area
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
    parts.append("</div>")  # end combined-tally-awards

    # 3. Main Bout Score Sheet (BOUT | WT | WRESTLERS NAME | 1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS)
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
            bout_num_display = "3*" if (group.size == 2 and b.bout_number == 3) else str(b.bout_number)

            # Row 1 of the bout (Wrestler A)
            parts.append(
                f'<tr class="bout-row-top">'
                f'<td class="cell-bout">{bout_num_display}</td>'
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

        # Fallback for any legacy saved 2-wrestler groups that only stored 2 bouts in JSON
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

    # 4. Combined Match Scoring Points, Round-Robin Tie-Breaker Criteria & Advancement Points Reference
    parts.append(_render_scoring_and_criteria_box())

    return "\n".join(parts)


def _render_scoring_and_criteria_box() -> str:
    """Render the condensed 3-column reference box for Match Scoring Points, Advancement Points, and Tie-Breakers."""
    return (
        '<div class="criteria-section">'
        '<table class="criteria-table">'
        "<thead><tr>"
        '<th class="col-crit-third">MATCH SCORING POINTS (PERIOD BOXES)</th>'
        '<th class="col-crit-third">ADVANCEMENT POINTS &amp; DECISION SPREADS</th>'
        '<th class="col-crit-third">ROUND-ROBIN TIE-BREAKER CRITERIA</th>'
        "</tr></thead>"
        "<tbody><tr>"
        '<td class="criteria-cell">'
        '<div class="crit-line"><strong>&bull; Takedown (T3):</strong> <strong>3 points</strong></div>'
        '<div class="crit-line"><strong>&bull; Escape (E1):</strong> <strong>1 point</strong></div>'
        '<div class="crit-line"><strong>&bull; Reversal (R2):</strong> <strong>2 points</strong></div>'
        '<div class="crit-line"><strong>&bull; Near Fall (NF2 / NF3 / NF4):</strong> <strong>2 pts</strong> (2 sec) &bull; <strong>3 pts</strong> (3 sec) &bull; <strong>4 pts</strong> (4+ sec)</div>'
        '<div class="crit-line"><strong>&bull; Penalty:</strong> <strong>Warn, 1pt, 1pt, 2pt, DQ</strong></div>'
        "</td>"
        '<td class="criteria-cell">'
        '<div class="crit-line"><strong>&bull; Fall / Forfeit / Default / DQ:</strong> <strong>6 points</strong></div>'
        '<div class="crit-line"><strong>&bull; Technical Fall (TF):</strong> <strong>5 pts</strong> &mdash; <em>Win by <strong>15+ match pts</strong></em></div>'
        '<div class="crit-line"><strong>&bull; Major Decision (MD):</strong> <strong>4 pts</strong> &mdash; <em>Win by <strong>8&ndash;14 pt spread</strong></em></div>'
        '<div class="crit-line"><strong>&bull; Decision (DEC):</strong> <strong>3 pts</strong> &mdash; <em>Win by <strong>1&ndash;7 pt spread</strong></em></div>'
        '<div class="crit-note"><em>* Spread: 1&ndash;7 pts = DEC (3) &bull; 8&ndash;14 = MD (4) &bull; 15+ = TF (5).</em></div>'
        "</td>"
        '<td class="criteria-cell">'
        '<div class="crit-line"><strong>1. Win/Loss Record:</strong> Best overall match record in pod.</div>'
        '<div class="crit-line"><strong>2. Head-to-Head:</strong> Direct bout winner (2-way ties).</div>'
        '<div class="crit-line"><strong>3. Activity Points:</strong> Most advancement points earned.</div>'
        '<div class="crit-line"><strong>4. Most Falls (Pins):</strong> Most pins in least total time.</div>'
        '<div class="crit-line"><strong>5. Tech Falls</strong> &bull; <strong>6. Major Decisions</strong> &bull; <strong>7. Match Pts</strong></div>'
        "</td>"
        "</tr></tbody>"
        "</table>"
        "</div>"
    )


def _render_blank_sheet_body(
    pod_size: int = 4,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    include_bracket_diagram: bool = True,
) -> str:
    """Render a 1-page blank write-in bracket & bout sheet for mat-side walk-in / exhibition pods."""
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")
    parts: list[str] = []

    # 0. Header with write-in blanks for Division, Age Group, Experience, Weight Range, and Mat #
    parts.append('<header class="sheet-header">')
    parts.append('<div class="header-top-row">')
    parts.append(
        f'<div class="header-title-block">'
        f'<span class="tourney-name">{escape(tournament_name)} &bull; {escape(date_display)}</span>'
        f"</div>"
    )
    parts.append(
        '<div class="header-table-info">'
        '<span class="doc-subtitle-badge">'
        '<span class="lbl-full">BLANK WRITE-IN BRACKET &amp; BOUT SHEET</span>'
        '<span class="lbl-bout-only">BLANK WRITE-IN BOUT SHEET</span>'
        "</span>"
        '<span class="table-field"><strong class="field-lbl">MAT #:</strong> <span class="field-blank mat-blank"></span></span>'
        "</div>"
    )
    parts.append("</div>")

    fmt_label = "BEST 2 OF 3" if pod_size == 2 else f"{pod_size}-MAN ROUND ROBIN"
    parts.append(
        '<div class="header-meta-row">'
        '<span class="meta-gid"><strong>BRACKET ID: ______________</strong></span>'
        '<span class="meta-tag"><strong>DIVISION:</strong> ____________</span>'
        '<span class="meta-tag"><strong>AGE GROUP:</strong> ________</span>'
        '<span class="meta-tag"><strong>EXPERIENCE:</strong> ____________</span>'
        '<span class="meta-tag meta-wt"><strong>WEIGHTS:</strong> _______________</span>'
        f'<span class="meta-tag"><strong>FORMAT:</strong> {fmt_label}</span>'
        "</div>"
    )
    parts.append("</header>")

    # 1. Visual Bracket Diagram (Blank Write-In — omitted in Bout-Sheet-Only mode)
    if include_bracket_diagram and pod_size == 2:
        parts.append(
            """
    <div class="bracket-tree-section">
      <svg class="bracket-tree-svg" viewBox="0 0 880 112" width="100%" height="96" xmlns="http://www.w3.org/2000/svg">
        <line x1="12" y1="60" x2="138" y2="60" stroke="#000" stroke-width="1.6" />
        <text x="75" y="73" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">2ND PLACE</text>
        <line x1="138" y1="60" x2="158" y2="60" stroke="#000" stroke-width="1.4" stroke-dasharray="3,2" />

        <text x="440" y="13" font-family="Arial, sans-serif" font-size="9.5" font-weight="900" text-anchor="middle" fill="#000">BEST 2 OUT OF 3 SERIES</text>

        <rect x="158" y="20" width="176" height="78" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="246" y="33" font-family="Arial, sans-serif" font-size="8.5" font-weight="900" text-anchor="middle" fill="#000">BOUT 1</text>
        <line x1="158" y1="38" x2="334" y2="38" stroke="#000" stroke-width="1.0" />
        <text x="164" y="55" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#444">#1:</text>
        <line x1="158" y1="66" x2="334" y2="66" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="164" y="85" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#444">#2:</text>

        <line x1="334" y1="59" x2="352" y2="59" stroke="#000" stroke-width="1.5" />

        <rect x="352" y="20" width="176" height="78" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="440" y="33" font-family="Arial, sans-serif" font-size="8.5" font-weight="900" text-anchor="middle" fill="#000">BOUT 2</text>
        <line x1="352" y1="38" x2="528" y2="38" stroke="#000" stroke-width="1.0" />
        <text x="358" y="55" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#444">#2:</text>
        <line x1="352" y1="66" x2="528" y2="66" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="358" y="85" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#444">#1:</text>

        <line x1="528" y1="59" x2="546" y2="59" stroke="#000" stroke-width="1.5" />

        <rect x="546" y="20" width="176" height="78" fill="#fff" stroke="#000" stroke-width="1.8" />
        <text x="634" y="33" font-family="Arial, sans-serif" font-size="8.5" font-weight="900" text-anchor="middle" fill="#000">BOUT 3* (IF SPLIT 1-1)</text>
        <line x1="546" y1="38" x2="722" y2="38" stroke="#000" stroke-width="1.0" />
        <text x="552" y="55" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#444">#1:</text>
        <line x1="546" y1="66" x2="722" y2="66" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="552" y="85" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#444">#2:</text>

        <line x1="722" y1="60" x2="868" y2="60" stroke="#000" stroke-width="1.6" />
        <text x="805" y="73" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">1ST PLACE (2 OF 3)</text>
      </svg>
    </div>
            """
        )
    elif include_bracket_diagram:
        slot4_lbl = "#4: BYE" if pod_size == 3 else "#4:"
        parts.append(
            f"""
    <div class="bracket-tree-section">
      <svg class="bracket-tree-svg" viewBox="0 0 880 112" width="100%" height="96" xmlns="http://www.w3.org/2000/svg">
        <!-- Left Side: 3rd Place / Consolation -->
        <line x1="14" y1="56" x2="152" y2="56" stroke="#000" stroke-width="1.6" />
        <text x="83" y="69" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">3RD PLACE</text>
        <polyline points="275,28 152,28 152,84 275,84" fill="none" stroke="#000" stroke-width="1.5" />

        <!-- Center Top Box (Bout 1) -->
        <rect x="275" y="6" width="330" height="44" fill="#fff" stroke="#000" stroke-width="1.8" />
        <line x1="275" y1="28" x2="605" y2="28" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="284" y="22" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#444">#1:</text>
        <text x="284" y="44" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#444">{slot4_lbl}</text>

        <!-- Center Bottom Box (Bout 2) -->
        <rect x="275" y="62" width="330" height="44" fill="#fff" stroke="#000" stroke-width="1.8" />
        <line x1="275" y1="84" x2="605" y2="84" stroke="#000" stroke-width="0.8" stroke-dasharray="2,2" />
        <text x="284" y="78" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#444">#2:</text>
        <text x="284" y="100" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#444">#3:</text>

        <!-- Right Side: 1st Place / Championship -->
        <polyline points="605,28 728,28 728,84 605,84" fill="none" stroke="#000" stroke-width="1.5" />
        <line x1="728" y1="56" x2="866" y2="56" stroke="#000" stroke-width="1.6" />
        <text x="797" y="69" font-family="Arial, sans-serif" font-size="9" font-weight="800" text-anchor="middle" fill="#000">1ST PLACE</text>
      </svg>
    </div>
            """
        )

    # 2. Combined Official Placement Awards + Blank Wrestler Win/Loss Tally Table
    parts.append('<div class="combined-tally-awards">')
    parts.append(
        '<div class="awards-section">'
        f'<div class="awards-title">{_BW_TROPHY_SVG}OFFICIAL BRACKET PLACEMENT &amp; AWARDS</div>'
        '<table class="awards-table">'
        "<tbody>"
        "<tr>"
        '<td class="col-award"><span class="award-place">1ST PLACE:</span> <span class="award-name-line"></span></td>'
        '<td class="col-award"><span class="award-place">2ND PLACE:</span> <span class="award-name-line"></span></td>'
        "</tr>"
        "<tr>"
        '<td class="col-award"><span class="award-place">3RD PLACE:</span> <span class="award-name-line"></span></td>'
        '<td class="col-award"><span class="award-place">4TH PLACE:</span> <span class="award-name-line"></span></td>'
        "</tr>"
        "</tbody>"
        "</table>"
        "</div>"
    )

    parts.append('<div class="tally-section">')
    parts.append('<div class="tally-title">WRESTLER WIN / LOSS TALLY (WRITE IN ROSTER)</div>')
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
    for idx in range(1, pod_size + 1):
        parts.append(
            f"<tr>"
            f'<td class="cell-center">{idx}</td>'
            f'<td class="cell-wt"></td>'
            f'<td class="cell-name"></td>'
            f"<td></td>"
            f'<td class="cell-tally-box"></td>'
            f'<td class="cell-tally-box"></td>'
            f'<td class="cell-tally-box"></td>'
            f'<td class="cell-tally-box"></td>'
            f"</tr>"
        )
    parts.append("</tbody></table></div>")
    parts.append("</div>")

    # 3. Main Bout Score Sheet (Blank Write-In Bouts with Seed Pairing Hints)
    if pod_size == 2:
        bout_pairings = [("1", "#1", "#2"), ("2", "#2", "#1"), ("3*", "#1", "#2")]
    elif pod_size == 3:
        bout_pairings = [("1", "#2", "#3"), ("2", "#1", "#3"), ("3", "#1", "#2")]
    else:
        bout_pairings = [
            ("1", "#1", "#4"),
            ("2", "#2", "#3"),
            ("3", "#1", "#3"),
            ("4", "#2", "#4"),
            ("5", "#1", "#2"),
            ("6", "#3", "#4"),
        ]

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
    for b_lbl, s_a, s_b in bout_pairings:
        parts.append(
            f'<tr class="bout-row-top">'
            f'<td class="cell-bout">{b_lbl}</td>'
            f'<td class="cell-wt"></td>'
            f'<td class="cell-name"><span style="color:#666;font-size:8.5px;font-weight:700;">{s_a}:</span> </td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f"</tr>"
            f'<tr class="bout-row-bottom">'
            f'<td class="cell-bout"></td>'
            f'<td class="cell-wt"></td>'
            f'<td class="cell-name"><span style="color:#666;font-size:8.5px;font-weight:700;">{s_b}:</span> </td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f'<td class="cell-period"></td><td class="cell-pts"></td>'
            f"</tr>"
        )
    parts.append("</tbody></table></div>")

    # 4. Scoring & Tie-Breaker Reference Box
    parts.append(_render_scoring_and_criteria_box())

    return "\n".join(parts)


def render_single_bracket_preview_html(
    group: BracketGroup,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    include_bracket_diagram: bool = False,
) -> str:
    """Return a self-styled HTML snippet for rendering a single bracket sheet inside Streamlit."""
    body = _render_bout_and_tally_sheet(
        group,
        tournament_name=tournament_name,
        tournament_date=tournament_date,
        include_bracket_diagram=include_bracket_diagram,
    )
    return _wrap_preview_html(body, bout_only=not include_bracket_diagram)


def render_blank_bracket_preview_html(
    pod_size: int = 4,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    include_bracket_diagram: bool = False,
) -> str:
    """Return a self-styled HTML snippet for previewing a blank write-in bracket sheet inside Streamlit."""
    body = _render_blank_sheet_body(
        pod_size=pod_size,
        tournament_name=tournament_name,
        tournament_date=tournament_date,
        include_bracket_diagram=include_bracket_diagram,
    )
    return _wrap_preview_html(body, bout_only=not include_bracket_diagram)


def _wrap_preview_html(body: str, bout_only: bool = False) -> str:
    """Wrap a single bracket body in self-contained preview CSS."""
    wrap_cls = "bm-preview-wrap bout-only-sheet" if bout_only else "bm-preview-wrap"
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
        border-bottom: 2.5px solid #000;
        padding-bottom: 5px;
        margin-bottom: 6px;
      }}
      .bm-preview-wrap .header-top-row {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 4px;
      }}
      .bm-preview-wrap .tourney-name {{
        font-size: 16px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.02em;
      }}
      .bm-preview-wrap .header-table-info {{
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 11px;
        font-weight: 700;
      }}
      .bm-preview-wrap .doc-subtitle-badge {{
        font-size: 11px;
        font-weight: 800;
        border: 1.5px solid #000;
        padding: 1.5px 7px;
        letter-spacing: 0.02em;
      }}
      .bm-preview-wrap .lbl-bout-only {{ display: none; }}
      .bm-preview-wrap.bout-only-sheet .lbl-full {{ display: none; }}
      .bm-preview-wrap.bout-only-sheet .lbl-bout-only {{ display: inline; }}
      .bm-preview-wrap .table-field {{
        margin-left: 2px;
      }}
      .bm-preview-wrap .field-blank {{
        display: inline-block;
        border-bottom: 1.2px solid #000;
        vertical-align: bottom;
      }}
      .bm-preview-wrap .mat-blank {{ width: 45px; }}
      .bm-preview-wrap .mat-badge {{
        display: inline-block;
        border: 1.5px solid #000;
        padding: 1.5px 7px;
        font-weight: 900;
        font-size: 11.5px;
        background: #fff;
        color: #000;
      }}
      .bm-preview-wrap .header-meta-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        font-size: 10.5px;
      }}
      .bm-preview-wrap .meta-gid {{
        background: #000;
        color: #fff;
        padding: 1.5px 6px;
        font-weight: 800;
        font-size: 11px;
        border-radius: 2px;
      }}
      .bm-preview-wrap .meta-tag {{
        padding: 1px 5px;
        border: 1px solid #000;
      }}
      .bm-preview-wrap .meta-wt {{
        font-weight: 600;
      }}

      /* Combined Awards & Tally Section */
      .bm-preview-wrap .combined-tally-awards {{
        margin-bottom: 6px;
      }}
      .bm-preview-wrap .awards-section {{
        border: 1.5px solid #000;
        border-bottom: none;
        padding: 4px 6px;
        background: #fff;
      }}
      .bm-preview-wrap .awards-title {{
        font-size: 10px;
        font-weight: 800;
        margin-bottom: 3px;
        letter-spacing: 0.03em;
      }}
      .bm-preview-wrap .awards-table {{
        width: 100%;
        border-collapse: collapse;
        border: none;
        margin-bottom: 0;
      }}
      .bm-preview-wrap .awards-table td {{
        border: none;
        padding: 2px 4px;
        height: 18px;
        font-size: 10.5px;
      }}
      .bm-preview-wrap .col-award {{ width: 50%; }}
      .bm-preview-wrap .award-place {{
        font-weight: 800;
        display: inline-block;
        min-width: 68px;
      }}
      .bm-preview-wrap .award-name-line {{
        display: inline-block;
        border-bottom: 1.2px solid #000;
        width: 70%;
        height: 14px;
        vertical-align: bottom;
      }}

      .bm-preview-wrap .tally-section {{
        margin-bottom: 0;
      }}
      .bm-preview-wrap .bracket-tree-section {{
        border: none;
        background: #fff;
        margin: 2px 0 4px 0;
      }}
      .bm-preview-wrap .bracket-tree-svg {{
        display: block;
        width: 100%;
        height: 92px;
      }}
      .bm-preview-wrap .tally-title {{
        font-size: 10px;
        font-weight: 800;
        padding: 2px 6px;
        border: 1.5px solid #000;
        border-bottom: none;
        background: #fff;
        letter-spacing: 0.03em;
      }}
      .bm-preview-wrap .bout-score-table,
      .bm-preview-wrap .tally-table,
      .bm-preview-wrap .criteria-table {{
        width: 100%;
        border-collapse: collapse;
        border: 1.5px solid #000;
        background: #fff;
        margin-bottom: 5px;
      }}
      .bm-preview-wrap th {{
        border: 1px solid #000;
        border-bottom: 1.5px solid #000;
        background: #fff !important;
        color: #000 !important;
        font-size: 10px;
        font-weight: 700;
        text-align: center;
        padding: 2px 2px;
        line-height: 1.1;
      }}
      .bm-preview-wrap td {{
        border: 1px solid #000;
        background: #fff !important;
        color: #000 !important;
        font-size: 10.5px;
        padding: 2px 4px;
        height: 18px;
      }}
      .bm-preview-wrap .bout-score-table td {{
        height: 38px;
        padding: 3px 4px;
      }}
      .bm-preview-wrap tr.bout-row-bottom td {{
        border-bottom: 2px solid #000;
      }}
      /* Narrowed name/bout/wt columns to maximize width (61%) for the 3 period scoreboxes */
      .bm-preview-wrap .col-bout {{ width: 3.8%; }}
      .bm-preview-wrap .col-wt {{ width: 4.7%; }}
      .bm-preview-wrap .col-name {{ width: 18.5%; }}
      .bm-preview-wrap .col-period {{ width: 20.33%; }}
      .bm-preview-wrap .col-pts {{ width: 4.0%; }}
      .bm-preview-wrap .cell-bout, .bm-preview-wrap .cell-center {{
        text-align: center;
        font-weight: 700;
      }}
      .bm-preview-wrap .cell-wt {{
        text-align: center;
        font-weight: 600;
        font-size: 9.5px;
      }}
      .bm-preview-wrap .bout-score-table .cell-name {{
        font-weight: 600;
        font-size: 9.5px;
        line-height: 1.15;
      }}
      .bm-preview-wrap .col-seed {{ width: 4%; }}
      .bm-preview-wrap .col-tally-name {{ width: 26%; }}
      .bm-preview-wrap .col-club {{ width: 18%; }}
      .bm-preview-wrap .col-wl {{ width: 13%; }}
      .bm-preview-wrap .col-tb {{ width: 16%; }}
      .bm-preview-wrap .col-place {{ width: 10%; }}

      .bm-preview-wrap .criteria-table {{
        margin-bottom: 0;
      }}
      .bm-preview-wrap .criteria-table th {{
        text-align: left;
        padding: 2px 4px;
        font-size: 8.8px;
      }}
      .bm-preview-wrap .criteria-cell {{
        vertical-align: top;
        font-size: 8.6px;
        line-height: 1.22;
        padding: 2px 4px;
        height: auto;
      }}
      .bm-preview-wrap .col-crit-third {{ width: 33.33%; }}
      .bm-preview-wrap .crit-line {{ margin-bottom: 1px; }}
      .bm-preview-wrap .crit-note {{ font-size: 8.2px; margin-top: 1px; }}

      /* Bout-Sheet-Only Mode (No Bracket Diagram -> Larger Fonts & Expanded Row Real Estate, Locked to 1 Page) */
      .bm-preview-wrap.bout-only-sheet .bracket-tree-section {{
        display: none !important;
      }}
      .bm-preview-wrap.bout-only-sheet .tourney-name {{ font-size: 16px; }}
      .bm-preview-wrap.bout-only-sheet .header-meta-row {{ font-size: 11.5px; }}
      .bm-preview-wrap.bout-only-sheet .awards-title,
      .bm-preview-wrap.bout-only-sheet .tally-title {{ font-size: 10.5px; padding: 2px 8px; }}
      .bm-preview-wrap.bout-only-sheet .awards-table td {{ height: 19px; font-size: 11px; }}
      .bm-preview-wrap.bout-only-sheet .tally-table th {{ font-size: 10px; padding: 2px 4px; }}
      .bm-preview-wrap.bout-only-sheet .tally-table td {{ height: 20px; font-size: 11px; }}
      .bm-preview-wrap.bout-only-sheet .bout-score-table th {{ font-size: 10.5px; padding: 2px 3px; }}
      .bm-preview-wrap.bout-only-sheet .bout-score-table td {{ height: 42px; padding: 3px 5px; font-size: 11px; }}
      .bm-preview-wrap.bout-only-sheet .bout-score-table .cell-bout {{ font-size: 12px; }}
      .bm-preview-wrap.bout-only-sheet .bout-score-table .cell-wt {{ font-size: 10.5px; }}
      .bm-preview-wrap.bout-only-sheet .bout-score-table .cell-name {{ font-size: 10.5px; }}
      .bm-preview-wrap.bout-only-sheet .criteria-table th {{ font-size: 9.2px; padding: 2px 5px; }}
      .bm-preview-wrap.bout-only-sheet .criteria-cell {{ font-size: 9px; line-height: 1.22; padding: 2px 5px; }}
    </style>
    <div class="{wrap_cls}">
      {body}
    </div>
    """


def export_blank_bracket_html(
    output_path: str | Path,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    pod_sizes: list[int] | None = None,
    include_bracket_diagram: bool = False,
) -> Path:
    """Generate a self-contained printable HTML file with blank write-in bracket & bout sheets."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")
    sizes = pod_sizes or [4, 3, 2]
    sheet_cls = "bracket-sheet" if include_bracket_diagram else "bracket-sheet bout-only-sheet"
    default_layout_val = "full" if include_bracket_diagram else "bout-only"

    cards_html: list[str] = []
    for sz in sizes:
        # Always render the SVG inside the HTML DOM so the interactive toolbar layout selector can toggle it live,
        # while applying `.bout-only-sheet` by default when `include_bracket_diagram=False`.
        body_html = _render_blank_sheet_body(
            pod_size=sz,
            tournament_name=tournament_name,
            tournament_date=date_display,
            include_bracket_diagram=True,
        )
        cards_html.append(
            f"""
        <section class="{sheet_cls}" data-size="{sz}">
          {body_html}
        </section>
        """
        )

    full_sel = ' selected="selected"' if default_layout_val == "full" else ""
    bout_sel = ' selected="selected"' if default_layout_val == "bout-only" else ""
    base_slug = _fs_safe_slug(tournament_name)

    html_doc = _build_printable_html_document(
        title=f"{base_slug}_{'blank_bout_sheet_only' if default_layout_val == 'bout-only' else 'blank_bracket_sheet'}_4_man",
        toolbar_html=f"""
    <div class="toolbar-filters">
      <strong>{escape(tournament_name)} — Blank Write-In Sheets</strong>
      <label>Template Size:
        <select id="f-size" onchange="applyBlankFilter()">
          <option value="4">4-Wrestler Round Robin (1 Page)</option>
          <option value="3">3-Wrestler Round Robin (1 Page)</option>
          <option value="2">2-Wrestler Best 2-of-3 (1 Page)</option>
          <option value="">All Blank Templates ({len(sizes)} Pages)</option>
        </select>
      </label>
      <label>Sheet Layout:
        <select id="f-layout" onchange="applyBlankFilter()">
          <option value="full"{full_sel}>Full Bracket + Bout Sheet</option>
          <option value="bout-only"{bout_sel}>Bout Sheet Only (No Bracket Drawing • Larger Boxes &amp; Fonts)</option>
        </select>
      </label>
      <span id="visible-count"></span>
    </div>
    <div class="toolbar-actions">
      <button class="btn-save" onclick="saveBlankPdf()" title="Save visible blank sheet(s) as PDF (pre-fills clean underscore filename)">Save as PDF</button>
      <button class="btn-save-html" onclick="saveBlankPrintout()" title="Download self-contained HTML file with current settings">Save HTML</button>
      <button onclick="saveBlankPdf()">Print Blank Sheet(s)</button>
    </div>
        """,
        cards_html=cards_html,
        script_html=f"""
    const BASE_SLUG = "{base_slug}";
    function cleanToken(val) {{
      return (val || '').toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    }}
    function getBlankBaseFilename() {{
      const szEl = document.getElementById('f-size');
      const layoutEl = document.getElementById('f-layout');
      const szPart = szEl && szEl.value ? `${{cleanToken(szEl.value)}}_man` : 'all_sizes';
      const layoutPart = layoutEl && layoutEl.value === 'bout-only' ? 'blank_bout_sheet_only' : 'blank_bracket_sheet';
      return [BASE_SLUG, layoutPart, szPart].filter(Boolean).join('_');
    }}
    function applyBlankFilter() {{
      const sz = document.getElementById('f-size').value;
      const layout = document.getElementById('f-layout').value;
      const sheets = document.querySelectorAll('.bracket-sheet');
      let shown = 0;
      sheets.forEach(s => {{
        s.classList.toggle('bout-only-sheet', layout === 'bout-only');
        if (!sz || s.dataset.size === sz) {{
          s.style.display = '';
          shown++;
        }} else {{
          s.style.display = 'none';
        }}
      }});
      document.title = getBlankBaseFilename();
      document.getElementById('visible-count').textContent = `Showing ${{shown}} blank sheet(s)`;
    }}
    function saveBlankPdf() {{
      document.title = getBlankBaseFilename();
      window.print();
    }}
    function saveBlankPrintout() {{
      const szEl = document.getElementById('f-size');
      const layoutEl = document.getElementById('f-layout');
      if (szEl) Array.from(szEl.options).forEach(o => o.toggleAttribute('selected', o.value === szEl.value));
      if (layoutEl) Array.from(layoutEl.options).forEach(o => o.toggleAttribute('selected', o.value === layoutEl.value));
      const baseName = getBlankBaseFilename();
      document.title = baseName;
      const filename = baseName + '.html';
      const htmlContent = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
      const blob = new Blob([htmlContent], {{ type: 'text/html;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }}
    applyBlankFilter();
        """,
    )
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def export_printable_html(
    result: TournamentResult,
    output_path: str | Path,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    include_bracket_diagram: bool = False,
) -> Path:
    """Generate a self-contained printable HTML file with unshaded bout score sheets and W/L tally areas."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")
    sheet_cls = "bracket-sheet" if include_bracket_diagram else "bracket-sheet bout-only-sheet"
    default_layout_val = "full" if include_bracket_diagram else "bout-only"

    divisions = sorted({g.division for g in result.groups})
    age_groups = list(dict.fromkeys(g.age_group for g in result.groups))
    skills = list(dict.fromkeys(g.skill_level for g in result.groups))
    mats = sorted({g.mat_number for g in result.groups if g.mat_number is not None})
    pod_sizes = sorted({g.size for g in result.groups if g.size > 0})

    cards_html: list[str] = []
    for g in result.groups:
        # Render SVG into DOM so the interactive toolbar can toggle between Full and Bout-Sheet-Only at any time,
        # while `.bout-only-sheet` hides the diagram and expands fonts/rows when `include_bracket_diagram=False`.
        body_html = _render_bout_and_tally_sheet(
            g,
            tournament_name=tournament_name,
            tournament_date=date_display,
            include_bracket_diagram=True,
        )
        mat_attr = str(g.mat_number) if g.mat_number is not None else "unassigned"
        search_blob = (
            f"{g.group_id} {g.division} {g.age_group} {g.skill_level} "
            + " ".join(f"{w.name} {w.display_team}" for w in g.wrestlers)
        ).lower()

        card = f"""
        <section class="{sheet_cls}"
                 data-division="{escape(g.division)}"
                 data-age="{escape(g.age_group)}"
                 data-skill="{escape(g.skill_level)}"
                 data-mat="{mat_attr}"
                 data-size="{g.size}"
                 data-search="{escape(search_blob)}"
                 data-flagged="{'true' if g.has_warnings else 'false'}">
          {body_html}
        </section>
        """
        cards_html.append(card)

    div_opts = "".join(f'<option value="{escape(d)}">{escape(d)}</option>' for d in divisions)
    age_opts = "".join(f'<option value="{escape(a)}">{escape(a)}</option>' for a in age_groups)
    skill_opts = "".join(f'<option value="{escape(s)}">{escape(s)}</option>' for s in skills)
    mat_opts = "".join(f'<option value="{m}">Mat {m}</option>' for m in mats)
    if any(g.mat_number is None for g in result.groups):
        mat_opts += '<option value="unassigned">Unassigned</option>'
    size_opts = "".join(
        f'<option value="{sz}">{sz}-Wrestler ({"Solo" if sz == 1 else "Best 2/3" if sz == 2 else f"{sz}-Man RR"})</option>'
        for sz in pod_sizes
    )
    full_sel = ' selected="selected"' if default_layout_val == "full" else ""
    bout_sel = ' selected="selected"' if default_layout_val == "bout-only" else ""
    base_slug = _fs_safe_slug(tournament_name)

    html_doc = _build_printable_html_document(
        title=f"{base_slug}_{'bout_sheets_only' if default_layout_val == 'bout-only' else 'brackets'}",
        toolbar_html=f"""
    <div class="toolbar-filters">
      <strong>{escape(tournament_name)} &mdash; Official Brackets &amp; Bout Sheets ({len(result.groups)} Brackets)</strong>
      <label>Layout:
        <select id="f-layout" onchange="applyFilters()">
          <option value="full"{full_sel}>Full Bracket + Bout Sheet</option>
          <option value="bout-only"{bout_sel}>Bout Sheet Only (No Bracket Drawing • Larger Boxes &amp; Fonts)</option>
        </select>
      </label>
      <label>Bracket Size:
        <select id="f-size" onchange="applyFilters()">
          <option value="">All Sizes</option>{size_opts}
        </select>
      </label>
      <label>Mat:
        <select id="f-mat" onchange="applyFilters()">
          <option value="">All Mats</option>{mat_opts}
        </select>
      </label>
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
      <label>Search:
        <input type="text" id="f-search" placeholder="Name or Bracket..." oninput="applyFilters()" style="width:120px;" />
      </label>
      <label>
        <input type="checkbox" id="f-flag" onchange="applyFilters()" /> &#9888; Flagged Only
      </label>
      <span id="visible-count"></span>
    </div>
    <div class="toolbar-actions">
      <button class="btn-save-html" onclick="resetBracketFilters()" title="Reset filters/search and refresh visible sheets">Refresh</button>
      <button class="btn-save" onclick="saveBracketsPdf()" title="Save visible sheets as PDF (pre-fills clean underscore filename)">Save as PDF</button>
      <button class="btn-save-html" onclick="saveBracketsPrintout()" title="Download self-contained HTML file with current layout &amp; filters">Save HTML</button>
      <button onclick="saveBracketsPdf()">Print Visible Sheets</button>
    </div>
        """,
        cards_html=cards_html,
        script_html=f"""
    const BASE_SLUG = "{base_slug}";
    function cleanToken(val) {{
      return (val || '').toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    }}
    function getBracketsBaseFilename() {{
      const layout = (document.getElementById('f-layout') || {{}}).value || 'full';
      const sz = (document.getElementById('f-size') || {{}}).value || '';
      const mat = (document.getElementById('f-mat') || {{}}).value || '';
      const div = (document.getElementById('f-div') || {{}}).value || '';
      const age = (document.getElementById('f-age') || {{}}).value || '';
      const skill = (document.getElementById('f-skill') || {{}}).value || '';
      const q = (document.getElementById('f-search') || {{}}).value || '';
      const flagEl = document.getElementById('f-flag');
      const parts = [BASE_SLUG, layout === 'bout-only' ? 'bout_sheets_only' : 'brackets'];
      if (sz) parts.push(`${{cleanToken(sz)}}_man`);
      if (mat) parts.push(mat === 'unassigned' ? 'unassigned_mat' : `mat_${{cleanToken(mat)}}`);
      if (div) parts.push(cleanToken(div));
      if (age) parts.push(cleanToken(age));
      if (skill) parts.push(cleanToken(skill));
      if (q.trim()) parts.push(cleanToken(q));
      if (flagEl && flagEl.checked) parts.push('flagged');
      return parts.filter(Boolean).join('_');
    }}
    function applyFilters() {{
      const layoutEl = document.getElementById('f-layout');
      const layout = layoutEl ? layoutEl.value : 'full';
      const szEl = document.getElementById('f-size');
      const sz = szEl ? szEl.value : '';
      const matEl = document.getElementById('f-mat');
      const mat = matEl ? matEl.value : '';
      const div = document.getElementById('f-div').value;
      const age = document.getElementById('f-age').value;
      const skill = document.getElementById('f-skill').value;
      const searchEl = document.getElementById('f-search');
      const q = (searchEl ? searchEl.value : '').trim().toLowerCase();
      const flagOnly = document.getElementById('f-flag').checked;
      const sheets = document.querySelectorAll('.bracket-sheet');
      let shown = 0;
      sheets.forEach(s => {{
        s.classList.toggle('bout-only-sheet', layout === 'bout-only');
        const matchSize = !sz || s.dataset.size === sz;
        const matchMat = !mat || s.dataset.mat === mat;
        const matchDiv = !div || s.dataset.division === div;
        const matchAge = !age || s.dataset.age === age;
        const matchSkill = !skill || s.dataset.skill === skill;
        const matchSearch = !q || (s.dataset.search || '').includes(q);
        const matchFlag = !flagOnly || s.dataset.flagged === 'true';
        if (matchSize && matchMat && matchDiv && matchAge && matchSkill && matchSearch && matchFlag) {{
          s.style.display = '';
          shown++;
        }} else {{
          s.style.display = 'none';
        }}
      }});
      document.title = getBracketsBaseFilename();
      document.getElementById('visible-count').textContent = `Showing ${{shown}} of ${{sheets.length}} brackets`;
    }}
    function saveBracketsPdf() {{
      document.title = getBracketsBaseFilename();
      window.print();
    }}
    function resetBracketFilters() {{
      ['f-size', 'f-mat', 'f-div', 'f-age', 'f-skill'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) el.value = '';
      }});
      const searchEl = document.getElementById('f-search');
      if (searchEl) searchEl.value = '';
      const flagEl = document.getElementById('f-flag');
      if (flagEl) flagEl.checked = false;
      applyFilters();
    }}
    function saveBracketsPrintout() {{
      ['f-layout', 'f-size', 'f-mat', 'f-div', 'f-age', 'f-skill'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) Array.from(el.options).forEach(o => o.toggleAttribute('selected', o.value === el.value));
      }});
      const searchEl = document.getElementById('f-search');
      if (searchEl) searchEl.setAttribute('value', searchEl.value);
      const flagEl = document.getElementById('f-flag');
      if (flagEl) flagEl.toggleAttribute('checked', flagEl.checked);
      const baseName = getBracketsBaseFilename();
      document.title = baseName;
      const filename = baseName + '.html';
      const htmlContent = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
      const blob = new Blob([htmlContent], {{ type: 'text/html;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }}
    applyFilters();
        """,
    )
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def _build_printable_html_document(
    title: str,
    toolbar_html: str,
    cards_html: list[str],
    script_html: str,
) -> str:
    """Assemble the complete printable HTML document with shared 1-page Letter portrait CSS."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{escape(title)}</title>
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
      background: #eef2f6;
    }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: #1e293b;
      color: #fff;
      padding: 10px 16px;
      border-radius: 6px;
      margin-bottom: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
    }}
    .toolbar-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      align-items: center;
      font-size: 12.5px;
    }}
    .toolbar-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .toolbar select, .toolbar input[type="text"] {{
      padding: 4px 7px;
      border-radius: 4px;
      border: 1px solid #cbd5e1;
      font-size: 12px;
      background: #fff;
      color: #000;
    }}
    .toolbar button {{
      background: #2563eb;
      color: #fff;
      border: none;
      padding: 7px 14px;
      border-radius: 4px;
      font-weight: 700;
      cursor: pointer;
      font-size: 13px;
    }}
    .toolbar .btn-save {{
      background: #0f766e;
    }}
    .toolbar .btn-save-html {{
      background: #475569;
    }}
    .bracket-sheet {{
      background: #fff;
      border: 1px solid #cbd5e1;
      padding: 0.16in 0.2in;
      margin-bottom: 20px;
      width: 100%;
      max-width: 8.1in;
      margin-left: auto;
      margin-right: auto;
      box-sizing: border-box;
      font-variant-emoji: text;
    }}
    .sheet-header {{
      border-bottom: 2.5px solid #000;
      padding-bottom: 5px;
      margin-bottom: 5px;
    }}
    .header-top-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 4px;
    }}
    .tourney-name {{
      font-size: 17px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .header-table-info {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 700;
    }}
    .doc-subtitle-badge {{
      font-size: 11px;
      font-weight: 800;
      border: 1.5px solid #000;
      padding: 1.5px 8px;
      letter-spacing: 0.02em;
    }}
    .lbl-bout-only {{ display: none; }}
    .bracket-sheet.bout-only-sheet .lbl-full {{ display: none; }}
    .bracket-sheet.bout-only-sheet .lbl-bout-only {{ display: inline; }}
    .table-field {{
      margin-left: 2px;
    }}
    .field-blank {{
      display: inline-block;
      border-bottom: 1.5px solid #000;
      vertical-align: bottom;
    }}
    .mat-blank {{ width: 50px; }}
    .mat-badge {{
      display: inline-block;
      border: 1.5px solid #000;
      padding: 1.5px 7px;
      font-weight: 900;
      font-size: 12px;
      background: #fff;
      color: #000;
    }}

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

    /* Combined Awards & Tally Section */
    .combined-tally-awards {{
      margin-bottom: 4px;
    }}
    .awards-section {{
      border: 1.5px solid #000;
      border-bottom: none;
      padding: 3px 8px;
      background: #fff;
    }}
    .awards-title {{
      font-size: 9.5px;
      font-weight: 800;
      letter-spacing: 0.03em;
      margin-bottom: 2px;
    }}
    .awards-table {{
      width: 100%;
      border-collapse: collapse;
      border: none;
      background: #fff;
      margin-bottom: 0;
    }}
    .awards-table td {{
      border: none;
      padding: 1px 4px;
      height: 17px;
      font-size: 10.5px;
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
      width: 75%;
      height: 13px;
      vertical-align: bottom;
    }}

    .tally-section {{
      margin-bottom: 0;
    }}
    .bracket-tree-section {{
      border: none;
      background: #fff;
      margin: 2px 0 4px 0;
    }}
    .bracket-tree-svg {{
      display: block;
      width: 100%;
      height: 92px;
    }}
    .tally-title {{
      font-size: 9.5px;
      font-weight: 800;
      letter-spacing: 0.03em;
      padding: 1.5px 8px;
      border: 1.5px solid #000;
      border-bottom: none;
      background: #fff;
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
      font-size: 9px;
      font-weight: 700;
      text-align: center;
      padding: 1.5px 3px;
    }}
    .tally-table td {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 10px;
      padding: 1.5px 6px;
      height: 17px;
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

    /* Main Bout Score Table — Unshaded, Crisp Black Borders, Double Height & Extra-Wide Period Boxes */
    .bout-score-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1.5px solid #000;
      margin-bottom: 4px;
      background: #fff;
    }}
    .bout-score-table th {{
      border: 1px solid #000;
      border-bottom: 1.5px solid #000;
      background: #fff;
      color: #000;
      font-size: 9.5px;
      font-weight: 700;
      text-align: center;
      padding: 1.5px 2px;
      line-height: 1.05;
    }}
    .bout-score-table td {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 10px;
      padding: 3px 4px;
      height: 38px;
      vertical-align: middle;
    }}
    /* Thick divider line between each 2-row bout pair so no shading is needed */
    .bout-score-table tr.bout-row-bottom td {{
      border-bottom: 2px solid #000;
    }}
    /* Narrowed name/bout/wt columns so the 3 Period columns get 61% of the total width */
    .col-bout {{ width: 3.8%; }}
    .col-wt {{ width: 4.7%; }}
    .col-name {{ width: 18.5%; }}
    .col-period {{ width: 20.33%; }}
    .col-pts {{ width: 4.0%; }}

    .th-bout, .th-pts {{
      font-size: 9px;
      padding: 2px 1px;
    }}
    .cell-bout {{
      text-align: center;
      font-weight: 700;
      font-size: 11px;
    }}
    .cell-wt {{
      text-align: center;
      font-weight: 600;
      font-size: 9.5px;
    }}
    .cell-name {{
      font-weight: 600;
      font-size: 9.5px;
      line-height: 1.15;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* Condensed 3-Column Match Scoring Points, Tie-Breaker & Advancement Points Section */
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
      font-size: 8.8px;
      font-weight: 700;
      text-align: left;
      padding: 2px 5px;
    }}
    .criteria-table td.criteria-cell {{
      border: 1px solid #000;
      background: #fff;
      color: #000;
      font-size: 8.6px;
      line-height: 1.18;
      padding: 2px 5px;
      vertical-align: top;
      height: auto;
    }}
    .col-crit-third {{ width: 33.33%; }}
    .crit-line {{ margin-bottom: 1px; }}
    .crit-note {{
      font-size: 8.2px;
      margin-top: 1px;
      color: #222;
    }}

    /* =========================================================================
       Bout-Sheet-Only Mode (.bout-only-sheet):
       Removes the 98px SVG bracket diagram and redistributes ~86px of vertical
       real estate into larger typography, taller W/L tally rows (20px), and
       taller 42px period scoreboxes so total page height stays ~900px (well
       under the ~960px printable Letter height, zero page-2 bleed!).
       ========================================================================= */
    .bracket-sheet.bout-only-sheet .bracket-tree-section {{
      display: none !important;
    }}
    .bracket-sheet.bout-only-sheet .tourney-name {{
      font-size: 16px;
    }}
    .bracket-sheet.bout-only-sheet .tourney-date {{
      font-size: 13.5px;
    }}
    .bracket-sheet.bout-only-sheet .header-meta-row {{
      font-size: 11.5px;
    }}
    .bracket-sheet.bout-only-sheet .meta-gid {{
      font-size: 12px;
      padding: 2px 7px;
    }}
    .bracket-sheet.bout-only-sheet .awards-section {{
      padding: 3.5px 8px;
    }}
    .bracket-sheet.bout-only-sheet .awards-title {{
      font-size: 10.5px;
      margin-bottom: 2px;
    }}
    .bracket-sheet.bout-only-sheet .awards-table td {{
      height: 19px;
      font-size: 11px;
      padding: 1.5px 5px;
    }}
    .bracket-sheet.bout-only-sheet .award-name-line {{
      height: 14px;
    }}
    .bracket-sheet.bout-only-sheet .tally-title {{
      font-size: 10.5px;
      padding: 2px 8px;
    }}
    .bracket-sheet.bout-only-sheet .tally-table th {{
      font-size: 10px;
      padding: 2px 4px;
    }}
    .bracket-sheet.bout-only-sheet .tally-table td {{
      height: 20px;
      font-size: 11px;
      padding: 2px 6px;
    }}
    .bracket-sheet.bout-only-sheet .bout-score-table th {{
      font-size: 10.5px;
      padding: 2px 2px;
    }}
    .bracket-sheet.bout-only-sheet .bout-score-table .th-bout,
    .bracket-sheet.bout-only-sheet .bout-score-table .th-pts {{
      font-size: 9.5px;
    }}
    .bracket-sheet.bout-only-sheet .bout-score-table td {{
      height: 42px;
      padding: 3px 5px;
      font-size: 11px;
    }}
    .bracket-sheet.bout-only-sheet .cell-bout {{
      font-size: 12px;
    }}
    .bracket-sheet.bout-only-sheet .cell-wt {{
      font-size: 10.5px;
    }}
    .bracket-sheet.bout-only-sheet .cell-name {{
      font-size: 10.5px;
    }}
    .bracket-sheet.bout-only-sheet .criteria-table th {{
      font-size: 9.2px;
      padding: 2px 5px;
    }}
    .bracket-sheet.bout-only-sheet .criteria-table td.criteria-cell {{
      font-size: 9px;
      line-height: 1.22;
      padding: 2px 5px;
    }}
    .bracket-sheet.bout-only-sheet .crit-note {{
      font-size: 8.5px;
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
        break-inside: avoid-page;
        page-break-after: always;
        break-after: page;
        page-break-before: auto;
        max-height: 9.9in;
      }}
      .bracket-sheet:last-child {{
        page-break-after: auto;
        break-after: auto;
      }}
    }}
  </style>
</head>
<body>
  <div class="toolbar no-print">
    {toolbar_html}
  </div>

  <main id="sheets-container">
    {"".join(cards_html)}
  </main>

  <script>
    {script_html}
  </script>
</body>
</html>
"""


def _summarize_group_warnings_and_merges(g: BracketGroup, w: object | None = None) -> list[str]:
    """Return concise human-readable warning and allowed-merge labels (with ⚠ prefix) for a bracket/wrestler."""
    badges: list[str] = []
    codes = {f.code for f in g.flags}

    if "SOLO_WRESTLER" in codes or g.size == 1:
        badges.append("⚠ SOLO WRESTLER")
    if "WEIGHT_SPREAD_PCT_EXCEEDED" in codes or "WEIGHT_SPREAD_LBS_EXCEEDED" in codes:
        badges.append(f"⚠ WT SPREAD {g.weight_spread_lbs:g}lb / {g.weight_spread_pct:.1f}%")
    if "OVERSIZED_GROUP" in codes:
        badges.append(f"⚠ {g.size}-MAN POD (>MAX {g.rule.max_group_size})")

    # Check individual or group-level merges (skill, age group, division)
    diff_skills = sorted({x.skill_level for x in g.wrestlers if x.skill_level != g.skill_level})
    if diff_skills or "SKILL_MERGED" in codes:
        if w is not None and getattr(w, "skill_level", g.skill_level) != g.skill_level:
            badges.append(f"⚠ MERGED SKILL ({getattr(w, 'skill_level')[:3].upper()}→{g.skill_level[:3].upper()})")
        elif diff_skills:
            s_lbl = "/".join(s[:3].upper() for s in diff_skills)
            badges.append(f"⚠ MERGED SKILL ({s_lbl} in {g.skill_level[:3].upper()})")
        else:
            badges.append("⚠ MERGED SKILL")

    diff_ages = sorted({x.age_group for x in g.wrestlers if x.age_group != g.age_group})
    if diff_ages or "AGE_MERGED" in codes:
        if w is not None and getattr(w, "age_group", g.age_group) != g.age_group:
            badges.append(f"⚠ MERGED AGE ({getattr(w, 'age_group')}→{g.age_group})")
        elif diff_ages:
            a_lbl = "/".join(diff_ages)
            badges.append(f"⚠ MERGED AGE ({a_lbl} in {g.age_group})")
        else:
            badges.append("⚠ MERGED AGE")

    diff_divs = sorted({x.division for x in g.wrestlers if x.division != g.division})
    if diff_divs or "DIVISION_MERGED" in codes:
        if w is not None and getattr(w, "division", g.division) != g.division:
            badges.append(f"⚠ MERGED DIV ({getattr(w, 'division')}→{g.division})")
        elif diff_divs:
            d_lbl = "/".join(diff_divs)
            badges.append(f"⚠ MERGED DIV ({d_lbl} in {g.division})")
        else:
            badges.append("⚠ MERGED DIV")

    if "TEAMMATE_CONFLICT" in codes or (g.rule.separate_teammates and g.teammate_pairs_count > 0):
        dup_teams = [f"{t} x{c}" for t, c in g.team_counts.items() if c > 1]
        badges.append(f"⚠ SAME CLUB ({', '.join(dup_teams)})" if dup_teams else "⚠ SAME CLUB")

    return badges


def export_printable_roster_html(
    result: TournamentResult,
    output_path: str | Path,
    tournament_name: str = "Wrestling Tournament",
    tournament_date: str = "",
    scratched_wrestlers: list[dict] | None = None,
    default_view: str = "alpha",
) -> Path:
    """Generate a printable Master Tournament Wrestler Roster & Mat Directory handout.

    Supports 6 instant print/handout views switchable in the toolbar (or via `default_view`):
      - `alpha`: Alphabetical Master Roster (A-Z by Wrestler Name) for Check-In, Wall Posting & Parents
      - `by-age-team`: Check-In Mode Grouped by Age Group & School / Club (`Age -> Club A-Z -> Wrestler A-Z`) for Age-Table Check-Ins
      - `by-gid`: Sorted by Bracket ID (All Wrestlers in Bracket & Seed Order)
      - `by-mat`: Grouped by Mat / Scoring Table (`Mat 1 .. Mat N`) for Mat Tables & Mat Runners
      - `by-team`: Grouped by School / Club for Coach Handouts
      - `by-bracket`: Grouped by Division, Age Group & Bracket ID for Head Table & Staging/Announcer
    Also provides a dynamic `Sort Rows` selector (`Bracket ID`, `Wrestler Name`, `Mat #`, `Weight`, `Club`, `Warnings First`)
    and prominent `⚠` warning badges for all bracket warnings and allowed merges (skill, age, division, weight spread, club).
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    date_display = tournament_date or datetime.now().strftime("%B %d, %Y")
    scratched_list = scratched_wrestlers or []

    # Collect flattened wrestler entries across all active brackets
    entries: list[dict] = []
    flagged_or_merged_group_ids: set[str] = set()
    for g_order, g in enumerate(result.groups, start=1):
        fmt_short = "Best 2/3" if (g.size == 2 or g.bracket_format == "best_of_3") else "RR"
        grp_badges = _summarize_group_warnings_and_merges(g)
        if grp_badges:
            flagged_or_merged_group_ids.add(g.group_id)

        for seed_idx, w in enumerate(g.wrestlers, start=1):
            opponents = [
                f"{other.name} ({other.team}, {other.weight:g})"
                for other in g.wrestlers
                if other.id != w.id
            ]
            opp_str = ", ".join(opponents) if opponents else "⚠ SOLO (Needs Exhibition/Merge)"
            w_badges = _summarize_group_warnings_and_merges(g, w)
            is_w_merged = (
                w.skill_level != g.skill_level
                or w.age_group != g.age_group
                or w.division != g.division
            )
            entries.append(
                {
                    "wrestler_id": w.id,
                    "name": w.name,
                    "name_sort": w.name.strip().lower(),
                    "team": w.display_team,
                    "team_raw": w.team,
                    "team_sort": w.display_team.strip().lower(),
                    "weight": w.weight,
                    "age": w.age,
                    "is_dual_entry": w.is_dual_entry,
                    "w_division": w.division,
                    "w_age_group": w.age_group,
                    "w_skill_level": w.skill_level,
                    "is_w_merged": is_w_merged,
                    "is_no_match": False,
                    "division": g.division,
                    "age_group": g.age_group,
                    "skill_level": g.skill_level,
                    "group_id": g.group_id,
                    "group_order": g_order,
                    "mat_number": g.mat_number,
                    "mat_label": g.mat_label,
                    "mat_attr": str(g.mat_number) if g.mat_number is not None else "unassigned",
                    "mat_sort": g.mat_number if g.mat_number is not None else 999,
                    "seed": seed_idx,
                    "pod_size": g.size,
                    "bout_count": len(g.bouts),
                    "fmt_short": fmt_short,
                    "weight_label": g.weight_label,
                    "spread_lbs": g.weight_spread_lbs,
                    "spread_pct": g.weight_spread_pct,
                    "opponents": opp_str,
                    "locked": g.locked,
                    "warning_badges": w_badges,
                    "has_alert": bool(w_badges),
                }
            )

    # Include any "no_match" entries directly in the roster with NO MATCH values (not Scratched)
    actual_scratches: list[dict] = []
    for nm_idx, sc in enumerate(scratched_list, start=1):
        if sc.get("entry_status") == "no_match":
            nm_name = str(sc.get("name", ""))
            nm_team = str(sc.get("team", ""))
            nm_div = str(sc.get("division", "Girls"))
            nm_age = str(sc.get("age_group", ""))
            nm_skill = str(sc.get("skill_level", ""))
            nm_wt = float(sc.get("weight", 0.0))
            entries.append(
                {
                    "wrestler_id": str(sc.get("id", f"NM{nm_idx}")),
                    "name": nm_name,
                    "name_sort": nm_name.strip().lower(),
                    "team": nm_team,
                    "team_raw": nm_team,
                    "team_sort": nm_team.strip().lower(),
                    "weight": nm_wt,
                    "age": sc.get("age"),
                    "is_dual_entry": bool(sc.get("is_dual_entry", False)),
                    "w_division": nm_div,
                    "w_age_group": nm_age,
                    "w_skill_level": nm_skill,
                    "is_w_merged": False,
                    "is_no_match": True,
                    "division": nm_div,
                    "age_group": nm_age,
                    "skill_level": nm_skill,
                    "group_id": "NO MATCH",
                    "group_order": 9990 + nm_idx,
                    "mat_number": None,
                    "mat_label": "NO MATCH",
                    "mat_attr": "unassigned",
                    "mat_sort": 999,
                    "seed": 0,
                    "pod_size": 0,
                    "bout_count": 0,
                    "fmt_short": "NO MATCH",
                    "weight_label": "No Match",
                    "spread_lbs": 0.0,
                    "spread_pct": 0.0,
                    "opponents": str(sc.get("reason", f"NO MATCH (No {nm_div} opponent within weight range)")),
                    "locked": False,
                    "warning_badges": ["⚠ NO MATCH"],
                    "has_alert": True,
                }
            )
        else:
            actual_scratches.append(sc)

    total_entries = len(entries)
    total_brackets = len(result.groups)
    total_bouts = sum(len(g.bouts) for g in result.groups)
    total_warn_brackets = len(flagged_or_merged_group_ids)

    divisions = sorted({e["division"] for e in entries})
    age_groups = list(dict.fromkeys(e["age_group"] for e in entries))
    skills = list(dict.fromkeys(e["skill_level"] for e in entries))
    teams = sorted({e["team"] for e in entries}, key=lambda s: s.lower())
    mats = sorted({g.mat_number for g in result.groups if g.mat_number is not None})
    has_unassigned_mat = any(g.mat_number is None for g in result.groups)
    pod_sizes = sorted({e["pod_size"] for e in entries if e["pod_size"] > 0})
    has_no_match_entries = any(e.get("is_no_match") for e in entries)

    # Build Mat Load Summary strip
    mat_summary_cards: list[str] = []
    for m in mats:
        m_grps = [g for g in result.groups if g.mat_number == m]
        m_wrestlers = sum(g.size for g in m_grps)
        m_bouts = sum(len(g.bouts) for g in m_grps)
        m_warns = sum(1 for g in m_grps if g.group_id in flagged_or_merged_group_ids)
        warn_suffix = f" &bull; &#9888;&#xFE0E; {m_warns} Flagged/Merged" if m_warns else ""
        mat_summary_cards.append(
            f'<div class="mat-stat-chip">'
            f'<span class="mat-chip-title">MAT {m}</span>'
            f'<span class="mat-chip-detail">{len(m_grps)} Brackets &bull; {m_wrestlers} Wrestlers &bull; {m_bouts} Bouts{warn_suffix}</span>'
            f"</div>"
        )
    if has_unassigned_mat:
        u_grps = [g for g in result.groups if g.mat_number is None]
        u_wrestlers = sum(g.size for g in u_grps)
        u_bouts = sum(len(g.bouts) for g in u_grps)
        mat_summary_cards.append(
            f'<div class="mat-stat-chip">'
            f'<span class="mat-chip-title">UNASSIGNED</span>'
            f'<span class="mat-chip-detail">{len(u_grps)} Brackets &bull; {u_wrestlers} Wrestlers &bull; {u_bouts} Bouts</span>'
            f"</div>"
        )

    def _render_roster_row(e: dict) -> str:
        dual_tag = ' <span class="tag-dual">DUAL</span>' if e["is_dual_entry"] else ""
        w_merge_icon = ' <span class="tag-warn" title="Wrestler merged across age/skill/division">&#9888;&#xFE0E; MERGED</span>' if e["is_w_merged"] else ""
        if e.get("is_no_match"):
            mat_badge = '<span class="roster-mat-unassigned">NO MATCH</span>'
        elif e["mat_number"] is not None:
            mat_badge = f'<span class="roster-mat-badge">MAT {e["mat_number"]}</span>'
        else:
            mat_badge = '<span class="roster-mat-unassigned">UNASSIGNED</span>'
        skill_short = e["skill_level"][:3].upper()
        # Show wrestler's original age/skill if merged into a different bracket age/skill
        if e["is_w_merged"]:
            orig_short = f"{e['w_age_group']} {e['w_skill_level'][:3].upper()}"
            div_cell_html = (
                f"{escape(e['division'])} &bull; {escape(e['age_group'])} &bull; {escape(skill_short)}"
                f'<span class="gid-sub"><strong>&#9888;&#xFE0E; Reg: {escape(orig_short)}</strong></span>'
            )
        else:
            div_cell_html = f"{escape(e['division'])} &bull; {escape(e['age_group'])} &bull; {escape(skill_short)}"

        warn_badges_html = ""
        if e["warning_badges"]:
            warn_pills = "".join(
                f'<span class="tag-warn-pill">{escape(b)}</span>' for b in e["warning_badges"]
            )
            warn_badges_html = f'<div class="warn-pill-wrap">{warn_pills}</div>'

        gid_warn_icon = ' <span class="tag-warn">&#9888;&#xFE0E;</span>' if e["has_alert"] else ""
        row_cls = "roster-row has-warning-row" if e["has_alert"] else "roster-row"

        if e.get("is_no_match"):
            gid_cell_html = (
                f'<strong>NO MATCH</strong>{gid_warn_icon} '
                f'<span class="gid-sub">(No opponent in weight range)</span>'
                f"{warn_badges_html}"
            )
            seed_cell_html = '<strong>NO MATCH</strong> <span class="gid-sub">(0b)</span>'
        else:
            gid_cell_html = (
                f'<strong>{escape(e["group_id"])}</strong>{gid_warn_icon} '
                f'<span class="gid-sub">({escape(e["weight_label"])} &bull; {e["spread_lbs"]:g}lb/{e["spread_pct"]:.1f}%)</span>'
                f"{warn_badges_html}"
            )
            seed_cell_html = (
                f'#{e["seed"]} of {e["pod_size"]} '
                f'<span class="gid-sub">({e["fmt_short"]} &bull; {e["bout_count"]}b)</span>'
            )

        return (
            f'<tr class="{row_cls}" '
            f'data-division="{escape(e["division"])}" '
            f'data-age="{escape(e["age_group"])}" '
            f'data-skill="{escape(e["skill_level"])}" '
            f'data-mat="{escape(e["mat_attr"])}" '
            f'data-mat-num="{e["mat_sort"]}" '
            f'data-team="{escape(e["team"])}" '
            f'data-team-sort="{escape(e["team_sort"])}" '
            f'data-name="{escape(e["name_sort"])}" '
            f'data-gid="{escape(e["group_id"])}" '
            f'data-gorder="{e["group_order"]}" '
            f'data-seed="{e["seed"]}" '
            f'data-size="{e["pod_size"]}" '
            f'data-weight="{e["weight"]}" '
            f'data-alert="{"1" if e["has_alert"] else "0"}">'
            f'<td class="col-chk"><span class="chk-box"></span></td>'
            f'<td class="col-wname"><strong>{escape(e["name"])}</strong>{dual_tag}{w_merge_icon}</td>'
            f'<td class="col-wteam">{escape(e["team"])}</td>'
            f'<td class="col-wwt">{e["weight"]:g}</td>'
            f'<td class="col-wdiv">{div_cell_html}</td>'
            f'<td class="col-wmat">{mat_badge}</td>'
            f'<td class="col-wgid">{gid_cell_html}</td>'
            f'<td class="col-wseed">{seed_cell_html}</td>'
            f'<td class="col-wopp">{escape(e["opponents"])}</td>'
            f"</tr>"
        )

    table_thead = (
        "<thead><tr>"
        '<th class="col-chk">&#10003;</th>'
        '<th class="col-wname">WRESTLER NAME</th>'
        '<th class="col-wteam">SCHOOL / CLUB</th>'
        '<th class="col-wwt">WT</th>'
        '<th class="col-wdiv">DIV / AGE / SKILL</th>'
        '<th class="col-wmat">MAT #</th>'
        '<th class="col-wgid">BRACKET ID, WEIGHTS &amp; &#9888;&#xFE0E; WARNINGS / MERGES</th>'
        '<th class="col-wseed">SEED / POD</th>'
        '<th class="col-wopp">POD OPPONENTS (CLUB, WT)</th>'
        "</tr></thead>"
    )

    # 1. Alphabetical View (A-Z by Wrestler Name)
    alpha_entries = sorted(entries, key=lambda x: (x["name_sort"], x["weight"], x["group_id"]))
    alpha_rows = "".join(_render_roster_row(e) for e in alpha_entries)
    alpha_section_html = f"""
    <div class="roster-view-pane" id="view-alpha" data-view="alpha">
      <div class="section-banner">
        <span>ALPHABETICAL MASTER WRESTLER DIRECTORY (A&ndash;Z)</span>
        <span class="banner-sub">Check-In Desk, Wall Posting &amp; Parent/Coach Lookup</span>
      </div>
      <table class="roster-table">
        {table_thead}
        <tbody>{alpha_rows}</tbody>
      </table>
    </div>
    """

    # 1B. Sorted by Bracket ID View (All Brackets in ID & Seed Order)
    gid_entries = sorted(entries, key=lambda x: (x["group_order"], x["group_id"], x["seed"], x["weight"]))
    gid_rows = "".join(_render_roster_row(e) for e in gid_entries)
    by_gid_section_html = f"""
    <div class="roster-view-pane" id="view-by-gid" data-view="by-gid" style="display:none;">
      <div class="section-banner">
        <span>MASTER ROSTER SORTED BY BRACKET ID (A&ndash;Z &bull; SEED ORDER)</span>
        <span class="banner-sub">Head Table Master Checklist &bull; Includes &#9888; Bracket Warnings &amp; Allowed Merges</span>
      </div>
      <table class="roster-table">
        {table_thead}
        <tbody>{gid_rows}</tbody>
      </table>
    </div>
    """

    # 2. Grouped by Mat / Scoring Table View
    mat_blocks_html: list[str] = []
    mat_keys: list[int | None] = list(mats) + ([None] if has_unassigned_mat else [])
    for m_val in mat_keys:
        m_label = f"MAT {m_val}" if m_val is not None else "UNASSIGNED MAT"
        m_attr = str(m_val) if m_val is not None else "unassigned"
        m_entries = [e for e in entries if e["mat_number"] == m_val and not e.get("is_no_match")]
        m_grps = [g for g in result.groups if g.mat_number == m_val]
        m_bouts = sum(len(g.bouts) for g in m_grps)
        m_brackets_parts: list[str] = []
        for g in m_grps:
            g_warns = _summarize_group_warnings_and_merges(g)
            w_mark = f" [{' | '.join(g_warns)}]" if g_warns else ""
            m_brackets_parts.append(
                f"{g.group_id} ({g.age_group} {g.skill_level[:3].upper()}, {g.weight_label}, {len(g.bouts)}b){w_mark}"
            )
        m_brackets_str = ", ".join(m_brackets_parts)
        m_rows = "".join(_render_roster_row(e) for e in m_entries)
        mat_blocks_html.append(
            f"""
            <section class="roster-group-block" data-mat-group="{m_attr}">
              <div class="section-banner">
                <span>{escape(m_label)} &mdash; TABLE ROSTER &amp; BRACKET CHECKLIST</span>
                <span class="banner-sub">{len(m_grps)} Brackets &bull; {len(m_entries)} Wrestlers &bull; {m_bouts} Total Bouts</span>
              </div>
              <div class="mat-brackets-strip"><strong>Assigned Brackets in Order:</strong> {escape(m_brackets_str)}</div>
              <table class="roster-table">
                {table_thead}
                <tbody>{m_rows}</tbody>
              </table>
            </section>
            """
        )
    by_mat_section_html = f"""
    <div class="roster-view-pane" id="view-by-mat" data-view="by-mat" style="display:none;">
      {"".join(mat_blocks_html)}
    </div>
    """

    # 3. Grouped by School / Club View
    team_blocks_html: list[str] = []
    for tm in teams:
        t_entries = sorted(
            [e for e in entries if e["team"] == tm],
            key=lambda x: (x["age_group"], x["weight"], x["name_sort"]),
        )
        t_rows = "".join(_render_roster_row(e) for e in t_entries)
        team_blocks_html.append(
            f"""
            <section class="roster-group-block" data-team-group="{escape(tm)}">
              <div class="section-banner">
                <span>SCHOOL / CLUB: {escape(tm.upper())}</span>
                <span class="banner-sub">{len(t_entries)} Wrestler(s) &bull; Coach Handout &amp; Mat Assignments</span>
              </div>
              <table class="roster-table">
                {table_thead}
                <tbody>{t_rows}</tbody>
              </table>
            </section>
            """
        )
    by_team_section_html = f"""
    <div class="roster-view-pane" id="view-by-team" data-view="by-team" style="display:none;">
      {"".join(team_blocks_html)}
    </div>
    """

    # 4. Grouped by Division & Age Group (Bracket Order)
    div_age_keys = list(dict.fromkeys((e["division"], e["age_group"]) for e in entries))
    bracket_blocks_html: list[str] = []
    for div_name, age_name in div_age_keys:
        da_entries = [e for e in entries if e["division"] == div_name and e["age_group"] == age_name]
        da_grps = [g for g in result.groups if g.division == div_name and g.age_group == age_name]
        da_bouts = sum(len(g.bouts) for g in da_grps)
        da_rows = "".join(_render_roster_row(e) for e in da_entries)
        bracket_blocks_html.append(
            f"""
            <section class="roster-group-block" data-div-group="{escape(div_name)}" data-age-group="{escape(age_name)}">
              <div class="section-banner">
                <span>{escape(div_name.upper())} &bull; {escape(age_name)} DIVISION ROSTER</span>
                <span class="banner-sub">{len(da_grps)} Brackets &bull; {len(da_entries)} Wrestlers &bull; {da_bouts} Bouts</span>
              </div>
              <table class="roster-table">
                {table_thead}
                <tbody>{da_rows}</tbody>
              </table>
            </section>
            """
        )
    by_bracket_section_html = f"""
    <div class="roster-view-pane" id="view-by-bracket" data-view="by-bracket" style="display:none;">
      {"".join(bracket_blocks_html)}
    </div>
    """

    # 5. Check-In Mode: Grouped by Age Group & School / Club (Age Table Check-In)
    age_team_blocks_html: list[str] = []
    for age_name in age_groups:
        age_entries_all = [e for e in entries if e["age_group"] == age_name]
        if not age_entries_all:
            continue
        age_teams = sorted({e["team"] for e in age_entries_all}, key=lambda s: s.lower())
        age_grps = [g for g in result.groups if g.age_group == age_name]
        age_mats = sorted({g.mat_number for g in age_grps if g.mat_number is not None})
        age_mats_str = ", ".join(f"Mat {m}" for m in age_mats) if age_mats else "Unassigned"
        club_subblocks: list[str] = []
        for tm in age_teams:
            at_entries = sorted(
                [e for e in age_entries_all if e["team"] == tm],
                key=lambda x: (x["name_sort"], x["weight"], x["group_id"]),
            )
            at_rows = "".join(_render_roster_row(e) for e in at_entries)
            club_subblocks.append(
                f"""
                <div class="roster-club-subblock" data-team-group="{escape(tm)}">
                  <div class="sub-banner">
                    <span>{escape(age_name)} &bull; SCHOOL / CLUB: {escape(tm.upper())}</span>
                    <span class="banner-sub">{len(at_entries)} Wrestler(s) &bull; Sorted A&ndash;Z for Fast Check-In</span>
                  </div>
                  <table class="roster-table">
                    {table_thead}
                    <tbody>{at_rows}</tbody>
                  </table>
                </div>
                """
            )
        age_team_blocks_html.append(
            f"""
            <section class="roster-group-block" data-age-group="{escape(age_name)}">
              <div class="section-banner age-checkin-banner">
                <span>CHECK-IN TABLE: {escape(age_name)} AGE GROUP &mdash; BY SCHOOL / CLUB</span>
                <span class="banner-sub">{len(age_teams)} Club(s) &bull; {len(age_entries_all)} Wrestlers &bull; {len(age_grps)} Brackets &bull; Mats: {escape(age_mats_str)}</span>
              </div>
              <div class="mat-brackets-strip"><strong>Clubs in {escape(age_name)} ({len(age_teams)}):</strong> {escape(", ".join(age_teams))}</div>
              {"".join(club_subblocks)}
            </section>
            """
        )
    by_age_team_section_html = f"""
    <div class="roster-view-pane" id="view-by-age-team" data-view="by-age-team" style="display:none;">
      {"".join(age_team_blocks_html)}
    </div>
    """

    # Optional Scratched / No-Show Table (excludes "no_match" entries)
    scratched_html = ""
    if actual_scratches:
        s_rows: list[str] = []
        for sc in actual_scratches:
            orig_gids = ", ".join(sc.get("original_brackets", sc.get("original_groups", []))) or "—"
            orig_mats_dict = sc.get("original_mats") or {}
            orig_mats_str = ", ".join(
                f"Mat {m}" for m in orig_mats_dict.values() if m is not None
            ) or "—"
            s_rows.append(
                f"<tr>"
                f"<td><strong>{escape(str(sc.get('name', '')))}</strong></td>"
                f"<td>{escape(str(sc.get('team', '')))}</td>"
                f'<td style="text-align:center;">{sc.get("weight", "")}</td>'
                f"<td>{escape(str(sc.get('division', '')))} &bull; {escape(str(sc.get('age_group', '')))} &bull; {escape(str(sc.get('skill_level', '')))}</td>"
                f'<td style="text-align:center;">{escape(orig_mats_str)}</td>'
                f"<td>{escape(orig_gids)}</td>"
                f"<td>{escape(str(sc.get('reason', 'Scratched')))}</td>"
                f"</tr>"
            )
        scratched_html = f"""
        <section class="scratched-section" id="scratched-block">
          <div class="section-banner scratched-banner">
            <span>SCRATCHED / NO-SHOW WRESTLERS ({len(actual_scratches)})</span>
            <span class="banner-sub">Removed from active brackets</span>
          </div>
          <table class="roster-table">
            <thead>
              <tr>
                <th>WRESTLER NAME</th><th>SCHOOL / CLUB</th><th>WT</th>
                <th>DIV / AGE / SKILL</th><th>ORIG MAT</th><th>ORIG BRACKET</th><th>REASON</th>
              </tr>
            </thead>
            <tbody>{"".join(s_rows)}</tbody>
          </table>
        </section>
        """

    div_opts = "".join(f'<option value="{escape(d)}">{escape(d)}</option>' for d in divisions)
    age_opts = "".join(f'<option value="{escape(a)}">{escape(a)}</option>' for a in age_groups)
    skill_opts = "".join(f'<option value="{escape(s)}">{escape(s)}</option>' for s in skills)
    team_opts = "".join(f'<option value="{escape(t)}">{escape(t)}</option>' for t in teams)
    mat_opts = "".join(f'<option value="{m}">Mat {m}</option>' for m in mats)
    if has_unassigned_mat:
        mat_opts += '<option value="unassigned">Unassigned</option>'
    size_opts_parts: list[str] = []
    for sz in pod_sizes:
        sz_grp_cnt = sum(1 for g in result.groups if g.size == sz)
        sz_lbl = f"{sz}-Man ({sz_grp_cnt} brk)" if sz > 1 else f"1-Man Solo ({sz_grp_cnt} brk)"
        size_opts_parts.append(f'<option value="{sz}">{sz_lbl}</option>')
    if any(s in pod_sizes for s in (1, 2)):
        sm_cnt = sum(1 for g in result.groups if g.size <= 2)
        size_opts_parts.append(f'<option value="le2">&#8804;2-Man ({sm_cnt} brk)</option>')
    if any(s in pod_sizes for s in (1, 2, 3)):
        lt4_cnt = sum(1 for g in result.groups if g.size <= 3)
        size_opts_parts.append(f'<option value="le3">&#8804;3-Man ({lt4_cnt} brk)</option>')
    if has_no_match_entries:
        nm_cnt = sum(1 for e in entries if e.get("is_no_match"))
        size_opts_parts.append(f'<option value="0">No Match ({nm_cnt})</option>')
    size_opts = "".join(size_opts_parts)

    sel_alpha = ' selected="selected"' if default_view == "alpha" else ""
    sel_age_team = ' selected="selected"' if default_view == "by-age-team" else ""
    sel_gid = ' selected="selected"' if default_view == "by-gid" else ""
    sel_mat = ' selected="selected"' if default_view == "by-mat" else ""
    sel_team = ' selected="selected"' if default_view == "by-team" else ""
    sel_brk = ' selected="selected"' if default_view == "by-bracket" else ""
    base_slug = _fs_safe_slug(tournament_name)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{escape(base_slug)}_roster_a_z</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 0.3in;
    }}
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #000;
      background: #eef2f6;
      margin: 0;
      padding: 12px;
    }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: #1e293b;
      color: #fff;
      padding: 10px 16px;
      border-radius: 6px;
      margin-bottom: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .toolbar-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      align-items: center;
      font-size: 12.5px;
    }}
    .toolbar select, .toolbar input[type="text"] {{
      padding: 4px 7px;
      border-radius: 4px;
      border: 1px solid #cbd5e1;
      font-size: 12px;
    }}
    .toolbar button {{
      background: #2563eb;
      color: #fff;
      border: none;
      padding: 7px 14px;
      border-radius: 4px;
      font-weight: 700;
      cursor: pointer;
      font-size: 13px;
    }}
    .toolbar .btn-save {{
      background: #0f766e;
    }}
    .toolbar .btn-save-html {{
      background: #475569;
    }}
    .toolbar-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .roster-page-wrap {{
      width: 100%;
      max-width: 8.1in;
      margin: 0 auto;
      background: #fff;
      padding: 0.2in;
      border: 1px solid #cbd5e1;
      font-variant-emoji: text;
    }}
    .roster-header {{
      border-bottom: 2.5px solid #000;
      padding-bottom: 6px;
      margin-bottom: 8px;
    }}
    .roster-title-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .roster-tourney-name {{
      font-size: 18px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .roster-doc-subtitle {{
      font-size: 12px;
      font-weight: 800;
      border: 1.5px solid #000;
      padding: 2px 8px;
    }}
    .roster-stats-row {{
      font-size: 11px;
      margin-top: 4px;
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
    }}
    .mat-summary-grid {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 10px;
    }}
    .mat-stat-chip {{
      border: 1.5px solid #000;
      padding: 3px 8px;
      font-size: 10px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .mat-chip-title {{
      font-weight: 900;
      font-size: 10.5px;
      border-right: 1px solid #000;
      padding-right: 6px;
    }}
    .section-banner {{
      border: 1.5px solid #000;
      border-bottom: none;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 900;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 8px;
      background: #fff;
    }}
    .banner-sub {{
      font-size: 9.5px;
      font-weight: 700;
    }}
    .age-checkin-banner {{
      border-bottom: 1.5px solid #000;
      margin-bottom: 0;
    }}
    .roster-club-subblock {{
      margin-top: 6px;
    }}
    .sub-banner {{
      border: 1.5px solid #000;
      border-bottom: none;
      padding: 3px 8px;
      font-size: 10px;
      font-weight: 900;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #fff;
    }}
    .mat-brackets-strip {{
      border-left: 1.5px solid #000;
      border-right: 1.5px solid #000;
      border-bottom: 1.5px solid #000;
      padding: 3px 8px;
      font-size: 9px;
      line-height: 1.3;
    }}
    .roster-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1.5px solid #000;
      margin-bottom: 8px;
    }}
    .roster-table thead {{
      display: table-header-group;
    }}
    .roster-table tr {{
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .roster-table th {{
      border: 1px solid #000;
      border-bottom: 1.8px solid #000;
      font-size: 9px;
      font-weight: 900;
      text-align: left;
      padding: 3px 4px;
      background: #fff;
    }}
    .roster-table td {{
      border: 1px solid #000;
      font-size: 9.5px;
      padding: 3px 4px;
      vertical-align: middle;
      line-height: 1.2;
    }}
    .col-chk {{ width: 3.0%; text-align: center !important; }}
    .col-wname {{ width: 16.5%; }}
    .col-wteam {{ width: 11.5%; }}
    .col-wwt {{ width: 5.0%; text-align: center !important; font-weight: 700; }}
    .col-wdiv {{ width: 12.0%; font-size: 8.8px !important; }}
    .col-wmat {{ width: 7.5%; text-align: center !important; }}
    .col-wgid {{ width: 19.5%; }}
    .col-wseed {{ width: 9.5%; font-size: 8.8px !important; }}
    .col-wopp {{ width: 15.5%; font-size: 8.6px !important; }}
    .chk-box {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border: 1.3px solid #000;
    }}
    .roster-mat-badge {{
      display: inline-block;
      border: 1.5px solid #000;
      padding: 1px 5px;
      font-weight: 900;
      font-size: 9.2px;
      letter-spacing: 0.02em;
    }}
    .roster-mat-unassigned {{
      font-size: 8.2px;
      color: #444;
    }}
    .gid-sub {{
      display: block;
      font-size: 8.1px;
      font-weight: 400;
    }}
    .tag-dual, .tag-warn {{
      display: inline-block;
      border: 1.2px solid #000;
      font-size: 7.8px;
      font-weight: 900;
      padding: 0 3px;
      margin-left: 2px;
    }}
    .warn-pill-wrap {{
      margin-top: 2px;
      display: flex;
      flex-wrap: wrap;
      gap: 2px;
    }}
    .tag-warn-pill {{
      display: inline-block;
      border: 1.2px solid #000;
      font-size: 7.8px;
      font-weight: 900;
      padding: 0.5px 3.5px;
      letter-spacing: 0.01em;
    }}
    .page-break-group .roster-group-block {{
      page-break-after: always;
      break-after: page;
    }}
    .page-break-group .roster-group-block:last-child {{
      page-break-after: auto;
      break-after: auto;
    }}
    @media print {{
      body {{
        background: #fff;
        padding: 0;
        margin: 0;
      }}
      .no-print, .toolbar {{
        display: none !important;
      }}
      .roster-page-wrap {{
        max-width: 100%;
        border: none;
        padding: 0;
        margin: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="toolbar no-print">
    <div class="toolbar-filters">
      <strong>{escape(tournament_name)} &mdash; Master Roster</strong>
      <label>Handout View:
        <select id="r-view" onchange="applyRosterFilters()">
          <option value="alpha"{sel_alpha}>Alphabetical (A&ndash;Z All Wrestlers)</option>
          <option value="by-age-team"{sel_age_team}>Check-In by Age Group &amp; Club (Age Check-In Tables)</option>
          <option value="by-gid"{sel_gid}>Sorted by Bracket ID (All Brackets)</option>
          <option value="by-mat"{sel_mat}>Grouped by Mat # (Table Handouts)</option>
          <option value="by-team"{sel_team}>Grouped by School / Club (Coach Handouts)</option>
          <option value="by-bracket"{sel_brk}>Grouped by Division &amp; Age (Staging / Announcer)</option>
        </select>
      </label>
      <label>Sort Rows:
        <select id="r-sort" onchange="applyRosterFilters()">
          <option value="gid" selected="selected">Bracket ID (A&ndash;Z &rarr; Seed)</option>
          <option value="default">Default for View</option>
          <option value="name">Wrestler Name (A&ndash;Z)</option>
          <option value="mat">Mat # &rarr; Bracket ID</option>
          <option value="weight">Weight (Low &rarr; High)</option>
          <option value="team">School / Club (A&ndash;Z)</option>
          <option value="size-asc">Bracket Size (Small &rarr; Large)</option>
          <option value="size-desc">Bracket Size (Large &rarr; Small)</option>
          <option value="warn">&#9888; Warnings &amp; Merges First</option>
        </select>
      </label>
      <label>Bracket Size:
        <select id="r-size" onchange="applyRosterFilters()">
          <option value="">All Sizes</option>
          {size_opts}
        </select>
      </label>
      <label>Mat:
        <select id="r-mat" onchange="applyRosterFilters()">
          <option value="">All Mats</option>
          {mat_opts}
        </select>
      </label>
      <label>Division:
        <select id="r-div" onchange="applyRosterFilters()">
          <option value="">All</option>
          {div_opts}
        </select>
      </label>
      <label>Age:
        <select id="r-age" onchange="applyRosterFilters()">
          <option value="">All</option>
          {age_opts}
        </select>
      </label>
      <label>Skill:
        <select id="r-skill" onchange="applyRosterFilters()">
          <option value="">All</option>
          {skill_opts}
        </select>
      </label>
      <label>Club:
        <select id="r-team" onchange="applyRosterFilters()">
          <option value="">All Clubs</option>
          {team_opts}
        </select>
      </label>
      <label>Search:
        <input type="text" id="r-search" placeholder="Name or Bracket..." oninput="applyRosterFilters()" style="width:115px;" />
      </label>
      <label title="Show only brackets/wrestlers with warnings or allowed skill/age/division merges">
        <input type="checkbox" id="r-warn-only" onchange="applyRosterFilters()" />
        &#9888; Warnings/Merges Only
      </label>
      <label>
        <input type="checkbox" id="r-pagebreak" onchange="applyRosterFilters()" />
        1 Age/Mat/Club Per Page
      </label>
      <span id="r-visible-count"></span>
    </div>
    <div class="toolbar-actions">
      <button class="btn-save-html" onclick="resetRosterFilters()" title="Reset filters/search and refresh roster view">Refresh</button>
      <button class="btn-save" onclick="saveRosterPdf()" title="Save visible roster view as PDF (pre-fills clean underscore filename)">Save as PDF</button>
      <button class="btn-save-html" onclick="saveRosterPrintout()" title="Download self-contained HTML file with current view &amp; filters">Save HTML</button>
      <button onclick="saveRosterPdf()">Print Roster Handout</button>
    </div>
  </div>

  <main class="roster-page-wrap" id="roster-main">
    <header class="roster-header">
      <div class="roster-title-row">
        <span class="roster-tourney-name">{escape(tournament_name)} &bull; {escape(date_display)}</span>
        <span class="roster-doc-subtitle" id="r-doc-badge">MASTER WRESTLER &amp; MAT DIRECTORY</span>
      </div>
      <div class="roster-stats-row">
        <span><strong>Active Wrestler Entries:</strong> {total_entries}</span>
        <span><strong>Total Brackets:</strong> {total_brackets}</span>
        <span><strong>Total Scheduled Bouts:</strong> {total_bouts}</span>
        <span><strong>Active Mats:</strong> {len(mats) or 1}</span>
        <span><strong>&#9888;&#xFE0E; Brackets w/ Warnings or Merges:</strong> {total_warn_brackets}</span>
      </div>
    </header>

    <div class="mat-summary-grid">
      {"".join(mat_summary_cards)}
    </div>

    {alpha_section_html}
    {by_age_team_section_html}
    {by_gid_section_html}
    {by_mat_section_html}
    {by_team_section_html}
    {by_bracket_section_html}
    {scratched_html}
  </main>

  <script>
    function compareRows(a, b, sortMode) {{
      if (sortMode === 'gid') {{
        const c = (a.dataset.gid || '').localeCompare(b.dataset.gid || '');
        if (c !== 0) return c;
        return (parseInt(a.dataset.seed || '0', 10) - parseInt(b.dataset.seed || '0', 10));
      }}
      if (sortMode === 'name') {{
        return (a.dataset.name || '').localeCompare(b.dataset.name || '');
      }}
      if (sortMode === 'mat') {{
        const ma = parseInt(a.dataset.matNum || '999', 10);
        const mb = parseInt(b.dataset.matNum || '999', 10);
        if (ma !== mb) return ma - mb;
        const c = (a.dataset.gid || '').localeCompare(b.dataset.gid || '');
        if (c !== 0) return c;
        return (parseInt(a.dataset.seed || '0', 10) - parseInt(b.dataset.seed || '0', 10));
      }}
      if (sortMode === 'weight') {{
        const wa = parseFloat(a.dataset.weight || '0');
        const wb = parseFloat(b.dataset.weight || '0');
        if (wa !== wb) return wa - wb;
        return (a.dataset.name || '').localeCompare(b.dataset.name || '');
      }}
      if (sortMode === 'team') {{
        const c = (a.dataset.teamSort || '').localeCompare(b.dataset.teamSort || '');
        if (c !== 0) return c;
        return (a.dataset.name || '').localeCompare(b.dataset.name || '');
      }}
      if (sortMode === 'size-asc' || sortMode === 'size-desc') {{
        const sa = parseInt(a.dataset.size || '0', 10);
        const sb = parseInt(b.dataset.size || '0', 10);
        if (sa !== sb) return sortMode === 'size-asc' ? (sa - sb) : (sb - sa);
        const c = (a.dataset.gid || '').localeCompare(b.dataset.gid || '');
        if (c !== 0) return c;
        return (parseInt(a.dataset.seed || '0', 10) - parseInt(b.dataset.seed || '0', 10));
      }}
      if (sortMode === 'warn') {{
        const wa = parseInt(b.dataset.alert || '0', 10) - parseInt(a.dataset.alert || '0', 10);
        if (wa !== 0) return wa;
        const c = (a.dataset.gid || '').localeCompare(b.dataset.gid || '');
        if (c !== 0) return c;
        return (parseInt(a.dataset.seed || '0', 10) - parseInt(b.dataset.seed || '0', 10));
      }}
      return 0;
    }}

    function applyRosterFilters() {{
      const view = document.getElementById('r-view').value;
      const sortMode = document.getElementById('r-sort').value;
      const sizeVal = document.getElementById('r-size').value;
      const mat = document.getElementById('r-mat').value;
      const div = document.getElementById('r-div').value;
      const age = document.getElementById('r-age').value;
      const skill = document.getElementById('r-skill').value;
      const team = document.getElementById('r-team').value;
      const q = (document.getElementById('r-search').value || '').trim().toLowerCase();
      const warnOnly = document.getElementById('r-warn-only').checked;
      const pageBreak = document.getElementById('r-pagebreak').checked;

      const mainEl = document.getElementById('roster-main');
      mainEl.classList.toggle('page-break-group', pageBreak);

      const badgeMap = {{
        'alpha': 'MASTER WRESTLER & MAT DIRECTORY (A-Z)',
        'by-age-team': 'AGE GROUP & CLUB CHECK-IN TABLE ROSTER',
        'by-gid': 'MASTER ROSTER SORTED BY BRACKET ID',
        'by-mat': 'MAT TABLE & RUNNER ROSTER CHECKLIST',
        'by-team': 'CLUB / COACH ROSTER & MAT ASSIGNMENTS',
        'by-bracket': 'DIVISION & AGE GROUP STAGING DIRECTORY'
      }};
      document.getElementById('r-doc-badge').textContent = badgeMap[view] || 'MASTER WRESTLER & MAT DIRECTORY';

      const panes = document.querySelectorAll('.roster-view-pane');
      let shownRows = 0;

      panes.forEach(pane => {{
        const isCurrent = pane.dataset.view === view;
        pane.style.display = isCurrent ? '' : 'none';
        if (!isCurrent) return;

        if (sortMode !== 'default') {{
          pane.querySelectorAll('tbody').forEach(tbody => {{
            const trs = Array.from(tbody.querySelectorAll('.roster-row'));
            trs.sort((a, b) => compareRows(a, b, sortMode));
            trs.forEach(tr => tbody.appendChild(tr));
          }});
        }}

        const rows = pane.querySelectorAll('.roster-row');
        rows.forEach(r => {{
          let ok = true;
          if (sizeVal) {{
            const rSz = parseInt(r.dataset.size || '0', 10);
            if (sizeVal === 'le2') {{
              if (rSz < 1 || rSz > 2) ok = false;
            }} else if (sizeVal === 'le3') {{
              if (rSz < 1 || rSz > 3) ok = false;
            }} else if (String(rSz) !== sizeVal) {{
              ok = false;
            }}
          }}
          if (mat && r.dataset.mat !== mat) ok = false;
          if (div && r.dataset.division !== div) ok = false;
          if (age && r.dataset.age !== age) ok = false;
          if (skill && r.dataset.skill !== skill) ok = false;
          if (team && r.dataset.team !== team) ok = false;
          if (warnOnly && r.dataset.alert !== '1') ok = false;
          if (q && !r.textContent.toLowerCase().includes(q)) ok = false;
          r.style.display = ok ? '' : 'none';
          if (ok) shownRows++;
        }});

        const subblocks = pane.querySelectorAll('.roster-club-subblock');
        subblocks.forEach(sb => {{
          const visibleInSub = Array.from(sb.querySelectorAll('.roster-row')).some(r => r.style.display !== 'none');
          sb.style.display = visibleInSub ? '' : 'none';
        }});

        const blocks = pane.querySelectorAll('.roster-group-block');
        blocks.forEach(b => {{
          const visibleInBlock = Array.from(b.querySelectorAll('.roster-row')).some(r => r.style.display !== 'none');
          b.style.display = visibleInBlock ? '' : 'none';
        }});
      }});

      document.title = getRosterBaseFilename();
      document.getElementById('r-visible-count').textContent = `Showing ${{shownRows}} of {total_entries}`;
    }}

    const BASE_SLUG = "{base_slug}";
    function cleanToken(val) {{
      return (val || '').toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    }}
    function getRosterBaseFilename() {{
      const view = (document.getElementById('r-view') || {{}}).value || 'alpha';
      const sizeVal = (document.getElementById('r-size') || {{}}).value || '';
      const mat = (document.getElementById('r-mat') || {{}}).value || '';
      const div = (document.getElementById('r-div') || {{}}).value || '';
      const age = (document.getElementById('r-age') || {{}}).value || '';
      const skill = (document.getElementById('r-skill') || {{}}).value || '';
      const team = (document.getElementById('r-team') || {{}}).value || '';
      const warnOnly = (document.getElementById('r-warn-only') || {{}}).checked;

      const viewMap = {{
        'alpha': 'roster_a_z',
        'by-age-team': 'roster_checkin_by_age_club',
        'by-gid': 'roster_by_bracket_id',
        'by-mat': 'roster_by_mat',
        'by-team': 'roster_by_club',
        'by-bracket': 'roster_by_division_age'
      }};
      const parts = [BASE_SLUG, viewMap[view] || 'roster'];
      if (mat) parts.push(mat === 'unassigned' ? 'unassigned_mat' : `mat_${{cleanToken(mat)}}`);
      if (div) parts.push(cleanToken(div));
      if (age) parts.push(cleanToken(age));
      if (skill) parts.push(cleanToken(skill));
      if (team) parts.push(cleanToken(team));
      if (sizeVal) parts.push(sizeVal.startsWith('le') ? `${{cleanToken(sizeVal)}}_man` : `size_${{cleanToken(sizeVal)}}`);
      if (warnOnly) parts.push('warnings_only');
      return parts.filter(Boolean).join('_');
    }}
    function saveRosterPdf() {{
      document.title = getRosterBaseFilename();
      window.print();
    }}
    function resetRosterFilters() {{
      const sortEl = document.getElementById('r-sort');
      if (sortEl) sortEl.value = 'gid';
      ['r-size', 'r-mat', 'r-div', 'r-age', 'r-skill', 'r-team'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) el.value = '';
      }});
      const searchEl = document.getElementById('r-search');
      if (searchEl) searchEl.value = '';
      const warnEl = document.getElementById('r-warn-only');
      if (warnEl) warnEl.checked = false;
      applyRosterFilters();
    }}
    function saveRosterPrintout() {{
      ['r-view', 'r-sort', 'r-size', 'r-mat', 'r-div', 'r-age', 'r-skill', 'r-team'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) Array.from(el.options).forEach(o => o.toggleAttribute('selected', o.value === el.value));
      }});
      const searchEl = document.getElementById('r-search');
      if (searchEl) searchEl.setAttribute('value', searchEl.value || '');
      ['r-warn-only', 'r-pagebreak'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) el.toggleAttribute('checked', el.checked);
      }});
      const baseName = getRosterBaseFilename();
      document.title = baseName;
      const filename = baseName + '.html';

      const htmlContent = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
      const blob = new Blob([htmlContent], {{ type: 'text/html;charset=utf-8' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }}
    applyRosterFilters();
  </script>
</body>
</html>
"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


