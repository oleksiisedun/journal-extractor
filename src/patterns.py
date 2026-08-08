"""Regex patterns shared across modules that would otherwise create a
circular import (assembly.py <-> time_extraction.py both need
ORDER_REF_PATTERN, and assembly.py separately imports from
time_extraction.py)."""

import re

# Optional space after № tolerated — real files are inconsistent about it
# (e.g. '№БР42/Б3/7Р/ДСК' vs '№ БР91/Б3/12Р/ДСК'). Requires a '/' somewhere
# in the token -- every real order reference has segments separated by '/'
# (.../Б3/.../ДСК), while plain "№" numbering that ISN'T an order (e.g. a
# group label 'Група №2', or the document's own header number '№ 12') never
# does. Without this, 'Група №2' was matching as if it were an order
# reference and made find_preceding_order_paragraph() (prefilter.py) stop
# there instead of walking back further to the real governing order -- see
# CLAUDE.md bug log.
ORDER_REF_PATTERN = re.compile(r"№\s?(?=\S*/)\S+")
