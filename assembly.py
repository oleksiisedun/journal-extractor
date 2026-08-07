"""Deterministic fragment assembly + validation (no LLM): slices source
text per the LLM's pointer, applies exact-match redactions, runs
guardrails, applies the one allowed punctuation fix, and attaches date/time
metadata."""

import re

from patterns import ORDER_REF_PATTERN
from time_extraction import time_for_paragraph

# MGRS-style grid coordinate, e.g. "37U CR 1234 5678" — zone+band, 100km
# square, then two equal-length easting/northing digit groups.
COORDINATE_PATTERN = re.compile(r"\d{1,2}[A-Z]\s[A-Z]{2}\s\d{2,5}\s\d{2,5}")

# "район зосередження" (concentration area) and its grammatical variants
# (районі, району, зосередженню, ...), with an immediately preceding
# preposition (у/в/на) swallowed too so no dangling preposition is left.
LOCATION_LABEL_PATTERN = re.compile(
    r"(?:[ув]|на)\s+район\w*\s+зосередженн\w*|район\w*\s+зосередженн\w*",
    re.IGNORECASE,
)


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
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,;.):])", r"\1", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text


def strip_location_labels(text):
    """Removes the phrase 'район зосередження' and its grammatical variants
    (районі, району, зосередженню, ...) from text, swallowing an immediately
    preceding preposition (у/в/на) so no dangling preposition is left. Like
    coordinates, this is location/tactical information with no place in a
    personnel extract — applied unconditionally, not just when it looks
    out of place."""
    text = LOCATION_LABEL_PATTERN.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,;.):])", r"\1", text)
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text


def assemble_fragment(paragraphs, pointer, date_value=None, time_boundaries=None):
    """Deterministically assembles the final fragment from the LLM's pointer
    — slices source text, applies redactions, runs guardrails, applies the
    one allowed punctuation fix. Also attaches the day's date (from the
    filename, via extract_date_from_filename()) and the heuristically
    assigned time (via assign_time_boundaries() + time_for_paragraph()) —
    both deterministic, no LLM involvement. Returns a dict, not a bare
    string, since date/time metadata rides along with the text."""
    para_dict = dict(paragraphs)

    if not pointer["found"]:
        return None

    context_indices = pointer["context_paragraph_indices"]
    target_index = pointer["target_paragraph_index"]
    indices = sorted(set(context_indices + [target_index]))
    parts = [para_dict[i] for i in indices]

    # SANITY GUARDRAIL: if TWO DIFFERENT order numbers appear among the
    # CONTEXT paragraphs (not among all selected paragraphs — the target
    # paragraph itself may not contain a number at all), that's a sign the
    # model stuck in context from an unrelated, foreign order (found
    # empirically: context=[36, 89], where 36 belongs to БР18 for a
    # DIFFERENT person, and 89 to the correct БР19). One person cannot be
    # governed by two different orders at once within a single record.
    order_refs = set()
    for i in context_indices:
        order_refs |= extract_order_refs(para_dict[i])
    if len(order_refs) > 1:
        raise ValueError(
            f"MODEL LOGIC ERROR: context paragraphs reference MULTIPLE "
            f"different orders at once ({order_refs}) — this is a sign the "
            f"model mixed in context from an unrelated, foreign section. "
            f"Result REJECTED.\ncontext_paragraph_indices={context_indices}"
        )

    # apply redactions — exact str.replace, fail-closed
    for r in pointer["redactions"]:
        applied = False
        for i in range(len(parts)):
            if r in parts[i]:
                parts[i] = parts[i].replace(r, "")
                applied = True
        if not applied:
            raise ValueError(
                f"VALIDATION ERROR: string to remove was not found verbatim "
                f"in the selected paragraphs — result REJECTED, manual review needed:\n{r!r}"
            )

    # mechanical strip — coordinates and location labels carry no legal/
    # identity meaning for the extract and must never leak into the output
    # (see strip_coordinates, strip_location_labels)
    parts = [strip_location_labels(strip_coordinates(p)) for p in parts]

    fragment_text = "\n\n".join(parts)

    # SANITY GUARDRAIL: the target person's full name must physically be
    # present in the final fragment. If the model mistakenly put the
    # target THEMSELVES into redactions (confusing "who is the target" with
    # "who to remove"), the fragment would come out without them, and this
    # must be caught here, not let through.
    surname = pointer.get("_surname_check")
    if surname and surname.upper() not in fragment_text.upper():
        raise ValueError(
            f"MODEL LOGIC ERROR: surname '{surname}' is missing from the "
            f"assembled fragment — the LLM likely redacted the target person "
            f"themselves by mistake. Result REJECTED.\nfragment_text={fragment_text!r}"
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
