"""Deterministic surname/full-name candidate narrowing and pointer
resolution (no LLM anywhere in this pipeline) — narrowing keeps namesake
windows governed by two different, unrelated orders from ever being mixed
together, and build_pointer() resolves the final answer: which paragraph
holds the target and which paragraphs are needed for legal/section
context."""

import re

from patterns import ORDER_REF_PATTERN


def find_candidate_windows(paragraphs, surname, window=8):
    """Deterministic prefilter (no LLM): paragraph windows around mentions
    of the SURNAME, not the full name — avoids losing namesakes at this
    stage."""
    para_dict = dict(paragraphs)
    max_idx = max(para_dict.keys())
    hits = [i for i, t in paragraphs if surname.upper() in t.upper()]
    if not hits:
        return []

    raw_windows = [(max(0, i - window), min(max_idx, i + 1)) for i in hits]
    raw_windows.sort()
    merged = [raw_windows[0]]
    for lo, hi in raw_windows[1:]:
        if lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def extract_full_name(rank_and_name):
    """Surname + first name + patronymic (without rank) — for narrower
    candidate filtering than searching by surname alone."""
    tokens = rank_and_name.split()
    surname_idx = None
    for i, w in enumerate(tokens):
        letters = [c for c in w if c.isalpha()]
        if letters and w == w.upper():
            surname_idx = i
            break
    if surname_idx is None:
        raise ValueError(f"Could not determine surname in: {rank_and_name!r}")
    return " ".join(tokens[surname_idx:surname_idx + 3])


def extract_surname(rank_and_name):
    """The surname is normally written in UPPERCASE, and is always the
    first token of extract_full_name()'s result — reuse that lookup rather
    than re-scanning for the uppercase token a second time."""
    return extract_full_name(rank_and_name).split()[0]


def filter_windows_by_full_name(paragraphs, windows, full_name):
    """Narrows surname-based windows down to the ones where the FULL name
    occurs verbatim, removing ambiguity before the LLM call rather than
    relying on the model to pick the right window."""
    para_dict = dict(paragraphs)
    matched = []
    for lo, hi in windows:
        text = " ".join(para_dict[i] for i in range(lo, hi + 1))
        if full_name.upper() in text.upper():
            matched.append((lo, hi))
    return matched


def select_ambiguous_window(windows, strategy):
    """Picks a single window when the full name matched verbatim in more
    than one place (genuine ambiguity, e.g. two identically-named people).
    `windows` must be pre-sorted in file order, as returned by
    filter_windows_by_full_name() (which preserves find_candidate_windows()'s
    ascending order) -- "first"/"last" then mean first/last occurrence in
    the file."""
    if strategy == "first":
        return windows[0]
    if strategy == "last":
        return windows[-1]
    raise ValueError(f"Unknown FULL_NAME_AMBIGUITY_STRATEGY: {strategy!r} (expected 'first' or 'last')")


def find_full_name_paragraph(paragraphs, window, full_name):
    """Returns the index of the single paragraph within `window` that
    contains the full name verbatim -- the anchor the target almost
    certainly sits on -- or None if no single paragraph in the window
    contains it (e.g. the name happens to span a paragraph break in the
    joined window text that filter_windows_by_full_name() checked)."""
    lo, hi = window
    para_dict = dict(paragraphs)
    for i in range(lo, hi + 1):
        if full_name.upper() in para_dict[i].upper():
            return i
    return None


def find_preceding_order_paragraph(paragraphs, anchor_index):
    """Walks backward from `anchor_index` for the nearest paragraph matching
    ORDER_REF_PATTERN -- the section/order header that actually governs the
    anchor. This can sit much further back than the fixed ±window: a single
    order (e.g. a БОЙОВИЙ НАКАЗ) can head a long composition list of many
    call-sign groups, so the governing order paragraph for someone deep in
    that list may be dozens of paragraphs away. Without this, the LLM's
    window can end up containing only a LATER, unrelated order paragraph
    (one that starts the next section right after the target) and mistake
    it for context -- found empirically, see CLAUDE.md bug log. Returns
    None if no such paragraph exists before the anchor."""
    para_dict = dict(paragraphs)
    for i in range(anchor_index - 1, -1, -1):
        if ORDER_REF_PATTERN.search(para_dict[i]):
            return i
    return None


# A bare (non-quoted) run of 3+ uppercase Cyrillic letters -- the shape a
# real personnel surname always has (see extract_surname()). Used to tell a
# group/list sub-header apart from another person's own paragraph when
# neither the guillemet nor colon signal is present (see
# find_preceding_label_header()).
SURNAME_LIKE_PATTERN = re.compile(r"[А-ЯЁІЇЄҐ]{3,}")
QUOTED_LABEL_PATTERN = re.compile(r"«[^»]*»")


def find_preceding_label_header(paragraphs, anchor_index, lower_bound=0):
    """Walks backward from `anchor_index` (exclusive) down to `lower_bound`
    (exclusive -- normally find_preceding_order_paragraph()'s result, so
    the search never wanders into an earlier, unrelated section) for the
    nearest paragraph that looks like a position/call-sign/group label
    header, skipping over OTHER people's own paragraphs along the way --
    the target isn't always the first person listed under their label (e.g.
    'Пост повітряного прикриття № 2:' followed by two people, the target
    being the second). This mirrors context_paragraph_indices' own
    semantics (CLAUDE.md: 'Not necessarily contiguous with the target --
    there can be a long run of other people's own paragraphs in between,
    and that gap is simply skipped').

    Two signals for "this is a label", checked per paragraph:
    1. Quoted in « » guillemets (e.g. 'СЗМ «ФЛЕШ»') or ending in ':' (e.g.
       'на ПВ «БЕРЕГ»:', 'Пост повітряного прикриття № 2 (...):'). Real
       personnel entries never contain guillemets or end in ':' (verified
       across all sample files) -- strong enough to trust across the whole
       walk, skipping over any other people's paragraphs first.
    2. Fallback for labels with NEITHER signal -- e.g. 'Група №2 за
       координатами (...)', lowercase 'група 1', 'Інженерно-саперна група
       №1' (verified as a recurring pattern across two different sample
       files, not a one-off). Real personnel lines always carry their
       surname in bare ALL CAPS, so the absence of one outside any «»
       quoting (call-sign text like 'ФЛЕШ' is also all-caps but IS quoted)
       is a safe signal this is a label, not another person's own
       paragraph -- but weaker than signal 1, so only trusted when
       immediately adjacent to the target (never after skipping over
       someone else first), to avoid guessing on a distant, ambiguous line.

    This complements find_preceding_order_paragraph(), which can land far
    back and miss an immediate sub-header the target sits directly under
    (found empirically: an earlier LLM-based version of this pipeline was
    given a label already in-window and still didn't select it as context
    even after a prompt clarification -- see CLAUDE.md bug log). Returns
    None if nothing matches before `lower_bound`."""
    para_dict = dict(paragraphs)
    for i in range(anchor_index - 1, lower_bound, -1):
        text = para_dict[i].strip()
        if not text:
            continue
        if "«" in text or "»" in text or text.endswith(":"):
            return i
        without_quotes = QUOTED_LABEL_PATTERN.sub("", text)
        if SURNAME_LIKE_PATTERN.search(without_quotes):
            continue  # someone else's own paragraph -- skip over it, keep walking back
        if i == anchor_index - 1:
            return i  # weak (no-surname) fallback only trusted when directly adjacent
        return None  # ambiguous line further back with neither strong signal nor a name -- stop rather than guess
    return None


def build_pointer(paragraphs, window, full_name):
    """Deterministically builds the pointer dict describing where a
    person's entry sits -- replaces the local LLM call this project used
    to make. Full-name narrowing (filter_windows_by_full_name()) has
    already confirmed `full_name` occurs verbatim somewhere in `window` by
    the time this is called, so target_paragraph_index is simply
    find_full_name_paragraph()'s result, and context_paragraph_indices is
    exactly the governing order + label header found by
    find_preceding_order_paragraph() / find_preceding_label_header(). No
    redactions: a person sharing the target's paragraph is left in the
    text as-is (project decision -- see CLAUDE.md)."""
    anchor = find_full_name_paragraph(paragraphs, window, full_name)
    if anchor is None:
        # full_name matched in the window's joined text but not within a
        # single paragraph (e.g. it spans a paragraph break) -- never
        # observed in real files; fail closed rather than guess.
        return {"found": False, "context_paragraph_indices": [], "target_paragraph_index": -1}

    order_idx = find_preceding_order_paragraph(paragraphs, anchor)
    label_idx = find_preceding_label_header(paragraphs, anchor, order_idx or 0)
    context = sorted({i for i in (order_idx, label_idx) if i is not None})
    return {"found": True, "context_paragraph_indices": context, "target_paragraph_index": anchor}
