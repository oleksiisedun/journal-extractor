"""Regex patterns shared across modules that would otherwise create a
circular import (assembly.py <-> time_extraction.py both need
ORDER_REF_PATTERN, and assembly.py separately imports from
time_extraction.py)."""

import re

# Optional space after № tolerated — real files are inconsistent about it
# (e.g. '№БР42/Б3/7Р/ДСК' vs '№ БР91/Б3/12Р/ДСК').
ORDER_REF_PATTERN = re.compile(r"№\s?\S+")
