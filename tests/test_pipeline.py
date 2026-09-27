from datetime import date

from pipeline import resolve_day_fragment

_DAY = date(2026, 7, 1)


def test_surname_not_present_is_not_found():
    paragraphs = [(0, "ПЕТРЕНКО Іван Іванович заступив на пост.")]
    outcome = resolve_day_fragment(
        paragraphs, _DAY, [], "солдат ІВАНЕНКО Іван Іванович"
    )
    assert outcome["status"] == "not_found"
    assert outcome["pointer"] is None


def test_surname_present_but_full_name_is_not_verbatim():
    # a namesake with the same surname but a different first name/
    # patronymic must fail closed, not resolve from surname-only context.
    paragraphs = [(0, "ІВАНЕНКО Петро Григорович заступив на пост.")]
    outcome = resolve_day_fragment(
        paragraphs, _DAY, [], "солдат ІВАНЕНКО Іван Іванович"
    )
    assert outcome["status"] == "not_found"


def test_full_name_verbatim_is_found():
    paragraphs = [
        (0, "на виконання БОЙОВОГО НАКАЗУ №БН1/Б3/ДСК"),
        (1, "ІВАНЕНКО Іван Іванович заступив на пост."),
    ]
    outcome = resolve_day_fragment(
        paragraphs, _DAY, [], "солдат ІВАНЕНКО Іван Іванович"
    )
    assert outcome["status"] == "found"
    assert outcome["result"] is not None
    assert "ІВАНЕНКО" in outcome["result"]["text"]
    assert outcome["result"]["date"] == _DAY
