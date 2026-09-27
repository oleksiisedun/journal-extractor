from datetime import date

from domain_types import WorkingGroupBlock
from working_groups import (
    compute_date_ranges,
    group_consecutive_identical_blocks,
    union_order_ids,
)


def _block(
    day: int, month: int, text: str, order_ids: list[str] | None = None
) -> WorkingGroupBlock:
    return {
        "date": date(2026, month, day),
        "text": text,
        "time": "00.00-06.00",
        "order_ids": order_ids or [],
    }


def test_group_consecutive_identical_blocks_ignores_punctuation_differences():
    blocks = [
        _block(1, 7, "Виконання завдання."),
        _block(2, 7, "Виконання завдання;"),
    ]
    groups = group_consecutive_identical_blocks(blocks)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_group_consecutive_identical_blocks_keeps_a_gapped_recurrence_in_one_group():
    # bug-log case: БАЙЛИМ covers a duty 02.07-05.07, someone else covers
    # it 06.07-19.07, then БАЙЛИМ's byte-identical text resumes 20.07 --
    # this must still be ONE group (every occurrence of the same
    # normalized text), not split by the calendar gap.
    blocks = [
        _block(2, 7, "Виконання завдання за наказом №БР1927/(S-3) ВКП/ДСК."),
        _block(10, 7, "Інше завдання іншої людини."),
        _block(20, 7, "Виконання завдання за наказом №БР1927/(S-3) ВКП/ДСК."),
    ]
    groups = group_consecutive_identical_blocks(blocks)
    assert len(groups) == 2
    recurring_group = next(g for g in groups if len(g) == 2)
    assert {b["date"] for b in recurring_group} == {date(2026, 7, 2), date(2026, 7, 20)}


def test_compute_date_ranges_splits_on_a_calendar_gap():
    blocks = [_block(2, 7, "x"), _block(3, 7, "x"), _block(5, 7, "x")]
    assert compute_date_ranges(blocks) == [
        (date(2026, 7, 2), date(2026, 7, 3)),
        (date(2026, 7, 5), date(2026, 7, 5)),
    ]


def test_compute_date_ranges_collapses_duplicate_same_day_entries():
    blocks = [_block(2, 7, "x"), _block(2, 7, "x")]
    assert compute_date_ranges(blocks) == [(date(2026, 7, 2), date(2026, 7, 2))]


def test_union_order_ids_dedupes_in_first_appearance_order():
    result = union_order_ids([["БР1927"], ["БР42", "БР1927"], ["БР99"]])
    assert result == ["БР1927", "БР42", "БР99"]
