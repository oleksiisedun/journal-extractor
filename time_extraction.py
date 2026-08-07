"""Time-of-day extraction (no LLM).

Two formats seen in real files, apparently never mixed within one day:
(a) "easy" / inline — a content paragraph itself starts with the time
    (e.g. '00.00 на виконання БОЙОВОГО РОЗПОРЯДЖЕННЯ ...'), and the time
    column is empty. This is exact/verbatim-derived — no guessing needed.
(b) "hard" / left-column — the narrow left column carries the times, NOT
    paragraph-aligned with the content column at all — verified
    empirically: gaps between consecutive left-column time labels don't
    track the content column's structure proportionally. A naive
    proportional mapping lands correctly on real section/list headers
    some of the time, but for the rest it lands INSIDE a single,
    homogeneous list of people governed by one order — which would
    silently mis-assign a time to real people. Handled with a
    snap-to-nearest-boundary heuristic below; only used when (a) finds
    nothing in a row. Assumes column 0 = time, column 1 = content.
"""

import re

from patterns import ORDER_REF_PATTERN

ROMAN_HEADER_PATTERN = re.compile(r"^[IVXІ]+\.")

INLINE_TIME_PATTERN = re.compile(r"^(\d{2}\.\d{2}(?:-\d{2}\.\d{2})?)\b")


def extract_inline_time(text):
    """Returns the time token at the very start of a content paragraph
    (e.g. '00.00' from '00.00 на виконання ...', or '05.00-06.40' from a
    ranged form), or None if the paragraph doesn't start with one. This is
    the "easy case": exact, verbatim-derived, no heuristic guessing."""
    match = INLINE_TIME_PATTERN.match(text.strip())
    return match.group(1) if match else None


def is_boundary_paragraph(text):
    """A content paragraph is a plausible time-boundary point if it's a
    Roman-numeral section header, a list/section-intro line ending in ':'
    (e.g. 'на ПВ «БРАВО»:'), or an order-reference sentence (matches
    ORDER_REF_PATTERN). Ordinary list entries (a single person's line)
    never qualify — that's what stops a time label from being snapped into
    the middle of a person list."""
    stripped = text.strip()
    return bool(
        ROMAN_HEADER_PATTERN.match(stripped)
        or stripped.endswith(":")
        or ORDER_REF_PATTERN.search(stripped)
    )


def _assign_time_boundaries_inline(content_paragraphs):
    """The "easy case": content paragraphs that themselves start with a
    time token. Exact and verbatim-derived, so always "confident"."""
    return [
        (global_idx, extract_inline_time(text), "confident")
        for global_idx, raw_idx, text in sorted(content_paragraphs, key=lambda t: t[0])
        if extract_inline_time(text)
    ]


def _assign_time_boundaries_left_column(row, slack):
    """The "hard case": snap-to-nearest-boundary heuristic over the left
    time column. See the module-level comment above for why this can't be
    an exact lookup. For each time label, a proportional cut point is
    computed from its raw position in the (blank-padded) time column, then
    snapped FORWARD to the nearest boundary-classified content paragraph.
    A label is "uncertain" if that snap traveled more than `slack` raw
    paragraphs from its predicted cut point, or if it collided with the
    same boundary as the previous label (in which case only the later,
    more specific time is kept — we can't tell which of the two genuinely
    governs that point)."""
    time_labels = row["time_labels"]
    left_raw_count = row["time_raw_count"]
    content_paragraphs = row["content_paragraphs"]
    right_raw_count = row["content_raw_count"]
    if not time_labels or left_raw_count <= 1 or right_raw_count <= 1:
        return []

    boundary_candidates = sorted(
        (raw_idx, global_idx)
        for global_idx, raw_idx, text in content_paragraphs
        if is_boundary_paragraph(text)
    )

    raw_assignments = []
    for label_raw_idx, time_value in time_labels:
        cut_point = round(
            label_raw_idx / (left_raw_count - 1) * (right_raw_count - 1)
        )
        snapped = next((b for b in boundary_candidates if b[0] >= cut_point), None)
        if snapped is None:
            continue  # no boundary left to snap to — this label can't be placed
        snapped_raw_idx, snapped_global_idx = snapped
        confident = abs(snapped_raw_idx - cut_point) <= slack
        raw_assignments.append([snapped_global_idx, time_value, confident])

    collapsed = []
    for global_idx, time_value, confident in raw_assignments:
        if collapsed and collapsed[-1][0] == global_idx:
            # two labels snapped to the same boundary — ambiguous which one
            # actually governs it; keep the later (more specific) time
            collapsed[-1] = [global_idx, time_value, False]
        else:
            collapsed.append([global_idx, time_value, confident])

    return [
        (global_idx, time_value, "confident" if confident else "uncertain")
        for global_idx, time_value, confident in collapsed
    ]


def assign_time_boundaries(row, slack=15):
    """Deterministically maps a table row's time information onto its
    content-column paragraphs. Returns an ascending list of
    (global_content_index, time_value, confidence) tuples, where
    confidence is "confident" or "uncertain" — never silently asserts a
    time it isn't reasonably sure about (same posture as the surname/
    order-number guardrails in assemble_fragment()).

    Tries the inline ("easy case") format first — see
    _assign_time_boundaries_inline() — and only falls back to the
    left-column heuristic (_assign_time_boundaries_left_column()) if no
    inline time tokens were found in this row's content. The two formats
    are assumed mutually exclusive within a single row/day, matching every
    real file seen so far; re-check this assumption if a file ever mixes
    them.
    """
    inline = _assign_time_boundaries_inline(row["content_paragraphs"])
    if inline:
        return inline
    return _assign_time_boundaries_left_column(row, slack)


def time_for_paragraph(boundaries, target_global_idx):
    """Looks up the (time_value, confidence) governing a given global
    content paragraph index: the boundary assignment with the largest
    global_content_index <= target_global_idx. Returns None if the target
    occurs before any boundary was assigned (time genuinely unknown)."""
    result = None
    for global_idx, time_value, confidence in boundaries:
        if global_idx <= target_global_idx:
            result = (time_value, confidence)
        else:
            break
    return result
