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

from assembly import strip_coordinates, strip_location_labels
from config import JOURNAL_DIR, OUTPUT_DIR, TEMPLATE_PATH, WORKING_GROUP_UNIT_PREFIX
from docx_parsing import extract_date_from_filename, load_paragraph_columns, load_paragraphs
from merge import merge_consecutive_entries
from person_spec import parse_person_spec
from pipeline import resolve_day_fragment
from prefilter import extract_surname
from render import render_extract
from time_extraction import assign_time_boundaries
from working_groups import (
    build_working_group_filename,
    group_consecutive_identical_blocks,
    parse_working_group_blocks,
    union_order_ids,
)


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
        if argv[0].lower().endswith((".doc", ".docx")):
            print(
                f"«{argv[0]}» — це .docx файл, не список імен. Якщо це звіт "
                f"«РОБОЧІ ГРУПИ», використайте:\n"
                f"  ./run.sh --working-groups {argv[0]!r}"
            )
            sys.exit(1)
        try:
            with open(argv[0], encoding="utf-8") as f:
                people = [line.strip() for line in f if line.strip()]
        except UnicodeDecodeError:
            print(f"{argv[0]} не є текстовим файлом у кодуванні UTF-8 зі списком імен.")
            sys.exit(1)
        if not people:
            print(f"{argv[0]} не містить жодного імені.")
            sys.exit(1)
        return people

    return argv


def _dedupe_output_path(path, used_paths):
    """Returns `path` unchanged if not already in `used_paths`, else
    appends a " (2)", " (3)", ... suffix before the extension until it's
    unique -- two working-group blocks can land on the exact same date +
    order-id set and would otherwise silently overwrite each other.
    @param {str} path
    @param {set[str]} used_paths
    @returns {str}
    """
    if path not in used_paths:
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while f"{base} ({n}){ext}" in used_paths:
        n += 1
    deduped = f"{base} ({n}){ext}"
    print(f"  Попередження: файл-дублікат назви, перейменовано в {deduped}")
    return deduped


def generate_working_groups(docx_path, year_override=None):
    """Entry point for --working-groups mode: one extract .docx per run of
    chronologically-consecutive reporting blocks that share byte-identical
    text (a recurring item, only date/time differing) found in a
    working-groups report, instead of the usual one-per-person-across-
    many-days extract. See working_groups.parse_working_group_blocks() for
    how blocks are found and working_groups.group_consecutive_identical_blocks()
    for how they're grouped.
    @param {str} docx_path
    @param {int|None} year_override -- overrides the fallback year used for
        blocks whose date comes from a bare DD.MM section header (see
        parse_working_group_blocks()); pass when the report doesn't cover
        the year the script happens to run in (e.g. a December report
        processed in January).
    """
    if not os.path.isfile(docx_path):
        print(f"Файл не знайдено: {docx_path}")
        sys.exit(1)
    if not docx_path.lower().endswith((".doc", ".docx")):
        print(f"Очікується .doc або .docx файл: {docx_path}")
        sys.exit(1)
    with open(docx_path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04":
        print(
            f"«{os.path.basename(docx_path)}» — це застарілий бінарний .doc "
            f"(не .docx), який не підтримується. Збережіть файл як .docx "
            f"(Word/LibreOffice: «Зберегти копію» → .docx) і спробуйте ще раз."
        )
        sys.exit(1)

    blocks = parse_working_group_blocks(docx_path, year_override)
    if not blocks:
        print(f"У {docx_path} не знайдено жодного блоку.")
        return
    blocks.sort(key=lambda b: b["date"])

    # process each block's text fully (coordinate/location stripping, the
    # trailing punctuation fix) BEFORE grouping, so the equality check in
    # group_consecutive_identical_blocks() compares final rendered text,
    # not raw source text that could still differ (or coincidentally
    # match) before those strips are applied.
    processed_blocks = []
    for block in blocks:
        text = strip_location_labels(strip_coordinates(block["text"])).rstrip()
        if text.endswith(";"):
            text = text[:-1] + "."
        processed_blocks.append({**block, "text": text})

    groups = group_consecutive_identical_blocks(processed_blocks)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    used_paths = set()

    for group in groups:
        entries = [
            {
                "text": b["text"],
                "date_from": b["date"],
                "date_to": b["date"],
                "time": b["time"],
                "time_confidence": "uncertain",
            }
            for b in group
        ]
        order_ids = union_order_ids(b["order_ids"] for b in group)

        filename = build_working_group_filename(
            WORKING_GROUP_UNIT_PREFIX, group[0]["date"], group[-1]["date"], order_ids
        )
        output_path = _dedupe_output_path(os.path.join(OUTPUT_DIR, filename), used_paths)
        used_paths.add(output_path)

        render_extract(entries, TEMPLATE_PATH, output_path)
        print(f"  >>> Створено: {output_path}  ({len(group)} днів)")

    print(f"Разом: {len(groups)} файлів з {len(blocks)} блоків.")


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["--working-groups"]:
        rest = argv[1:]
        year_override = None
        if "--year" in rest:
            idx = rest.index("--year")
            try:
                year_override = int(rest[idx + 1])
            except (IndexError, ValueError):
                print("Використання: ./run.sh --working-groups <файл.docx> [--year YYYY]")
                sys.exit(1)
            del rest[idx:idx + 2]
        if len(rest) != 1:
            print("Використання: ./run.sh --working-groups <файл.docx> [--year YYYY]")
            sys.exit(1)
        generate_working_groups(rest[0], year_override)
        return

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
        render_extract(merge_consecutive_entries(entries), TEMPLATE_PATH, output_path)
        print(f"  >>> Створено: {output_path}  ({len(entries)} з {len(relevant_days)} днів)")


if __name__ == "__main__":
    main()
