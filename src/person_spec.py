"""Parses a person CLI spec into the name portion plus an optional trailing
date/date-range filter (see CLAUDE.md's "Not yet built" -> requested date
range). Its own module, not bolted onto generate_extract.py, for the same
reason render.py got its own file instead of growing assembly.py.
"""

import re
from datetime import date

# Trailing "DD.MM.YYYY" or "DD.MM.YYYY-DD.MM.YYYY", separated from the name
# by whitespace, anchored to the end of the string. Dot is the only
# accepted date-internal separator here (unlike FILENAME_DATE_PATTERN in
# docx_parsing.py, which also tolerates '_'/'-') because '-' is reserved as
# the range separator -- allowing it inside the date too would make
# "02-04-2026-23-04-2026" ambiguous.
PERSON_DATE_PATTERN = re.compile(
    r"\s+(\d{2}\.\d{2}\.\d{4})(?:-(\d{2}\.\d{2}\.\d{4}))?$"
)


def _parse_ddmmyyyy(token):
    """Parses a single 'DD.MM.YYYY' token (day-first, matching the
    project's existing filename-date convention)."""
    day, month, year = (int(part) for part in token.split("."))
    try:
        return date(year, month, day)
    except ValueError as e:
        raise ValueError(f"Invalid date {token!r}: {e}") from e


def parse_person_spec(raw):
    """Splits a person CLI spec into (full_name, date_from, date_to).
    `full_name` is the 'rank SURNAME Firstname Patronymic' portion with any
    trailing date/range stripped; `date_from`/`date_to` are inclusive
    `date` bounds, or (None, None) if no date/range was appended (search
    every day, current/default behavior). A single date is treated as a
    one-day range (date_from == date_to).
    @param {str} raw
    @returns {tuple[str, date|None, date|None]}
    """
    match = PERSON_DATE_PATTERN.search(raw)
    if not match:
        return raw.strip(), None, None

    full_name = raw[:match.start()].strip()
    date_from = _parse_ddmmyyyy(match.group(1))
    date_to = _parse_ddmmyyyy(match.group(2)) if match.group(2) else date_from

    if date_from > date_to:
        raise ValueError(
            f"Start date {date_from.isoformat()} is after end date "
            f"{date_to.isoformat()} in: {raw!r}"
        )

    return full_name, date_from, date_to
