"""Cross-day date-range merging (no LLM — see CLAUDE.md's "Core
architectural principle"). Collapses a run of consecutive "found" days
that share byte-identical assembled text into a single "з ... по ..."
range entry, matching how real extract samples represent standing/
recurring text — see
samples/Витяг з ЖБД на 100к ЛИПЕНЬ Сімоненков.docx, where nine identical
"00.00 відповідно до БОЙОВОГО НАКАЗА ..." days collapse into one
"з 01.07.2026 по 09.07.2026" line instead of nine stacked copies.
"""

from datetime import timedelta

from domain_types import Fragment, MergedEntry


def merge_consecutive_entries(entries: list[Fragment]) -> list[MergedEntry]:
    """Merges a chronological list of assemble_fragment() dicts ({"text",
    "date", "time", "time_confidence"}) into ranges. Two entries merge only
    when their text is byte-identical AND their dates are exactly one
    calendar day apart — a gap (the person not found on an intervening day)
    always breaks the run, even if identical text resumes afterward, since
    merging across a gap would misrepresent presence on the missing day(s).

    `time`/`time_confidence` are only kept for single-day entries
    (date_from == date_to) — no single time correctly represents an entire
    multi-day range, so both are set to None rather than showing one day's
    time as if it applied throughout."""
    if not entries:
        return []

    merged: list[MergedEntry] = []
    current = _start_run(entries[0])

    for entry in entries[1:]:
        entry_date = entry["date"]
        assert entry_date is not None, "found days always carry a date"
        same_text = entry["text"] == current["text"]
        consecutive_day = entry_date == current["date_to"] + timedelta(days=1)
        if same_text and consecutive_day:
            current["date_to"] = entry_date
        else:
            merged.append(_finalize_run(current))
            current = _start_run(entry)

    merged.append(_finalize_run(current))
    return merged


def _start_run(entry: Fragment) -> MergedEntry:
    entry_date = entry["date"]
    assert entry_date is not None, "found days always carry a date"
    return {
        "text": entry["text"],
        "date_from": entry_date,
        "date_to": entry_date,
        "time": entry["time"],
        "time_confidence": entry["time_confidence"],
    }


def _finalize_run(run: MergedEntry) -> MergedEntry:
    if run["date_from"] != run["date_to"]:
        run["time"] = None
        run["time_confidence"] = None
    return run
