"""Fills templates/1.docx-style extract templates with assembled fragments
(no LLM, no text generation — see CLAUDE.md's "Core architectural
principle"). Every placeholder is replaced with text that already came
verbatim out of assembly.assemble_fragment(); this module only arranges
that text into the template's paragraphs, it never invents any of it.

Cross-day date-range merging ("з ... по ...") is NOT done here — each
entry renders as its own stacked date/fragment block, one after another.
See CLAUDE.md's "Not yet built" list.
"""

import copy
import os

import docx
from docx.oxml.ns import qn


def _replace_run_placeholder(document, placeholder, value):
    """Substring-replaces `placeholder` inside whichever run of a top-level
    (non-table) paragraph contains it, e.g. '3 ДСК/Х/7 від {дата витягу}'
    -> '...від 01.08.2026' — formatting of the surrounding run is
    untouched since only its text content changes."""
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            if placeholder in run.text:
                run.text = run.text.replace(placeholder, value)
                return
    raise ValueError(f"Placeholder {placeholder!r} not found in template")


def _find_placeholder_paragraph(document, placeholder):
    """Finds the table-cell paragraph whose entire text is exactly
    `placeholder` (e.g. '{дата}', '{витяг}') — in the real template each
    one is the sole content of its own paragraph, distinct from
    _replace_run_placeholder's case of a placeholder sharing a run with
    other text."""
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if paragraph.text == placeholder:
                        return paragraph
    raise ValueError(f"Placeholder {placeholder!r} not found in template")


def _expand_multiline_placeholder(paragraph, lines):
    """Replaces a paragraph whose only content is a placeholder run with
    one paragraph per entry in `lines` (an empty string renders as a blank
    paragraph, matching how real extract samples separate stacked entries).
    Each new paragraph is a deep copy of the placeholder paragraph's XML,
    so it inherits the exact same pPr/rPr formatting (font, size, spacing)
    without this code needing to know or hardcode any of it."""
    p_element = paragraph._p
    parent = p_element.getparent()

    for line in lines:
        new_p = copy.deepcopy(p_element)
        runs = new_p.findall(qn("w:r"))
        if line == "":
            for run_element in runs:
                new_p.remove(run_element)
        else:
            t_elements = new_p.findall(".//" + qn("w:t"))
            t_elements[0].text = line
            t_elements[0].set(qn("xml:space"), "preserve")
            for run_element in runs[1:]:
                new_p.remove(run_element)
        p_element.addprevious(new_p)

    parent.remove(p_element)


def _format_time_line(entry):
    """One line for an entry's time: the raw value as-is when confident,
    flagged inline when uncertain or entirely unresolved — never silently
    presented as fact (same posture as CLAUDE.md's time-extraction
    guardrails and generate_extract.py's console warnings)."""
    time_value = entry["time"]
    if time_value is None:
        return "час не визначено — перевірити"
    if entry["time_confidence"] == "uncertain":
        return f"{time_value} (час приблизний — перевірити)"
    return time_value


def _format_date_lines(entries):
    """Builds the {дата} cell's lines: date + time per entry, blank-line
    separated between entries (none trailing)."""
    lines = []
    for i, entry in enumerate(entries):
        if i > 0:
            lines.append("")
        lines.append(entry["date"].strftime("%d.%m.%Y"))
        lines.append(_format_time_line(entry))
    return lines


def _format_fragment_lines(entries):
    """Builds the {витяг} cell's lines: each entry's already-assembled
    verbatim text split on its own paragraph breaks, blank-line separated
    between entries (none trailing)."""
    lines = []
    for i, entry in enumerate(entries):
        if i > 0:
            lines.append("")
        lines.extend(entry["text"].split("\n"))
    return lines


def render_extract(entries, issue_date, template_path, output_path):
    """Fills `template_path` with `entries` (a chronological list of
    assemble_fragment()'s result dicts — {"text", "date", "time",
    "time_confidence"} — for one person's "found" days only; callers are
    expected to have already filtered out "not_found"/"rejected" days) and
    saves the result to `output_path`. `issue_date` fills the header's
    {дата витягу} placeholder.
    """
    if not entries:
        raise ValueError("No fragments to render — entries is empty.")

    document = docx.Document(template_path)

    _replace_run_placeholder(document, "{дата витягу}", issue_date.strftime("%d.%m.%Y"))

    date_paragraph = _find_placeholder_paragraph(document, "{дата}")
    fragment_paragraph = _find_placeholder_paragraph(document, "{витяг}")
    _expand_multiline_placeholder(date_paragraph, _format_date_lines(entries))
    _expand_multiline_placeholder(fragment_paragraph, _format_fragment_lines(entries))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    document.save(output_path)
