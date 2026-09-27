"""Shared type aliases and TypedDicts for the shapes passed between
pipeline modules — kept in one place so a shape change (e.g. adding a key)
touches a single definition instead of every module that names it.
"""

from datetime import date
from typing import Literal, NotRequired, TypedDict

# A day's (or window's) parsed paragraphs: (global_index, verbatim_text).
Paragraphs = list[tuple[int, str]]

# A candidate paragraph-index range (lo, hi), both inclusive.
Window = tuple[int, int]

# Resolved (global_content_index, time_value, confidence) boundaries, as
# returned by time_extraction.assign_time_boundaries().
TimeBoundaries = list[tuple[int, str, str]]


class Pointer(TypedDict):
    found: bool
    context_paragraph_indices: list[int]
    target_paragraph_index: int
    # set by pipeline.resolve_day_fragment() after build_pointer() returns,
    # for assemble_fragment()'s surname guardrail — absent until then.
    _surname_check: NotRequired[str]


class Fragment(TypedDict):
    text: str
    date: date | None
    time: str | None
    time_confidence: str


class ResolveResult(TypedDict):
    status: Literal["found", "not_found", "rejected"]
    result: Fragment | None
    pointer: Pointer | None
    note: str


class MergedEntry(TypedDict):
    text: str
    date_from: date
    date_to: date
    time: str | None
    time_confidence: str | None


class Row(TypedDict):
    time_labels: list[tuple[int, str]]
    time_raw_count: int
    content_paragraphs: list[tuple[int, int, str]]
    content_raw_count: int


class WorkingGroupBlock(TypedDict):
    date: date
    text: str
    time: str
    order_ids: list[str]


class DayRecord(TypedDict):
    filename: str
    paragraphs: Paragraphs
    date: date
    time_boundaries: TimeBoundaries
