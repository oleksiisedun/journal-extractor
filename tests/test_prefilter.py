from prefilter import (
    extract_full_name,
    extract_surname,
    find_preceding_label_header,
    find_preceding_order_paragraph,
)


def test_extract_full_name_returns_surname_first_patronymic():
    assert (
        extract_full_name("молодший сержант ПЕТРЕНКО Іван Миколайович")
        == "ПЕТРЕНКО Іван Миколайович"
    )


def test_extract_surname_is_the_first_token():
    assert extract_surname("солдат ШЕВЧЕНКО Олег Васильович") == "ШЕВЧЕНКО"


def test_find_preceding_order_paragraph_reaches_far_outside_any_fixed_window():
    # bug-log item 1: a single order can head a long list, so the
    # governing order paragraph can sit dozens of paragraphs before the
    # target -- must not stop early just because it's far away.
    # paragraphs list must cover every index up to the target -- the
    # finder indexes by paragraph number, not by position in the list.
    paragraphs = (
        [(i, "filler") for i in range(10)]
        + [(10, "на виконання БОЙОВОГО НАКАЗУ №БН1/Б3/ДСК")]
        + [(i, f"ПВ «ГРУПА-{i}»") for i in range(11, 50)]
        + [(50, "ІВАНЕНКО Іван Іванович заступив на пост.")]
    )
    assert find_preceding_order_paragraph(paragraphs, anchor_index=50) == 10


def test_find_preceding_order_paragraph_ignores_bare_list_numbering():
    # bug-log item 2: plain "№2" group numbering (no "/") must never be
    # mistaken for a governing order reference.
    paragraphs = [
        (0, "Група №2 за координатами (37U CR 15093 59641)"),
        (1, "ХОМЕНКО Дмитро Юрійович заступив на пост."),
    ]
    assert find_preceding_order_paragraph(paragraphs, anchor_index=1) is None


def test_find_preceding_label_header_skips_another_persons_paragraph():
    # bug-log item 4: the target isn't always the first person listed
    # under their label -- a fellow list member's own paragraph sits
    # between the label and the target and must be skipped, not mistaken
    # for the label itself.
    paragraphs = [
        (1, "Пост повітряного прикриття № 2 (37U CR 15021 60370):"),
        (2, "ОГУЛА Максим Олексійович заступив на пост."),
        (3, "ЧЕРЕДНІЧЕНКО Олександр Іванович заступив на пост."),
    ]
    assert find_preceding_label_header(paragraphs, anchor_index=3, lower_bound=0) == 1


def test_find_preceding_label_header_trusts_guillemets_and_colon():
    paragraphs = [
        (1, "на ПВ «БЕРЕГ»:"),
        (2, "ІВАНЕНКО Іван Іванович заступив на пост."),
    ]
    assert find_preceding_label_header(paragraphs, anchor_index=2, lower_bound=0) == 1


def test_find_preceding_label_header_stops_rather_than_guess_past_a_skip():
    # the weak "no bare surname" fallback signal is only trusted when
    # directly adjacent to the target -- once a person's own paragraph has
    # already been skipped, a further-back line with neither strong signal
    # must stop the search (None) instead of guessing.
    paragraphs = [
        (1, "Довільний текст без жодного сигналу."),
        (2, "ОГУЛА Максим Олексійович заступив на пост."),
        (3, "ЧЕРЕДНІЧЕНКО Олександр Іванович заступив на пост."),
    ]
    assert (
        find_preceding_label_header(paragraphs, anchor_index=3, lower_bound=0) is None
    )
