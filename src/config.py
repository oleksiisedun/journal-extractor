"""Runtime settings for the extraction pipeline."""

JOURNAL_DIR = "journals"  # directory of daily journal .docx files
TEMPLATE_PATH = "templates/1.docx"  # extract .docx template with {placeholders}
OUTPUT_DIR = "output"  # generated extract .docx files land here

# When the full name (surname + first name + patronymic) occurs verbatim in
# more than one place in a day's text -- a genuine ambiguity, e.g. two
# identically-named people -- which occurrence to use. "first" or "last".
FULL_NAME_AMBIGUITY_STRATEGY = "first"
