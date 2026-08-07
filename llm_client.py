"""Local LLM query — the model only ever returns pointers into a numbered
paragraph list ("where"), never the text itself ("what"). See CLAUDE.md's
"Core architectural principle" for why this is what guarantees
verbatim-fidelity structurally rather than by prompting alone."""

import json

import requests

from config import MODEL, OLLAMA_URL

SYSTEM_PROMPT = """You locate the mention of ONE specific person in a numbered list of
paragraphs from a single day of a combat log.

You are given: rank + full name of the person to find, and a numbered list
of paragraphs.

Output THREE things, never the text itself:
1. "context_paragraph_indices" — paragraphs needed for legal/section context:
   order references (containing "БР", "наказ", "розпорядження", or a number
   like №.../.../ДСК), section headers (e.g. "на ПВ «...»:"). These do NOT
   have to be adjacent to the target paragraph — there can be a large gap
   with OTHER people's own paragraphs in between, and that gap is simply
   skipped, not included. Context paragraphs must NEVER contain other
   people's names.
2. "target_paragraph_index" — the SINGLE paragraph that contains the target
   person. Match the FULL name (surname + first name + patronymic) — the
   document may contain several people with the same surname.
3. "redactions" — ONLY used when OTHER people appear INSIDE that SAME target
   paragraph (e.g. several names in one continuous sentence). Copy their
   text VERBATIM, character-for-character. This is RARE — most of the time
   redactions stays empty, because other people are on their OWN separate
   paragraphs and are simply never selected (see Example 2 below).

   NEVER put the target person's own name into redactions.
   NEVER try to redact a paragraph that is not context_paragraph_indices or
   target_paragraph_index — if another person is on their own separate
   paragraph, just don't select that paragraph. Do not enumerate or redact
   people who are not on the target's own paragraph.

   CRITICAL: the paragraph list you receive may contain candidates from
   MULTIPLE, UNRELATED sections/orders (e.g. two different people with the
   same surname, each governed by a DIFFERENT order). Pick context
   paragraphs ONLY from the SAME section/order that actually governs the
   target paragraph. NEVER combine order-reference paragraphs from two
   different, unrelated orders into context_paragraph_indices — a single
   person's record is governed by exactly ONE order, never two.

If the person is not found in the given list, return found: false,
context_paragraph_indices: [], target_paragraph_index: -1, redactions: [].

CRITICAL: you NEVER rewrite or paraphrase any text. Your job is only to
point to WHERE things are, not to write text yourself.

--- EXAMPLE 1: target is the first person right after a section header ---
[36] на виконання БР командира 7 обр (на бмп) 2 боп 15 обр «СОКІЛ» №БР42/Б3/7Р/ДСК від 15.02.26, продовжують стійко утримувати зайняті рубежі оборони в районі ВЕРБОВЕ, СОСНІВКА, Полтавської громади, Полтавського району, Полтавської області, не допускають раптових дії противника на лінії бойового зіткнення з противником в першому ешелоні оборони:
[37] на ПВ «БЕРЕГ»:
[38] солдат ОРЛЕНКО Олександр Сергійович;
[39] солдат ПЕТРЕНКО Едуард Дмитрович;

Query: "солдат ОРЛЕНКО Олександр Сергійович"
Correct answer:
{"found": true, "context_paragraph_indices": [36, 37], "target_paragraph_index": 38, "redactions": []}
(Paragraph 39 — a different person — is simply never selected. No redaction needed.)

--- EXAMPLE 2: target is deep inside a long list, with OTHER people's own
paragraphs in between the context and the target ---
[89] на виконання БР командира 7 обр (на бмп) 2 боп 15 обр «СОКІЛ» №БР47/Б3/7Р/ДСК від 15.02.26, з метою швидкого реагування ...
[90] молодший сержант КОВАЛЬЧУК Євген Миколайович;
[91] сержант ЮЩЕНКО Ренат Маратович;
[92] старший солдат ДЕМЧЕНКО Олександр Васильович;
[93] солдат ОРЛЕНКО Павло Юрійович;
[94] солдат МАЛЬЦЕВА Олександра Васильович;

Query: "солдат ОРЛЕНКО Павло Юрійович"
Correct answer:
{"found": true, "context_paragraph_indices": [89], "target_paragraph_index": 93, "redactions": []}
(Paragraphs 90-92 and 94 — other people, each on their own paragraph — are
simply never selected and need NO redactions. Do NOT try to list them in
redactions — that is unnecessary and error-prone. Only the context
paragraph [89] and the target paragraph [93] are chosen.)

--- EXAMPLE 3: TWO people share the SAME paragraph — this is when redactions
is actually needed ---
[55] з метою вивчення реального стану справ ... проводили роботу: головний сержант 2 корпусу НГУ «СОКІЛ» майстер-сержант БОНДАРЕНКО Дмитро Сергійович, водій ... солдат ЛИТВИНЕНКО Андрій Іванович (згідно БР ... від 10.02.2026).

Query: "солдат ЛИТВИНЕНКО Андрій Іванович"
Correct answer:
{"found": true, "context_paragraph_indices": [], "target_paragraph_index": 55, "redactions": ["головний сержант 2 корпусу НГУ «СОКІЛ» майстер-сержант БОНДАРЕНКО Дмитро Сергійович, "]}
(Here БОНДАРЕНКО shares the exact same paragraph/sentence as the target, so his
text must be redacted. This is the ONLY situation where redactions is used.)

--- EXAMPLE 4 (rare fallback case): if the list still contains candidates
from TWO DIFFERENT, UNRELATED orders (e.g. two namesakes governed by
different orders) — pick context from the order that actually governs the
target paragraph, never both. A person is governed by exactly ONE order."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "context_paragraph_indices": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Paragraphs needed for legal/section context (order references, "
                           "section headers). NOT necessarily adjacent to the target paragraph, "
                           "and must NEVER contain other people's names.",
        },
        "target_paragraph_index": {"type": "integer"},
        "redactions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Verbatim text of OTHER people to remove, ONLY if they appear "
                           "INSIDE the target paragraph itself (same sentence).",
        },
    },
    "required": ["found", "context_paragraph_indices", "target_paragraph_index", "redactions"],
}


def ask_llm(paragraphs, rank_and_name):
    """Sends the candidate paragraph window to the local LLM and returns the
    parsed pointer JSON — never the assembled text itself."""
    listing = "\n".join(f"[{i}] {text}" for i, text in paragraphs)
    user_prompt = (
        f"Looking for: {rank_and_name}\n\n"
        f"Paragraph list (may be a candidate window, not the full day):\n{listing}"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "format": RESPONSE_SCHEMA,
        "stream": False,
        "think": False,          # CRITICAL: top-level, not inside "options" —
                                  # otherwise Qwen3 (a hybrid thinking model)
                                  # still generates a full reasoning chain, and
                                  # on CPU that is several times slower. The
                                  # "/no_think" text trick in the prompt is an
                                  # unreliable legacy method — don't rely on it.
        "keep_alive": "30m",     # keep the model loaded in memory between calls
        "options": {
            "temperature": 0,
            "num_thread": 8,      # physical cores of the Ryzen 7 7840HS (not
                                   # 16 — SMT often doesn't speed up, and can
                                   # slow down, memory-bound inference; verify
                                   # 16 yourself too)
        },
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return json.loads(content)
