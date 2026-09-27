from text_wrap import estimate_wrapped_line_count


def test_empty_text_is_one_blank_line():
    assert estimate_wrapped_line_count("", 10.0, 200.0, 200.0) == 1


def test_short_text_fits_on_one_line():
    assert estimate_wrapped_line_count("Короткий текст.", 10.0, 500.0, 500.0) == 1


def test_long_text_wraps_to_multiple_lines():
    long_text = " ".join(["слово"] * 50)
    lines = estimate_wrapped_line_count(long_text, 10.0, 100.0, 100.0)
    assert lines > 1


def test_narrower_first_line_wraps_sooner_than_continuation():
    text = " ".join(["слово"] * 20)
    narrow_first = estimate_wrapped_line_count(text, 10.0, 20.0, 500.0)
    wide_first = estimate_wrapped_line_count(text, 10.0, 500.0, 500.0)
    assert narrow_first > wide_first


def test_single_word_wider_than_line_still_gets_one_line_not_infinite_loop():
    # Word doesn't break mid-word without hyphenation -- a word wider than
    # its available width must still be placed alone on that line rather
    # than looping forever trying to fit it.
    huge_word = "а" * 500
    lines = estimate_wrapped_line_count(huge_word, 10.0, 1.0, 1.0)
    assert lines == 1
