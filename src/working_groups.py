"""Parses a "РОБОЧІ ГРУПИ" (working groups) report -- a single .docx
covering a whole month as flowing body paragraphs (no table, unlike the
daily journals) -- into per-item blocks, each destined for its own extract
.docx (no LLM anywhere -- see CLAUDE.md's "Core architectural
principle"). One block = one item paragraph; a date-header paragraph only
supplies the fallback date for items that don't carry their own inline
date.
"""

import re
from datetime import date

from docx import Document

DATE_HEADER_PATTERN = re.compile(r"^\d{2}\.\d{2}$")

# Tolerant of the real formatting variance seen in the source document:
# '.' or ':' between hour/minute, an optional seconds-like third group
# (e.g. '09:00.00-18.00'), and an optional leading DD.MM.YYYY that
# overrides the enclosing date-header section for that one item.
ITEM_START_PATTERN = re.compile(
    r"^\s*(?:(\d{2})\.(\d{2})\.(\d{4})\s+)?"
    r"\d{2}[.:]\d{2}(?:[.:]\d{2})?\s*[-–]\s*\d{2}[.:]\d{2}(?:[.:]\d{2})?"
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


def parse_working_group_blocks(docx_path):
    """Extracts every reporting item from `docx_path` as a block dict
    ({"date", "text", "order_ids"}), in document order. `text` is kept
    fully verbatim (including its leading tab) -- no reformatting, per
    CLAUDE.md's verbatim rule. A block's date is its own inline
    DD.MM.YYYY when present (real year included), else the nearest
    preceding date-header's day/month paired with the current year (the
    header never carries a year in the source). A paragraph that's
    neither blank, a date header, nor a recognized item is skipped with a
    loud warning rather than aborting the whole file.
    @param {str} docx_path
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
            print(f"  Незрозумілий абзац, пропущено: {stripped[:100]!r}")
            continue

        if item_match.group(1):
            inline_day, inline_month, inline_year = (
                int(item_match.group(1)), int(item_match.group(2)), int(item_match.group(3)),
            )
            block_date = date(inline_year, inline_month, inline_day)
        elif current_section_date is not None:
            day, month = current_section_date
            block_date = date(date.today().year, month, day)
        else:
            print(f"  Абзац поза межами будь-якої дати, пропущено: {stripped[:100]!r}")
            continue

        blocks.append({
            "date": block_date,
            "text": text,
            "order_ids": _extract_order_ids(text),
        })

    return blocks


def build_working_group_filename(unit_prefix, block_date, order_ids):
    """Output filename for one block, e.g. '3 боп витяг жбд за
    21.07.2026 БР2418.docx'. Every distinct order id found in the block
    is included, space-separated, in first-appearance order -- no cap.
    @param {str} unit_prefix
    @param {datetime.date} block_date
    @param {list[str]} order_ids
    @returns {str}
    """
    date_part = block_date.strftime("%d.%m.%Y")
    order_part = " ".join(order_ids)
    return f"{unit_prefix} витяг жбд за {date_part} {order_part}.docx"
