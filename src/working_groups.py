"""Parses a "РОБОЧІ ГРУПИ" (working groups) report -- a single .docx
covering a whole month as flowing body paragraphs (no table, unlike the
daily journals) -- into per-item blocks (no LLM anywhere -- see CLAUDE.md's
"Core architectural principle"). One block = one item paragraph; a
date-header paragraph only supplies the fallback date for items that
don't carry their own inline date. Consecutive blocks whose text is
byte-identical (only date/time differing -- a recurring reporting item)
are grouped by group_consecutive_identical_blocks() into one extract
.docx instead of one file per block; see generate_extract.py's
generate_working_groups().
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
    first-appearance order. Dedup keys on the bare digits -- the same
    order number is written with and without the 'БР' prefix in different
    places in the real document, so keying on the raw string would treat
    one real order as two. Whichever formatting (БР-prefixed or not) is
    seen first for a given number wins the displayed token.
    @param {str} text
    @returns {list[str]}
    """
    seen = {}
    for match in WORKING_GROUP_ORDER_REF_PATTERN.finditer(text):
        digits = match.group(1)
        if digits not in seen:
            seen[digits] = ("БР" + digits) if "БР" in match.group(0) else digits
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
    """Partitions `blocks` (must already be sorted chronologically by
    "date", and already carrying each block's final, fully-processed
    "text") into runs of chronologically-consecutive blocks that share
    byte-identical "text" -- the recurring-item case where only the
    date/time changes day to day. Unlike merge.merge_consecutive_entries(),
    every block stays its own entry within a run (no fold into a single "з
    ... по ..." line) -- this mode's real samples show each day's own
    date+time stacked, never collapsed.

    Grouping is done PER DISTINCT TEXT VALUE, not by walking the full list
    and comparing only immediately-adjacent entries: a real working-groups
    report lists several unrelated items per date section, so a recurring
    item's next-day occurrence is essentially never adjacent to today's in
    the flat chronological list -- other same-day items for other people/
    orders sit between them. Every occurrence of a given exact text is
    collected (preserving the chronological order `blocks` already has),
    then that same-text subsequence alone is split into runs wherever two
    consecutive occurrences aren't exactly one calendar day apart -- same
    gap-breaks-a-run rule as merge.merge_consecutive_entries(), just
    applied within one text's own occurrences instead of the raw list.
    Two identical-text blocks on the very same date (two separate items
    that day happen to read the same) never merge with each other either,
    since a zero-day gap isn't a one-day gap.

    Kept as a separate function from merge.merge_consecutive_entries()
    rather than generalizing that one since the two produce genuinely
    different output shapes (fold-into-a-range vs. partition-into-still-
    separate-entries).

    Returned groups are sorted by their earliest date, for a predictable,
    chronological order of output files.
    @param {list[dict]} blocks
    @returns {list[list[dict]]}
    """
    if not blocks:
        return []

    by_text = {}
    for block in blocks:
        by_text.setdefault(block["text"], []).append(block)

    groups = []
    for same_text_blocks in by_text.values():
        current = [same_text_blocks[0]]
        for block in same_text_blocks[1:]:
            if block["date"] == current[-1]["date"] + timedelta(days=1):
                current.append(block)
            else:
                groups.append(current)
                current = [block]
        groups.append(current)

    groups.sort(key=lambda group: group[0]["date"])
    return groups


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


def build_working_group_filename(unit_prefix, date_from, date_to, order_ids):
    """Output filename for one block or merged run of blocks, e.g. '3 боп
    витяг жбд за 21.07.2026 БР2418.docx' for a single day, or '3 боп витяг
    жбд з 06.06.2026 по 08.06.2026 БР1596.docx' for a merged run (`date_to`
    > `date_from`) -- same "з ... по ..." phrasing render.py's
    _format_date_lines() already uses for a merged multi-day {дата} entry.
    Every distinct order id across the run is included, space-separated,
    in first-appearance order -- no cap.
    @param {str} unit_prefix
    @param {datetime.date} date_from
    @param {datetime.date} date_to
    @param {list[str]} order_ids
    @returns {str}
    """
    if date_from == date_to:
        date_part = f"за {date_from.strftime('%d.%m.%Y')}"
    else:
        date_part = f"з {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}"
    order_part = " ".join(order_ids)
    return f"{unit_prefix} витяг жбд {date_part} {order_part}.docx"
