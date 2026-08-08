"""
Generates a real "витяг" (extract) .docx per person, filling
templates/1.docx from every day's assembled fragment (no LLM anywhere —
see CLAUDE.md's "Core architectural principle"). Days that resolve to
"not_found" or "rejected" are skipped and printed as warnings, never
silently dropped, matching run_demo.py's existing posture.

Cross-day date-range merging ("з ... по ...") and requested-date-range
filtering are NOT done here — every "found" day across all of journals/
becomes its own stacked entry in the output. See CLAUDE.md's "Not yet
built" list.

See README.md for setup/run instructions.
"""

import glob
import os
from datetime import date

from config import COMBAT_LOG_DIR, OUTPUT_DIR, TEMPLATE_PATH
from docx_parsing import extract_date_from_filename, load_paragraph_columns, load_paragraphs
from pipeline import resolve_day_fragment
from prefilter import extract_surname
from render import render_extract
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
        # file, but keep the script runnable in a fresh clone
        test_cases = [
            "солдат ОРЛЕНКО Максим Ігорович",
            "солдат ОРЛЕНКО Богдан Юрійович",
        ]

    # each day's paragraphs/time boundaries only depend on the file, not
    # the person -- load them once and reuse across every person below
    days = []
    for docx_path in docx_paths:
        all_paragraphs = load_paragraphs(docx_path)
        day_date = extract_date_from_filename(docx_path)
        columns = load_paragraph_columns(docx_path)
        content_row = max(columns, key=lambda r: len(r["content_paragraphs"]))
        time_boundaries = assign_time_boundaries(content_row)
        days.append({
            "filename": os.path.basename(docx_path),
            "paragraphs": all_paragraphs,
            "date": day_date,
            "time_boundaries": time_boundaries,
        })

    issue_date = date.today()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for person in test_cases:
        print("=" * 70)
        print("Особа:", person)

        entries = []
        for day in days:
            outcome = resolve_day_fragment(
                day["paragraphs"], day["date"], day["time_boundaries"], person,
            )
            if outcome["status"] == "found":
                entries.append(outcome["result"])
            else:
                print(f"    [{day['filename']}] пропущено: {outcome['note']}")

        if not entries:
            print("  >>> Жодного дня не знайдено для цієї особи — .docx не створено.")
            continue

        surname = extract_surname(person)
        output_path = os.path.join(OUTPUT_DIR, f"Витяг_{surname}_{issue_date.isoformat()}.docx")
        render_extract(entries, issue_date, TEMPLATE_PATH, output_path)
        print(f"  >>> Створено: {output_path}  ({len(entries)} з {len(days)} днів)")


if __name__ == "__main__":
    main()
