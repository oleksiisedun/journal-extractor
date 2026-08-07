"""
Mini demo of a local LLM for generating combat log extracts.

See README.md for setup/run instructions and CLAUDE.md for full pipeline
and rule documentation.
"""

import glob
import os

from config import COMBAT_LOG_DIR, FULL_NAME_AMBIGUITY_STRATEGY
from docx_parsing import extract_date_from_filename, load_paragraph_columns, load_paragraphs
from llm_client import ask_llm
from prefilter import (
    extract_full_name,
    extract_surname,
    filter_windows_by_full_name,
    find_candidate_windows,
    select_ambiguous_window,
)
from time_extraction import assign_time_boundaries
from assembly import assemble_fragment


def main():
    docx_paths = sorted(
        glob.glob(os.path.join(COMBAT_LOG_DIR, "*.docx")),
        key=extract_date_from_filename,
    )
    if not docx_paths:
        print(f"У {COMBAT_LOG_DIR}/ немає жодного .docx файлу.")
        return

    try:
        # real names from the actual sample files — gitignored, see
        # local_test_data.py's docstring for how to set it up locally
        from local_test_data import TEST_CASES as test_cases
    except ImportError:
        # fictional placeholders; won't match anything in a real journals/
        # file, but keep the demo runnable in a fresh clone
        test_cases = [
            "солдат ОРЛЕНКО Максим Ігорович",
            "солдат ОРЛЕНКО Богдан Юрійович",
            "сержант НЕІСНУЮЧИЙ Іван Іванович",   # found=false test
        ]

    for docx_path in docx_paths:
        print("#" * 70)
        print("Файл:", os.path.basename(docx_path))

        all_paragraphs = load_paragraphs(docx_path)
        print(f"Завантажено параграфів: {len(all_paragraphs)}\n")

        day_date = extract_date_from_filename(docx_path)

        # find the table row that actually holds the day's content (the one
        # with the most content paragraphs) and derive its time boundaries —
        # see assign_time_boundaries() for why this is heuristic/best-effort
        columns = load_paragraph_columns(docx_path)
        content_row = max(columns, key=lambda r: len(r["content_paragraphs"]))
        time_boundaries = assign_time_boundaries(content_row)
        print(f"Дата: {day_date.isoformat()}    Знайдено часових міток: {len(time_boundaries)}\n")

        for person in test_cases:
            print("=" * 70)
            print("Шукаємо:", person)

            surname = extract_surname(person)
            windows = find_candidate_windows(all_paragraphs, surname)

            if not windows:
                # the surname isn't in this day's text at all — no need to
                # call the LLM, and this is faster and more reliable than
                # asking the model "does this person exist"
                print(">>> Прізвище відсутнє в тексті дня — LLM не викликаємо. found=false")
                continue

            # narrow by FULL name (not surname alone) - if this unambiguously
            # narrows to a single window, the LLM never sees other namesakes
            # or other orders at all.
            full_name = extract_full_name(person)
            narrowed = filter_windows_by_full_name(all_paragraphs, windows, full_name)
            if len(narrowed) == 0:
                # full name isn't verbatim anywhere in this day's text, even
                # though the surname is -- fail closed rather than handing
                # the LLM weaker (surname-only) context to guess from
                print(">>> ПОВНЕ ПІБ не знайдено дослівно в тексті дня — LLM не викликаємо. found=false")
                continue
            elif len(narrowed) == 1:
                windows_to_use = narrowed
                note = "однозначно звужено до 1 вікна за повним ПІБ"
            else:
                windows_to_use = [select_ambiguous_window(narrowed, FULL_NAME_AMBIGUITY_STRATEGY)]
                note = (f"увага: повне ПІБ дослівно зустрічається у {len(narrowed)} різних місцях - "
                        f"справжня неоднозначність, беремо {FULL_NAME_AMBIGUITY_STRATEGY} входження")

            candidate_paragraphs = []
            seen = set()
            for lo, hi in windows_to_use:
                for i in range(lo, hi + 1):
                    if i not in seen:
                        seen.add(i)
                        candidate_paragraphs.append((i, dict(all_paragraphs)[i]))
            print(f"    (префільтр: {len(candidate_paragraphs)} з {len(all_paragraphs)} параграфів, "
                  f"{note})")

            pointer = ask_llm(candidate_paragraphs, person)
            pointer["_surname_check"] = surname  # for the sanity check in assemble_fragment
            print("Відповідь LLM (pointer):", pointer)

            if not pointer.get("found"):
                print(">>> Не знайдено в цьому дні (перевір вручну — гепи не пропускаємо мовчки)")
                continue

            try:
                result = assemble_fragment(
                    all_paragraphs, pointer,
                    date_value=day_date, time_boundaries=time_boundaries,
                )
            except ValueError as e:
                print(f">>> ПОТРЕБУЄ РУЧНОЇ ПЕРЕВІРКИ — гвардрейл відхилив результат:\n{e}")
                print()
                continue

            time_note = "" if result["time_confidence"] == "confident" else "  [!! ЧАС НЕВИЗНАЧЕНИЙ/НЕТОЧНИЙ — перевірити вручну !!]"
            print(f">>> Дата: {result['date'].isoformat()}    Час: {result['time']}{time_note}")
            print(">>> ЗІБРАНИЙ ФРАГМЕНТ (дослівно з джерела):")
            print(result["text"])
            print()


if __name__ == "__main__":
    main()
