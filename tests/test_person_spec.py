from datetime import date

import pytest

from person_spec import parse_person_spec


def test_no_trailing_date_searches_every_day():
    name, date_from, date_to = parse_person_spec(
        "старший солдат БОНДАРЕНКО Олег Васильович"
    )
    assert name == "старший солдат БОНДАРЕНКО Олег Васильович"
    assert date_from is None
    assert date_to is None


def test_single_trailing_date_is_a_one_day_range():
    name, date_from, date_to = parse_person_spec(
        "старший солдат БОНДАРЕНКО Олег Васильович 02.04.2026"
    )
    assert name == "старший солдат БОНДАРЕНКО Олег Васильович"
    assert date_from == date_to == date(2026, 4, 2)


def test_trailing_date_range_is_parsed_inclusive():
    name, date_from, date_to = parse_person_spec(
        "старший солдат БОНДАРЕНКО Олег Васильович 02.04.2026-23.04.2026"
    )
    assert name == "старший солдат БОНДАРЕНКО Олег Васильович"
    assert date_from == date(2026, 4, 2)
    assert date_to == date(2026, 4, 23)


def test_start_after_end_raises():
    with pytest.raises(ValueError):
        parse_person_spec("солдат ШЕВЧЕНКО О.В. 23.04.2026-02.04.2026")


def test_invalid_calendar_date_raises():
    with pytest.raises(ValueError):
        parse_person_spec("солдат ШЕВЧЕНКО О.В. 31.02.2026")
