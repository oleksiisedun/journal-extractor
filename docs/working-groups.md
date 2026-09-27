# `--working-groups` mode (alternate entry path)

`generate_extract.py --working-groups <file.docx> [--year YYYY]` is a
structurally different mode from the per-person pipeline in `CLAUDE.md`:
instead of one extract per *person* across many days, it produces one
extract per *distinct reporting item ("block") text, once punctuation
marks are ignored* found in a single month-spanning "РОБОЧІ ГРУПИ" (working
groups) report — a `.docx` written as flowing body paragraphs (no table,
unlike the daily journals). A recurring item (same governing order, same
body text modulo incidental punctuation — e.g. a trailing `.` one day vs
`;` another, or a `,` vs `;` mid-sentence) collapses into one file with
every occurrence's date+time stacked, instead of one near-duplicate file
per day — **every occurrence of that same item goes into the same file
regardless of calendar gaps between occurrences** (e.g. a different person
covers the same duty for a stretch of days, then the original person's
identical-text entry resumes later in the month): each occurrence keeps
its own dated entry rather than being folded into a single "з ... по ..."
span, so a gap day simply has no entry and nothing is misrepresented — see
bug case below. Each block's own text still renders byte-verbatim in the
output — only the *grouping decision* ignores punctuation, per
`working_groups.py`'s `_normalize_for_grouping()`.

`working_groups.py`'s `parse_working_group_blocks()` walks the
document's paragraphs deterministically: a `DD.MM` line is a date-header
that supplies the fallback date for items that follow; each reporting
item is recognized by `ITEM_START_PATTERN` (an optional leading
`DD.MM.YYYY` override, then an `HH:MM-HH:MM`-shaped time range, both as
named regex groups) and carries its remaining text verbatim (the matched
date-override/time-range prefix is split off into the block's own `"time"`
field rather than left inline — it's structural item metadata, not
narrative content, and leaving it inline would (a) defeat byte-identical
text comparison between otherwise-identical days and (b) leave the
rendered `{дата}` column with nothing to show, since `time` used to be
discarded entirely) plus any order numbers found via
`WORKING_GROUP_ORDER_REF_PATTERN` (a working-groups-specific pattern —
deliberately not `patterns.ORDER_REF_PATTERN` — tolerant of `БР`-prefixed
and space-variant order tokens). A paragraph matching neither shape is
skipped with a loud warning, never silently dropped.

A header-derived date (no inline `DD.MM.YYYY` on the item itself) pairs
the header's day/month with `--year` if given, else the year the script
happens to be *run* in (`date.today().year`) — a fallback that's only
correct when running in the same year the report covers. **Known
limitation, left unfixed by design**: a report whose own date-header
sections straddle a year boundary (e.g. late December into early January
within one file) can't be represented by one flat `--year` value; this
wasn't judged worth solving since real working-groups reports each cover a
single calendar month and so never actually straddle a year boundary
themselves — `--year` only exists for the case where the report covers one
year but the script runs in a different one (e.g. processing a December
report in January).

`generate_extract.py`'s `generate_working_groups()` sorts blocks
chronologically, applies the same coordinate/location stripping and
trailing `;` → `.` fix as the main pipeline to each block's text, then
groups them via `working_groups.py`'s `group_consecutive_identical_blocks()`
— unlike `merge.merge_consecutive_entries()`'s adjacency-walk (which
requires exactly-consecutive calendar dates and always breaks a run on a
gap), this groups **every occurrence of a given normalized text into one
group, regardless of calendar gaps** between occurrences: it buckets all
blocks by `_normalize_for_grouping()`'s punctuation-insensitive key first,
then treats each bucket as one whole group, no further date-based
splitting. This is safe (unlike folding into a single "з ... по ..." span)
because every block stays its own dated entry within the group instead of
collapsing into one line — a gap date simply produces no entry, so nothing
implies continuous presence across it. Kept as a separate function from
`merge_consecutive_entries()` rather than adding a mode flag to it, since
the two output shapes are different enough (fold-into-a-range vs.
one-group-per-distinct-text-with-every-occurrence-kept-separate) that
sharing one function would trade a clear function for a branchy one. Each
group is rendered through the same multi-entry `render_extract()` template
path the per-person pipeline already uses to stack a person's multiple
found days in one document — no changes needed there. Output filenames
come from `build_working_group_filename()`, given the group's date ranges
from `compute_date_ranges()` (partitions the group's dates into runs of
chronologically-consecutive calendar days — since a group's occurrences
can now be non-contiguous, there can be more than one such run) —
`WORKING_GROUP_UNIT_PREFIX` in `config.py` (e.g. `"3 боп"`) + the date
part + every distinct order id across the group, unioned via
`union_order_ids()` in first-appearance order. The date part is `"за
DD.MM.YYYY"` for a single day or `"з DD.MM.YYYY по DD.MM.YYYY"` for one
contiguous run (same phrasing `render.py`'s `_format_date_lines()` uses
for a merged multi-day {дата} entry) when the group has exactly one date
range; when it has more than one (the gapped case), each range instead
renders compactly as `"DD.MM.YYYY-DD.MM.YYYY"` (or bare `"DD.MM.YYYY"` for
a lone day within the list), space-separated, e.g. `"02.07.2026-05.07.2026
10.07.2026-11.07.2026 20.07.2026-31.07.2026"` — so the filename itself
never implies a continuous span the source doesn't show. Order ids are
always displayed `БР`-prefixed (e.g. `БР1927`) regardless of which
spelling a given occurrence used in the source — the same order is
written both `№1927/...` and `№БР 1927/...` in real documents, so
`_extract_order_ids()` normalizes the *display* token while still deduping
on the bare digits, rather than transcribing whichever spelling happened
to be matched first.
`_dedupe_output_path()` appends `" (2)"`, `" (3)"`, ... if two groups would
otherwise collide on the same filename. Legacy binary `.doc` input is
rejected up front (checked by file signature, not extension).

**Bug case (fixed): a recurring item with a real coverage gap used to
split into multiple near-duplicate files instead of one.** Real case
(`journals/РОБОЧІ ГРУПИ 01.07-31.07.docx`, order `№БР1927/(S-3) ВКП/ДСК`,
БАЙЛИМ Іван Сергійович's identical-text entry): he covered this duty
02.07–05.07, someone else covered it 06.07–19.07, then he resumed
20.07–31.07 with byte-identical (post-normalization) text. Before the fix,
`group_consecutive_identical_blocks()` split same-text occurrences into a
new group every time a date gap appeared — same "gap breaks a run" rule as
`merge.merge_consecutive_entries()` — producing three separate,
near-duplicate output files for what a human reviewer would recognize as
one recurring assignment. Verified against the real source file that the
gap dates (06.07–19.07) genuinely have no matching-text block (a different
person's paragraph covers those dates instead), ruling out a parsing miss.
Fixed by removing the date-gap split entirely for this mode: grouping is
now purely by normalized text, and `compute_date_ranges()` +
`build_working_group_filename()`'s multi-range format make the resulting
single file's filename correctly show the three separate spans instead of
falsely claiming one continuous run.
