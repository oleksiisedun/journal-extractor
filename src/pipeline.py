"""Per-day, per-person pointer resolution (no LLM — see CLAUDE.md's "Core
architectural principle"). Wraps the surname prefilter -> full-name
narrowing -> build_pointer() -> assemble_fragment() chain from
prefilter.py/assembly.py into one reusable call, so generate_extract.py
doesn't have to re-implement the not-found/ambiguous/guardrail branching
inline.
"""

from prefilter import (
    build_pointer,
    extract_full_name,
    extract_surname,
    filter_windows_by_full_name,
    find_candidate_windows,
    select_ambiguous_window,
)
from assembly import assemble_fragment
from config import FULL_NAME_AMBIGUITY_STRATEGY


def resolve_day_fragment(all_paragraphs, day_date, time_boundaries, full_name):
    """Resolves one person's fragment for one day's already-parsed paragraph
    list. `full_name` is a full "rank SURNAME Firstname Patronymic" string,
    same shape as prefilter.extract_surname()/extract_full_name() expect.

    Returns a dict:
      {"status": "found", "result": assemble_fragment()'s dict, "note": str,
       "pointer": dict}
      {"status": "not_found", "result": None, "note": str, "pointer": None}
      {"status": "rejected", "result": None, "note": str, "pointer": dict}  # guardrail
    `note` is a human-readable Ukrainian explanation, suitable for printing
    or logging. `pointer` is build_pointer()'s raw dict (when resolution
    got that far) — kept
    around for the same real-file debugging workflow described in
    CLAUDE.md's bug log (every prefilter.py fix started from inspecting a
    real pointer that came out wrong).
    """
    surname = extract_surname(full_name)
    windows = find_candidate_windows(all_paragraphs, surname)

    if not windows:
        # the surname isn't in this day's text at all
        return {"status": "not_found", "result": None, "pointer": None,
                "note": "Прізвище відсутнє в тексті дня. found=false"}

    # narrow by FULL name (not surname alone) - if this unambiguously
    # narrows to a single window, that window can't mix in another
    # namesake or another, unrelated order.
    name = extract_full_name(full_name)
    narrowed = filter_windows_by_full_name(all_paragraphs, windows, name)
    if len(narrowed) == 0:
        # full name isn't verbatim anywhere in this day's text, even
        # though the surname is -- fail closed rather than guess from
        # weaker (surname-only) context
        return {"status": "not_found", "result": None, "pointer": None,
                "note": "ПОВНЕ ПІБ не знайдено дослівно в тексті дня. found=false"}
    elif len(narrowed) == 1:
        windows_to_use = narrowed
        narrowing_note = "однозначно звужено до 1 вікна за повним ПІБ"
    else:
        windows_to_use = [select_ambiguous_window(narrowed, FULL_NAME_AMBIGUITY_STRATEGY)]
        narrowing_note = (f"увага: повне ПІБ дослівно зустрічається у {len(narrowed)} різних місцях - "
                           f"справжня неоднозначність, беремо {FULL_NAME_AMBIGUITY_STRATEGY} входження")

    # target_paragraph_index is find_full_name_paragraph()'s result;
    # context_paragraph_indices is the governing order + label header,
    # walked back from there -- see build_pointer().
    pointer = build_pointer(all_paragraphs, windows_to_use[0], name)
    pointer["_surname_check"] = surname  # for the sanity check in assemble_fragment

    if not pointer.get("found"):
        return {"status": "not_found", "result": None, "pointer": pointer,
                "note": "Не знайдено в цьому дні (перевір вручну — гепи не пропускаємо мовчки)"}

    try:
        result = assemble_fragment(
            all_paragraphs, pointer,
            date_value=day_date, time_boundaries=time_boundaries,
        )
    except ValueError as e:
        return {"status": "rejected", "result": None, "pointer": pointer,
                "note": f"ПОТРЕБУЄ РУЧНОЇ ПЕРЕВІРКИ — гвардрейл відхилив результат:\n{e}"}

    return {"status": "found", "result": result, "pointer": pointer,
            "note": narrowing_note}
