"""Ukrainian date/date-range formatting shared between render.py and
working_groups.py -- kept in one place so the "DD.MM.YYYY" format and the
"з ... по ..." range phrasing (which both output paths must render
identically -- see CLAUDE.md) can't drift apart between the two.
"""

from datetime import date

DATE_FORMAT = "%d.%m.%Y"


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def format_date_span(date_from: date, date_to: date) -> str:
    """'DD.MM.YYYY' for a single day (date_from == date_to), or
    'з DD.MM.YYYY по DD.MM.YYYY' for a range -- the phrasing used across
    output to mark a merged/recurring date span."""
    if date_from == date_to:
        return format_date(date_from)
    return f"з {format_date(date_from)} по {format_date(date_to)}"
