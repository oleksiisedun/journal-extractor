from datetime import date

import pytest

from docx_parsing import extract_date_from_filename


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("journals/ЖБД_02_04_2026.docx", date(2026, 4, 2)),
        ("journals/ЖБД 10.07.2026.docx", date(2026, 7, 10)),
        ("journals/ЖБД_12-04-2026.docx", date(2026, 4, 12)),
    ],
)
def test_extracts_date_across_real_separator_variants(filename, expected):
    assert extract_date_from_filename(filename) == expected


def test_raises_when_filename_has_no_date():
    with pytest.raises(ValueError):
        extract_date_from_filename("journals/no-date-here.docx")


def test_raises_on_invalid_calendar_date_in_filename():
    with pytest.raises(ValueError):
        extract_date_from_filename("journals/ЖБД_31_02_2026.docx")
