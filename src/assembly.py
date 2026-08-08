"""Deterministic fragment assembly + validation (no LLM anywhere in this
pipeline): slices source text per the pointer built by
prefilter.build_pointer(), runs guardrails, applies the one allowed
punctuation fix, and attaches date/time metadata."""

import re

from patterns import ORDER_REF_PATTERN
from time_extraction import time_for_paragraph

# MGRS-style grid coordinate, e.g. "37U CR 1234 5678" — zone+band, 100km
# square, then two equal-length easting/northing digit groups.
COORDINATE_PATTERN = re.compile(r"\d{1,2}[A-Z]\s[A-Z]{2}\s\d{2,5}\s\d{2,5}")

# "за координатами" (by/at coordinates) -- the phrase that introduces an
# MGRS reference, e.g. "Група №2 за координатами (37U CR 1234 5678)" or
# "...за координатами: (37U CR 1234 5678)". Meaningless once the
# coordinates themselves are stripped, so it's removed as part of the same
# coordinate-removal rule (CLAUDE.md rule 4), not a separate one -- same
# rationale as the digits: tactical data with no place in a personnel
# extract. The optional trailing ":" + whitespace is swallowed too, since
# the colon introduces the (now-removed) coordinate parenthetical and is
# equally dangling on its own once the parenthetical is gone.
COORDINATE_LABEL_PATTERN = re.compile(r"за\s+координат\w*:?\s*", re.IGNORECASE)

# "район зосередження" (concentration area) and its grammatical variants
# (районі, району, зосередженню, ...), with an immediately preceding
# preposition (у/в/на) swallowed too so no dangling preposition is left.
LOCATION_LABEL_PATTERN = re.compile(
    r"(?:[ув]|на)\s+район\w*\s+зосередженн\w*|район\w*\s+зосередженн\w*",
    re.IGNORECASE,
)


def _normalize_stripped_whitespace(text):
    """Cleans up leftover spacing after a phrase has been cut out of
    `text`: collapses runs of 2+ spaces/tabs, drops a space/tab now
    stranded directly before punctuation, and trims trailing spaces/tabs
    per line. Shared by strip_coordinates() and strip_location_labels()
    since both need the exact same cleanup after their own removal."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,;.):])", r"\1", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text


def extract_order_refs(text):
    """Extracts order/directive numbers of the form №БР42/Б3/7Р/ДСК from
    text. Whitespace after № is stripped before comparison so the same
    order isn't treated as two different ones just because one mention
    happens to have a space after № and another doesn't (both forms occur
    in real files)."""
    return {re.sub(r"\s+", "", ref) for ref in ORDER_REF_PATTERN.findall(text)}


def strip_coordinates(text):
    """Removes MGRS-style grid coordinates (e.g. '37U CR 1234 5678'), including
    semicolon-separated lists of them, from the given text. Coordinates are
    tactical/operational data and must never appear in the generated
    extract, regardless of how the source formats them. Also drops any
    parenthetical group that becomes empty once its coordinates are removed
    (e.g. 'район зосередження (37U CR 1234 5678; 37U CR 1234 5678)' ->
    'район зосередження')."""
    text = COORDINATE_PATTERN.sub("", text)

    def _drop_if_empty(match):
        inner = match.group(1)
        return "" if re.fullmatch(r"[\s;]*", inner) else match.group(0)

    text = re.sub(r"\(([^()]*)\)", _drop_if_empty, text)
    text = COORDINATE_LABEL_PATTERN.sub("", text)
    # the comma that used to separate the preceding clause from "за
    # координатами" is left dangling once that phrase and its parenthetical
    # are gone (e.g. "...області, за координатами: (...)." -> "...області,."
    # without this) -- drop it so it doesn't collide with the punctuation
    # that now immediately follows.
    text = re.sub(r",\s*([.;])", r"\1", text)
    return _normalize_stripped_whitespace(text)


def strip_location_labels(text):
    """Removes the phrase 'район зосередження' and its grammatical variants
    (районі, району, зосередженню, ...) from text, swallowing an immediately
    preceding preposition (у/в/на) so no dangling preposition is left. Like
    coordinates, this is location/tactical information with no place in a
    personnel extract — applied unconditionally, not just when it looks
    out of place."""
    text = LOCATION_LABEL_PATTERN.sub("", text)
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    return _normalize_stripped_whitespace(text)


def assemble_fragment(paragraphs, pointer, date_value=None, time_boundaries=None):
    """Deterministically assembles the final fragment from the pointer
    built by prefilter.build_pointer() — slices source text, runs
    guardrails, applies the one allowed punctuation fix. Also attaches the
    day's date (from the filename, via extract_date_from_filename()) and
    the heuristically assigned time (via assign_time_boundaries() +
    time_for_paragraph()). Returns a dict, not a bare string, since
    date/time metadata rides along with the text."""
    para_dict = dict(paragraphs)

    if not pointer["found"]:
        return None

    context_indices = pointer["context_paragraph_indices"]
    target_index = pointer["target_paragraph_index"]
    indices = sorted(set(context_indices + [target_index]))
    parts = [para_dict[i] for i in indices]

    # SANITY GUARDRAIL: if TWO DIFFERENT context paragraphs each cite an
    # order number, that's a sign context was pulled in from an unrelated,
    # foreign order (found empirically, back when this pipeline used an
    # LLM: context=[36, 89], where 36 belongs to БР18 for a DIFFERENT
    # person, and 89 to the correct БР19). build_pointer() only ever adds a
    # single preceding order paragraph, so more than one order-bearing
    # paragraph in context means two unrelated legal bases got merged.
    # NOTE: a single paragraph legitimately citing multiple orders together
    # as one joint legal basis (e.g. "на виконання БОЙОВОГО НАКАЗУ ...
    # №БН5/Б3/ДСК ... та БОЙОВОГО РОЗПОРЯДЖЕННЯ ... №БР63/Б3/9Р/ДСК ...")
    # is real and must NOT trip this — so the check counts order-bearing
    # PARAGRAPHS, not distinct order numbers.
    order_bearing_paragraphs = [i for i in context_indices if extract_order_refs(para_dict[i])]
    if len(order_bearing_paragraphs) > 1:
        conflicting_refs = {
            ref for i in order_bearing_paragraphs for ref in extract_order_refs(para_dict[i])
        }
        raise ValueError(
            f"PIPELINE ERROR: context paragraphs reference MULTIPLE "
            f"different orders at once ({conflicting_refs}) — a person can only "
            f"be governed by one order. Result REJECTED.\n"
            f"context_paragraph_indices={context_indices}"
        )

    # mechanical strip — coordinates and location labels carry no legal/
    # identity meaning for the extract and must never leak into the output
    # (see strip_coordinates, strip_location_labels)
    parts = [strip_location_labels(strip_coordinates(p)) for p in parts]

    fragment_text = "\n".join(parts)

    # SANITY GUARDRAIL: the target person's surname must physically be
    # present in the final fragment — catches target_paragraph_index
    # pointing at the wrong paragraph, or a stripping rule accidentally
    # eating it.
    surname = pointer.get("_surname_check")
    if surname and surname.upper() not in fragment_text.upper():
        raise ValueError(
            f"PIPELINE ERROR: surname '{surname}' is missing from the "
            f"assembled fragment — target_paragraph_index likely points at "
            f"the wrong paragraph. Result REJECTED.\nfragment_text={fragment_text!r}"
        )

    # the one allowed exception to the "verbatim" rule
    stripped = fragment_text.rstrip()
    if stripped.endswith(";"):
        stripped = stripped[:-1] + "."

    time_result = time_for_paragraph(time_boundaries, target_index) if time_boundaries else None
    time_value, time_confidence = time_result if time_result else (None, "uncertain")

    return {
        "text": stripped,
        "date": date_value,
        "time": time_value,
        "time_confidence": time_confidence,
    }
