"""
Generates a real "витяг" (extract) .docx per person, filling
templates/1.docx from every day's assembled fragment (no LLM anywhere —
see CLAUDE.md's "Core architectural principle"). Days that resolve to
"not_found" or "rejected" are skipped and printed as warnings, never
silently dropped.

A per-person requested date/date-range (optional trailing token on the
CLI spec, see person_spec.parse_person_spec()) narrows which journals/
days are searched and flags dates in that range with no matching file.
Consecutive "found" days with byte-identical assembled text are collapsed
into a single "з ... по ..." range entry by merge.merge_consecutive_entries()
before rendering.

Run via run.sh — see README.md for setup/run instructions.
"""

import glob
import os
import sys
from datetime import date, timedelta

from config import JOURNAL_DIR, OUTPUT_DIR, TEMPLATE_PATH
from docx_parsing import extract_date_from_filename, load_paragraph_columns, load_paragraphs
from merge import merge_consecutive_entries
from person_spec import parse_person_spec
from pipeline import resolve_day_fragment
from prefilter import extract_surname
from render import render_extract
from time_extraction import assign_time_boundaries


def load_people(argv):
    """People to extract, from CLI args: either raw "rank SURNAME
    Firstname Patronymic [DD.MM.YYYY[-DD.MM.YYYY]]" strings passed
    directly, or -- if `argv` is a single existing file path -- one such
    string per non-blank line of that file. The trailing date/date-range
    is optional and, when present, restricts that person's search to
    those day(s) instead of every file in journals/ -- see
    person_spec.parse_person_spec().
    @param {list[str]} argv
    @returns {list[str]}
    """
    if not argv:
        print("Використання: ./run.sh <ім'я> [<ім'я> ...] | <names.txt>")
        sys.exit(1)

    if len(argv) == 1 and os.path.isfile(argv[0]):
        with open(argv[0], encoding="utf-8") as f:
            people = [line.strip() for line in f if line.strip()]
        if not people:
            print(f"{argv[0]} не містить жодного імені.")
            sys.exit(1)
        return people

    return argv


def main():
    people = load_people(sys.argv[1:])

    docx_paths = []
    for docx_path in glob.glob(os.path.join(JOURNAL_DIR, "**", "*.docx"), recursive=True):
        try:
            extract_date_from_filename(docx_path)
        except ValueError:
            print(f"Пропущено (немає дати в назві файлу): {os.path.basename(docx_path)}")
            continue
        docx_paths.append(docx_path)
    docx_paths.sort(key=extract_date_from_filename)
    if not docx_paths:
        print(f"У {JOURNAL_DIR}/ немає жодного .docx файлу.")
        return

    # each day's paragraphs/time boundaries only depend on the file, not
    # the person -- load them once and reuse across every person below
    days = []
    for docx_path in docx_paths:
        columns = load_paragraph_columns(docx_path)
        if not columns:
            print(f"Пропущено (немає таблиці в файлі): {os.path.basename(docx_path)}")
            continue
        all_paragraphs = load_paragraphs(docx_path)
        day_date = extract_date_from_filename(docx_path)
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

    for person in people:
        print("=" * 70)
        print("Особа:", person)

        try:
            full_name, date_from, date_to = parse_person_spec(person)
        except ValueError as e:
            print(f"  >>> Пропущено особу «{person}»: {e}")
            continue

        if date_from is None:
            relevant_days = days
        else:
            relevant_days = [d for d in days if date_from <= d["date"] <= date_to]
            covered_dates = {d["date"] for d in relevant_days}
            missing_date = date_from
            while missing_date <= date_to:
                if missing_date not in covered_dates:
                    print(
                        f"    [{missing_date.isoformat()}] ЖУРНАЛ ВІДСУТНІЙ — "
                        f"файл за цю дату не знайдено в {JOURNAL_DIR}/"
                    )
                missing_date += timedelta(days=1)

        entries = []
        for day in relevant_days:
            outcome = resolve_day_fragment(
                day["paragraphs"], day["date"], day["time_boundaries"], full_name,
            )
            if outcome["status"] == "found":
                entries.append(outcome["result"])
            else:
                print(f"    [{day['filename']}] пропущено: {outcome['note']}")

        if not entries:
            print("  >>> Жодного дня не знайдено для цієї особи — .docx не створено.")
            continue

        surname = extract_surname(full_name)
        output_path = os.path.join(OUTPUT_DIR, f"Витяг_{surname}_{issue_date.isoformat()}.docx")
        render_extract(merge_consecutive_entries(entries), issue_date, TEMPLATE_PATH, output_path)
        print(f"  >>> Створено: {output_path}  ({len(entries)} з {len(relevant_days)} днів)")


if __name__ == "__main__":
    main()
