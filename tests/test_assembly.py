import pytest

from assembly import (
    assemble_fragment,
    extract_order_refs,
    strip_coordinates,
    strip_location_labels,
)
from domain_types import Paragraphs, Pointer


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # a single coordinate is stripped cleanly
        ("Позиція 37U CR 1234 5678 зайнята.", "Позиція зайнята."),
        # bug-log item 3: the empty parenthetical left behind, plus the
        # dangling "за координатами" phrase, must both disappear
        (
            "Група №2 за координатами (37U CR 15093 59641) вибула.",
            "Група №2 вибула.",
        ),
        # bug-log item 5: a colon right after "за координатами" and the
        # comma left dangling by the removed clause must not collide into
        # stray punctuation like ",:."
        (
            "... Харківської області, за координатами: (37U CR 1234 5678; "
            "37U CR 1234 5678).",
            "... Харківської області.",
        ),
        # a semicolon-separated list of coordinates inside one parenthetical
        (
            "район зосередження (37U CR 1234 5678; 37U CR 1234 5678)",
            "район зосередження",
        ),
        # no coordinates present -- text passes through unchanged
        ("Звичайний текст без координат.", "Звичайний текст без координат."),
    ],
)
def test_strip_coordinates(text, expected):
    assert strip_coordinates(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("вибув у район зосередження.", "вибув."),
        ("перебуває в районі зосередження підрозділу.", "перебуває підрозділу."),
        ("повернення до зосередженню.", "повернення до зосередженню."),
        ("звичайний текст.", "звичайний текст."),
    ],
)
def test_strip_location_labels(text, expected):
    assert strip_location_labels(text) == expected


def test_extract_order_refs_normalizes_whitespace_after_symbol():
    text = "на виконання №БР42/Б3/7Р/ДСК та №БР 42/Б3/7Р/ДСК"
    assert extract_order_refs(text) == {"№БР42/Б3/7Р/ДСК"}


def test_extract_order_refs_ignores_bare_list_numbering():
    # plain "№2" group numbering must never be mistaken for an order
    # reference -- see bug-log item 2.
    assert extract_order_refs("Група №2 за координатами (...)") == set()


def test_extract_order_refs_finds_multiple_distinct_orders():
    text = "БОЙОВОГО НАКАЗУ №БН5/Б3/ДСК та БОЙОВОГО РОЗПОРЯДЖЕННЯ №БР63/Б3/9Р/ДСК"
    assert extract_order_refs(text) == {"№БН5/Б3/ДСК", "№БР63/Б3/9Р/ДСК"}


def _paragraphs(*texts: str) -> Paragraphs:
    return list(enumerate(texts))


def test_assemble_fragment_rejects_context_from_two_different_orders():
    # mirrors CLAUDE.md's real found case: context pulled from two
    # unrelated orders governing two different people must never be
    # merged into one person's fragment.
    paragraphs = _paragraphs(
        "на виконання БОЙОВОГО НАКАЗУ №БН18/Б3/ДСК",
        "на виконання БОЙОВОГО РОЗПОРЯДЖЕННЯ №БР19/Б3/ДСК",
        "ІВАНЕНКО Іван Іванович заступив на пост.",
    )
    pointer: Pointer = {
        "found": True,
        "context_paragraph_indices": [0, 1],
        "target_paragraph_index": 2,
    }
    with pytest.raises(ValueError, match="MULTIPLE"):
        assemble_fragment(paragraphs, pointer)


def test_assemble_fragment_allows_one_paragraph_citing_two_orders_together():
    # bug-log item 6: a single context paragraph legitimately citing two
    # orders as one joint legal basis must NOT trip the guardrail above --
    # only two DIFFERENT context paragraphs each with their own order do.
    paragraphs = _paragraphs(
        "на виконання БОЙОВОГО НАКАЗУ №БН5/Б3/ДСК та "
        "БОЙОВОГО РОЗПОРЯДЖЕННЯ №БР63/Б3/9Р/ДСК",
        "ІВАНЕНКО Іван Іванович заступив на пост.",
    )
    pointer: Pointer = {
        "found": True,
        "context_paragraph_indices": [0],
        "target_paragraph_index": 1,
    }
    result = assemble_fragment(paragraphs, pointer)
    assert result is not None
    assert "ІВАНЕНКО" in result["text"]


def test_assemble_fragment_fixes_trailing_semicolon():
    paragraphs = _paragraphs("ІВАНЕНКО Іван Іванович заступив на пост;")
    pointer: Pointer = {
        "found": True,
        "context_paragraph_indices": [],
        "target_paragraph_index": 0,
    }
    result = assemble_fragment(paragraphs, pointer)
    assert result is not None
    assert result["text"] == "ІВАНЕНКО Іван Іванович заступив на пост."


def test_assemble_fragment_rejects_when_surname_missing_from_result():
    paragraphs = _paragraphs("ПЕТРЕНКО Іван Іванович заступив на пост.")
    pointer: Pointer = {
        "found": True,
        "context_paragraph_indices": [],
        "target_paragraph_index": 0,
        "_surname_check": "ІВАНЕНКО",
    }
    with pytest.raises(ValueError, match="missing"):
        assemble_fragment(paragraphs, pointer)
