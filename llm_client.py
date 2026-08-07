"""Local LLM query — the model only ever returns pointers into a numbered
paragraph list ("where"), never the text itself ("what"). See CLAUDE.md's
"Core architectural principle" for why this is what guarantees
verbatim-fidelity structurally rather than by prompting alone."""

import json

import requests

from config import MODEL, OLLAMA_URL

SYSTEM_PROMPT = """You locate the mention of ONE specific person in a numbered list of
paragraphs from a single day of a combat log. You are given a rank + full
name to find, and the numbered paragraph list.

Output THREE things, never the text itself:
1. "context_paragraph_indices" — paragraphs needed for legal/section
   context: order references (containing "БР", "наказ", "розпорядження", or
   №.../.../ДСК), section/position headers (e.g. "на ПВ «...»:", or a short
   standalone call-sign label immediately above the target's own paragraph
   like "СЗМ «ФЛЕШ»" — these headers often have NO trailing punctuation at
   all, unlike ordinary content lines which always end in ; or . — don't
   skip one just because it lacks a colon or an order number). Not necessarily
   adjacent to the target — skip over any gap of other people's own
   paragraphs. Must never contain other people's names, and must come from
   the SAME order/section that governs the target — if the list contains
   candidates from two different, unrelated orders (e.g. two namesakes),
   never mix context from both; a person is governed by exactly one order.
   The governing order always comes BEFORE the target in the paragraph
   numbering, even if far before it (a single order can head a long list of
   many groups). An order-reference paragraph that appears AFTER the target
   starts the NEXT, later section — never select it as context.
2. "target_paragraph_index" — the SINGLE paragraph containing the target,
   matched by FULL name (surname + first name + patronymic), since several
   people may share a surname.
3. "redactions" — ONLY the verbatim (character-for-character) text of OTHER
   people who appear INSIDE the target's own paragraph/sentence. Rare. If
   another person is on their own separate paragraph, just don't select
   that paragraph — never redact or enumerate it. Never put the target's
   own name into redactions.

If not found: found=false, context_paragraph_indices=[],
target_paragraph_index=-1, redactions=[].

You NEVER rewrite or paraphrase — only point to WHERE things are.

--- EXAMPLE 1: target right after a section header, one unselected neighbor after it ---
[36] на виконання БР командира 7 обр (на бмп) 2 боп 15 обр «СОКІЛ» №БР42/Б3/7Р/ДСК від 15.02.26, продовжують стійко утримувати зайняті рубежі оборони в районі ВЕРБОВЕ, СОСНІВКА, Полтавської громади, Полтавського району, Полтавської області, не допускають раптових дії противника на лінії бойового зіткнення з противником в першому ешелоні оборони:
[37] на ПВ «БЕРЕГ»:
[38] солдат ОРЛЕНКО Максим Ігорович;
[39] солдат ПЕТРЕНКО Віталій Олегович;

Query: "солдат ОРЛЕНКО Максим Ігорович"
{"found": true, "context_paragraph_indices": [36, 37], "target_paragraph_index": 38, "redactions": []}
(Paragraph 39 is a different person on their own paragraph — never selected, never redacted.)

--- EXAMPLE 2: target deep in a list, with other people's own paragraphs between context and target ---
[89] на виконання БР командира 7 обр (на бмп) 2 боп 15 обр «СОКІЛ» №БР47/Б3/7Р/ДСК від 15.02.26, з метою швидкого реагування ...
[90] молодший сержант КОВАЛЬЧУК Роман Андрійович;
[91] сержант ЮЩЕНКО Тарас Павлович;
[92] старший солдат ДЕМЧЕНКО Ігор Васильович;
[93] солдат ОРЛЕНКО Богдан Юрійович;
[94] солдат МАЛЬЦЕВА Ірина Василівна;

Query: "солдат ОРЛЕНКО Богдан Юрійович"
{"found": true, "context_paragraph_indices": [89], "target_paragraph_index": 93, "redactions": []}
(Paragraphs 90-92 and 94 are other people, each on their own paragraph — none selected, none redacted.)

--- EXAMPLE 3: two people share the SAME paragraph — the only case redactions is used ---
[55] з метою вивчення реального стану справ ... проводили роботу: головний сержант 3 корпусу НГУ «СОКІЛ» майстер-сержант БОНДАРЕНКО Сергій Миколайович, водій ... солдат ЛИТВИНЕНКО Андрій Іванович (згідно БР ... від 10.02.2026).

Query: "солдат ЛИТВИНЕНКО Андрій Іванович"
{"found": true, "context_paragraph_indices": [], "target_paragraph_index": 55, "redactions": ["головний сержант 3 корпусу НГУ «СОКІЛ» майстер-сержант БОНДАРЕНКО Сергій Миколайович, "]}
(БОНДАРЕНКО shares the exact same paragraph/sentence as the target, so his text must be redacted.)"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "context_paragraph_indices": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "target_paragraph_index": {"type": "integer"},
        "redactions": {
            "type": "array",
            "items": {"type": "string"},
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
