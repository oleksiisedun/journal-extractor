"""Parses a "РОБОЧІ ГРУПИ" (working groups) report -- a single .docx
covering a whole month as flowing body paragraphs (no table, unlike the
daily journals) -- into per-item blocks (no LLM anywhere -- see CLAUDE.md's
"Core architectural principle"). One block = one item paragraph; a
date-header paragraph only supplies the fallback date for items that
don't carry their own inline date. Consecutive blocks whose text matches
once punctuation marks are ignored (only date/time -- and sometimes
incidental punctuation -- differing, a recurring reporting item) are
grouped by group_consecutive_identical_blocks() into one extract .docx
instead of one file per block, though each block's own text still renders
byte-verbatim; see generate_extract.py's generate_working_groups().
"""

import re
from datetime import date, timedelta

from docx import Document

DATE_HEADER_PATTERN = re.compile(r"^\d{2}\.\d{2}$")

# Tolerant of the real formatting variance seen in the source document:
# '.' or ':' between hour/minute, an optional seconds-like third group
# (e.g. '09:00.00-18.00'), and an optional leading DD.MM.YYYY that
# overrides the enclosing date-header section for that one item. Named
# groups (rather than positional) so a reader doesn't have to count
# parentheses to know which is which.
ITEM_START_PATTERN = re.compile(
    r"^\s*(?:(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})\s+)?"
    r"(?P<time>\d{2}[.:]\d{2}(?:[.:]\d{2})?\s*[-–]\s*\d{2}[.:]\d{2}(?:[.:]\d{2})?)"
)

# A new, working-groups-specific pattern -- deliberately NOT
# patterns.ORDER_REF_PATTERN, which requires no whitespace between '№' and
# the rest of the token and is tuned for the daily-journal pipeline. This
# document commonly writes 'БР' with a space before the digits, and
# sometimes omits '№' entirely ('БР 1901/ЮВ/ДСК'). Still requires an
# eventual '/' so plain list markers like '№1', '№2' never match (same
# anti-false-positive idea as the existing pattern).
WORKING_GROUP_ORDER_REF_PATTERN = re.compile(r"(?:№\s*(?:БР\s*)?|БР\s*)(\d{3,5})\s*/")


def _extract_order_ids(text):
    """Distinct order-number tokens referenced in `text`, in
    first-appearance order, always displayed with a 'БР' prefix -- the
    same order number is written with and without 'БР' in different
    places in the real document (e.g. '№1927/...' vs '№БР 1927/...' for
    the very same order), so this is purely a display convention, not a
    literal transcription of that one occurrence's source formatting;
    dedup keys on the bare digits so both spellings collapse to one token
    ('БР1927') instead of appearing as two different order ids for what is
    the same order.
    @param {str} text
    @returns {list[str]}
    """
    seen = {}
    for match in WORKING_GROUP_ORDER_REF_PATTERN.finditer(text):
        digits = match.group(1)
        if digits not in seen:
            seen[digits] = "БР" + digits
    return list(seen.values())


def parse_working_group_blocks(docx_path, year_override=None):
    """Extracts every reporting item from `docx_path` as a block dict
    ({"date", "text", "time", "order_ids"}), in document order. `text` is
    the paragraph's content AFTER its leading date-override/time-range
    token (everything ITEM_START_PATTERN matched) is removed -- that token
    is structural item metadata, not narrative content, and is returned
    separately as `time` (kept fully verbatim, e.g. "13.40-14.50") so
    equal-text comparison (see group_consecutive_identical_blocks()) isn't
    defeated by every block carrying a different literal time prefix, and
    so it can be rendered into its own {дата}-column line. Everything
    after the matched prefix stays byte-verbatim, per CLAUDE.md's verbatim
    rule -- only the separating whitespace is trimmed.

    A block's date is its own inline DD.MM.YYYY when present (real year
    included, never affected by `year_override`), else the nearest
    preceding date-header's day/month paired with `year_override` if given,
    else the current year (the header never carries a year in the source,
    so without an explicit override the fallback is only correct when the
    script happens to run in the same year the report covers -- pass
    `year_override` when that's not the case, e.g. processing a December
    report in January). A paragraph that's neither blank, a date header,
    nor a recognized item is skipped with a loud warning rather than
    aborting the whole file.
    @param {str} docx_path
    @param {int|None} year_override
    @returns {list[dict]}
    """
    document = Document(docx_path)
    blocks = []
    current_section_date = None  # (day, month), no year -- from the source

    for paragraph in document.paragraphs:
        text = paragraph.text
        stripped = text.strip()
        if not stripped:
            continue

        if DATE_HEADER_PATTERN.match(stripped):
            day, month = stripped.split(".")
            current_section_date = (int(day), int(month))
            continue

        item_match = ITEM_START_PATTERN.match(text)
        if not item_match:
            print(f"  Unrecognized paragraph, skipped: {stripped[:100]!r}")
            continue

        if item_match.group("day"):
            inline_day, inline_month, inline_year = (
                int(item_match.group("day")), int(item_match.group("month")), int(item_match.group("year")),
            )
            block_date = date(inline_year, inline_month, inline_day)
        elif current_section_date is not None:
            day, month = current_section_date
            year = year_override if year_override is not None else date.today().year
            block_date = date(year, month, day)
        else:
            print(f"  Paragraph outside any date section, skipped: {stripped[:100]!r}")
            continue

        item_text = text[item_match.end():].lstrip(" \t")
        blocks.append({
            "date": block_date,
            "text": item_text,
            "time": item_match.group("time"),
            "order_ids": _extract_order_ids(text),
        })

    return blocks


def group_consecutive_identical_blocks(blocks):
    """Groups `blocks` (must already be sorted chronologically by "date",
    and already carrying each block's final, fully-processed "text") into
    one group per distinct normalized text value (`_normalize_for_grouping()`
    ignores punctuation, e.g. a trailing '.' vs ';', or a ',' vs ';'
    mid-sentence) -- the recurring-item case where only the date/time
    changes day to day. Every occurrence of a given normalized text lands
    in the same group regardless of calendar gaps between occurrences (e.g.
    someone else covers the same duty for a stretch of days, then the
    original person resumes) -- unlike merge.merge_consecutive_entries(),
    this never folds a run into a single "з ... по ..." line that would
    imply continuous presence; each block stays its own dated entry within
    the group (see generate_extract.py's generate_working_groups()), so
    grouping across a gap doesn't misrepresent anything -- the gap dates
    simply have no entry. Each block's own "text" is still rendered
    byte-verbatim -- only the grouping decision ignores punctuation, never
    the output. `build_working_group_filename()` uses `compute_date_ranges()`
    to reflect the group's real (possibly disjoint) date spans in its
    output filename.

    Grouping is done PER DISTINCT NORMALIZED TEXT VALUE, not by walking the
    full list and comparing only immediately-adjacent entries: a real
    working-groups report lists several unrelated items per date section,
    so a recurring item's next-day occurrence is essentially never adjacent
    to today's in the flat chronological list -- other same-day items for
    other people/orders sit between them.

    Kept as a separate function from merge.merge_consecutive_entries()
    rather than generalizing that one since the two produce genuinely
    different output shapes (fold-into-a-range vs. one-group-per-distinct-
    text-with-every-occurrence-kept-separate).

    Returned groups are sorted by their earliest date, for a predictable,
    chronological order of output files.
    @param {list[dict]} blocks
    @returns {list[list[dict]]}
    """
    if not blocks:
        return []

    by_text = {}
    for block in blocks:
        by_text.setdefault(_normalize_for_grouping(block["text"]), []).append(block)

    groups = list(by_text.values())
    groups.sort(key=lambda group: group[0]["date"])
    return groups


def compute_date_ranges(blocks):
    """Partitions `blocks`' distinct dates into runs of chronologically-
    consecutive calendar days, e.g. dates [02.07, 03.07, 05.07] (a gap at
    04.07) become [(02.07, 03.07), (05.07, 05.07)]. Used to build a
    grouped file's filename (`build_working_group_filename()`) so it
    reflects the group's real, possibly-disjoint date spans rather than a
    single "з ... по ..." that would misstate a continuous presence across
    a gap group_consecutive_identical_blocks() no longer breaks on.
    Duplicate dates (two same-text blocks on one day) collapse to one
    calendar day and never split a range on their own, since a zero-day
    gap isn't a real gap.
    @param {list[dict]} blocks
    @returns {list[tuple[datetime.date, datetime.date]]}
    """
    dates = sorted({block["date"] for block in blocks})
    ranges = []
    start = prev = dates[0]
    for current in dates[1:]:
        if current == prev + timedelta(days=1):
            prev = current
        else:
            ranges.append((start, prev))
            start = prev = current
    ranges.append((start, prev))
    return ranges


# Used only to build the grouping key in group_consecutive_identical_blocks()
# -- never applied to a block's actual rendered "text", which always stays
# byte-verbatim per CLAUDE.md's verbatim rule. Covers the punctuation marks
# actually seen varying between otherwise-identical recurring items (period/
# comma/semicolon/colon, both dash styles, both quote styles).
_GROUPING_PUNCTUATION_CHARS = ".,;:!?()\"'«»-–—"
_GROUPING_PUNCTUATION_TABLE = str.maketrans("", "", _GROUPING_PUNCTUATION_CHARS)


def _normalize_for_grouping(text):
    """Comparison key for group_consecutive_identical_blocks(): strips
    punctuation marks and collapses the whitespace that stripping them can
    leave behind, so two blocks whose text differs only in punctuation
    (e.g. one day's item ends in ';', another's in '.', or a comma where
    another has a semicolon) are still recognized as the same recurring
    item. Comparison-only -- each block keeps its own untouched text for
    rendering.
    @param {str} text
    @returns {str}
    """
    stripped = text.translate(_GROUPING_PUNCTUATION_TABLE)
    return re.sub(r"\s+", " ", stripped).strip()


def union_order_ids(order_id_lists):
    """Unions several blocks' order_ids lists into one, deduped, in
    first-appearance order across the lists -- used when several blocks
    are grouped into one output file, so no order id is silently dropped
    from the filename even in the unlikely case a group's members don't
    all cite it identically.
    @param {list[list[str]]} order_id_lists
    @returns {list[str]}
    """
    seen = []
    for order_ids in order_id_lists:
        for order_id in order_ids:
            if order_id not in seen:
                seen.append(order_id)
    return seen


def build_working_group_filename(unit_prefix, date_ranges, order_ids):
    """Output filename for one group's blocks, e.g. '3 боп витяг жбд за
    21.07.2026 БР2418.docx' for a single day, '3 боп витяг жбд з
    06.06.2026 по 08.06.2026 БР1596.docx' for one contiguous run (same "з
    ... по ..." phrasing render.py's _format_date_lines() already uses for
    a merged multi-day {дата} entry), or, when the group's occurrences
    aren't all contiguous (e.g. someone else covers the same duty for a
    stretch of days in between), a space-separated list of each
    contiguous span in compact 'DD.MM.YYYY-DD.MM.YYYY' form (a single day
    within such a list renders as just 'DD.MM.YYYY', no repeated dash), so
    the filename never implies a continuous presence the source doesn't
    show, e.g. '3 боп витяг жбд 02.07.2026-05.07.2026 10.07.2026-11.07.2026
    20.07.2026-31.07.2026 БР1927.docx'. Every distinct order id across the
    group is included, space-separated, in first-appearance order -- no
    cap.
    @param {str} unit_prefix
    @param {list[tuple[datetime.date, datetime.date]]} date_ranges -- from
        compute_date_ranges(), sorted chronologically, at least one entry
    @param {list[str]} order_ids
    @returns {str}
    """
    if len(date_ranges) == 1:
        date_from, date_to = date_ranges[0]
        if date_from == date_to:
            date_part = f"за {date_from.strftime('%d.%m.%Y')}"
        else:
            date_part = f"з {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}"
    else:
        date_part = " ".join(
            date_from.strftime("%d.%m.%Y")
            if date_from == date_to
            else f"{date_from.strftime('%d.%m.%Y')}-{date_to.strftime('%d.%m.%Y')}"
            for date_from, date_to in date_ranges
        )
    order_part = " ".join(order_ids)
    return f"{unit_prefix} витяг жбд {date_part} {order_part}.docx"
