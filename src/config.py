"""Runtime settings for the extraction pipeline."""

COMBAT_LOG_DIR = "journals"  # directory of daily combat log .docx files

# When the full name (surname + first name + patronymic) occurs verbatim in
# more than one place in a day's text -- a genuine ambiguity, e.g. two
# identically-named people -- which occurrence to use. "first" or "last".
FULL_NAME_AMBIGUITY_STRATEGY = "first"
