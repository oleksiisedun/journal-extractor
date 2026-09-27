from datetime import date

from domain_types import Fragment
from merge import merge_consecutive_entries


def _fragment(day: int, text: str = "text", time: str = "00.00") -> Fragment:
    return {
        "text": text,
        "date": date(2026, 7, day),
        "time": time,
        "time_confidence": "confident",
    }


def test_empty_input_returns_empty():
    assert merge_consecutive_entries([]) == []


def test_single_entry_stays_single_day():
    result = merge_consecutive_entries([_fragment(1)])
    assert result == [
        {
            "text": "text",
            "date_from": date(2026, 7, 1),
            "date_to": date(2026, 7, 1),
            "time": "00.00",
            "time_confidence": "confident",
        }
    ]


def test_consecutive_identical_days_merge_into_one_range():
    entries = [_fragment(1), _fragment(2), _fragment(3)]
    result = merge_consecutive_entries(entries)
    assert len(result) == 1
    assert result[0]["date_from"] == date(2026, 7, 1)
    assert result[0]["date_to"] == date(2026, 7, 3)


def test_merged_range_drops_time_and_confidence():
    entries = [_fragment(1), _fragment(2)]
    result = merge_consecutive_entries(entries)
    assert result[0]["time"] is None
    assert result[0]["time_confidence"] is None


def test_gap_in_dates_breaks_the_run_even_with_identical_text():
    # person not found on 2026-07-02 -- identical text resuming on
    # 2026-07-03 must NOT be folded into one range with 07-01, since that
    # would misrepresent presence on the missing day.
    entries = [_fragment(1), _fragment(3)]
    result = merge_consecutive_entries(entries)
    assert len(result) == 2
    assert result[0]["date_from"] == result[0]["date_to"] == date(2026, 7, 1)
    assert result[1]["date_from"] == result[1]["date_to"] == date(2026, 7, 3)


def test_different_text_on_consecutive_days_does_not_merge():
    entries = [_fragment(1, text="text A"), _fragment(2, text="text B")]
    result = merge_consecutive_entries(entries)
    assert len(result) == 2
