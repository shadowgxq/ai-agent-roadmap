from src.metrics import summarize


def test_old_call_keeps_the_original_shape():
    assert summarize([2, 3]) == {"total": 5}


def test_new_flag_adds_count_without_removing_total():
    assert summarize([2, 3], include_count=True) == {"total": 5, "count": 2}


def test_empty_values_have_zero_count():
    assert summarize([], include_count=True) == {"total": 0, "count": 0}
