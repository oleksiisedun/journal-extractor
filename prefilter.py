"""Deterministic surname/full-name candidate narrowing (no LLM) — this is
what keeps the LLM from ever seeing two unrelated namesake windows at once,
and lets it be skipped entirely when a person isn't in a given day at all."""


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
