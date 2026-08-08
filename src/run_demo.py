"""
Mini demo of the fully deterministic pipeline for generating combat log
extracts (no LLM — see CLAUDE.md's "Core architectural principle").

See README.md for setup/run instructions and CLAUDE.md for full pipeline
and rule documentation.
"""

import glob
import os

from config import COMBAT_LOG_DIR
from docx_parsing import extract_date_from_filename, load_paragraph_columns, load_paragraphs
from pipeline import resolve_day_fragment
from time_extraction import assign_time_boundaries


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

            outcome = resolve_day_fragment(all_paragraphs, day_date, time_boundaries, person)

            if outcome["pointer"] is None:
                # surname or full name never even matched -- no pointer was built
                print(f">>> {outcome['note']}")
                print()
                continue

            print(f"    ({outcome['note']})")
            print("Вказівник (pointer):", outcome["pointer"])

            if outcome["status"] != "found":
                print(f">>> {outcome['note']}")
                print()
                continue

            result = outcome["result"]
            time_note = "" if result["time_confidence"] == "confident" else "  [!! ЧАС НЕВИЗНАЧЕНИЙ/НЕТОЧНИЙ — перевірити вручну !!]"
            print(f">>> Дата: {result['date'].isoformat()}    Час: {result['time']}{time_note}")
            print(">>> ЗІБРАНИЙ ФРАГМЕНТ (дослівно з джерела):")
            print(result["text"])
            print()


if __name__ == "__main__":
    main()
