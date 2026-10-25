"""Round-robin and elimination bracket bout generation."""

from __future__ import annotations

from bracketman.models import Bout, Wrestler


def resolve_bracket_format(size: int, configured_format: str = "auto") -> str:
    """Resolve the effective bracket format for a group of a given size."""
    if size <= 1:
        return "uncontested"
    if configured_format != "auto":
        return configured_format
    if size <= 5:
        return "round_robin"
    return "bracket_8"


def generate_round_robin_bouts(wrestlers: list[Wrestler]) -> list[Bout]:
    """Generate balanced round-robin bouts using the circle method.

    For 2 wrestlers: 2 bouts (best 2-of-3 format) or 1 bout.
    For 3-5 wrestlers: standard round-robin rounds.
    """
    n = len(wrestlers)
    if n <= 1:
        return []

    if n == 2:
        # Standard youth 2-man bracket: Best 2 of 3
        return [
            Bout(bout_number=1, round_number=1, wrestler_a=wrestlers[0], wrestler_b=wrestlers[1]),
            Bout(bout_number=2, round_number=2, wrestler_a=wrestlers[1], wrestler_b=wrestlers[0]),
        ]

    # Circle method; add None (BYE) if odd number of wrestlers
    pool: list[Wrestler | None] = list(wrestlers)
    if len(pool) % 2 == 1:
        pool.append(None)

    m = len(pool)
    num_rounds = m - 1
    half = m // 2

    bouts: list[Bout] = []
    bout_num = 1
    current = list(pool)

    for r in range(1, num_rounds + 1):
        for i in range(half):
            wa = current[i]
            wb = current[m - 1 - i]
            if wa is not None and wb is not None:
                bouts.append(
                    Bout(
                        bout_number=bout_num,
                        round_number=r,
                        wrestler_a=wa,
                        wrestler_b=wb,
                    )
                )
                bout_num += 1
        # Rotate all except first element
        current = [current[0], current[-1]] + current[1:-1]

    return bouts


def order_wrestlers_for_bracket_tree(wrestlers: list[Wrestler]) -> list[Wrestler | None]:
    """Place wrestlers into an 8-slot bracket array separating teammates across halves."""
    slots: list[Wrestler | None] = [None] * 8
    n = len(wrestlers)
    if n == 0:
        return slots

    # Separate top half (slots 0..3) and bottom half (slots 4..7)
    top_indices = [0, 2, 1, 3]
    bottom_indices = [4, 6, 5, 7]
    top_teams: set[str] = set()
    bottom_teams: set[str] = set()

    top_pos = 0
    bot_pos = 0
    for idx, w in enumerate(wrestlers[:8]):
        tkey = w.team_key
        # Prefer the half that does not already contain a teammate, balancing counts
        if top_pos <= bot_pos and (tkey not in top_teams or tkey in bottom_teams or bot_pos >= 4):
            slots[top_indices[top_pos]] = w
            top_teams.add(tkey)
            top_pos += 1
        elif bot_pos < 4:
            slots[bottom_indices[bot_pos]] = w
            bottom_teams.add(tkey)
            bot_pos += 1
        else:
            slots[top_indices[top_pos]] = w
            top_teams.add(tkey)
            top_pos += 1

    return slots


def generate_bracket_8_bouts(wrestlers: list[Wrestler]) -> list[Bout]:
    """Generate first-round quarterfinal matchups for a 6-8 wrestler bracket."""
    slots = order_wrestlers_for_bracket_tree(wrestlers)
    bouts: list[Bout] = []
    bout_num = 1
    for i in range(0, 8, 2):
        wa = slots[i]
        wb = slots[i + 1]
        if wa is None and wb is not None:
            wa, wb = wb, None
        if wa is not None:
            bouts.append(
                Bout(
                    bout_number=bout_num,
                    round_number=1,
                    wrestler_a=wa,
                    wrestler_b=wb,
                )
            )
            bout_num += 1
    return bouts


def generate_bouts_for_group(wrestlers: list[Wrestler], bracket_format: str) -> list[Bout]:
    """Generate bouts for a group based on its resolved bracket format."""
    if len(wrestlers) <= 1:
        return []
    if bracket_format == "bracket_8":
        return generate_bracket_8_bouts(wrestlers)
    return generate_round_robin_bouts(wrestlers)
