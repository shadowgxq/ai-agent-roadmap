from src.ranking import rank_scores


def test_scores_rank_highest_first():
    assert rank_scores([("Ada", 80), ("Lin", 95), ("Mo", 88)]) == [
        ("Lin", 95),
        ("Mo", 88),
        ("Ada", 80),
    ]


def test_equal_scores_keep_input_order():
    assert rank_scores([("first", 90), ("second", 90), ("third", 80)]) == [
        ("first", 90),
        ("second", 90),
        ("third", 80),
    ]

