"""The comparison is the measuring instrument of the evaluation, so it has its own tests."""

from run_eval import same_result


def test_row_order_and_number_formatting_do_not_matter() -> None:
    reference = [["Home", "3301"], ["Office", "3698.00"]]
    assert same_result(reference, [["Office", 3698], ["Home", 3301.004]])


def test_extra_columns_and_another_column_order_are_allowed() -> None:
    reference = [["Kettle Plus", "65188.20"]]
    assert same_result(reference, [[41, 65188.2, "Home", "Kettle Plus"]])


def test_a_different_value_is_wrong() -> None:
    assert not same_result([["Home", "3301"]], [["Home", 3302]])


def test_missing_or_extra_rows_are_wrong() -> None:
    reference = [["a", "1"], ["b", "2"]]
    assert not same_result(reference, [["a", 1]])
    assert not same_result(reference, [["a", 1], ["b", 2], ["c", 3]])


def test_values_must_come_from_the_same_row() -> None:
    reference = [["a", "1"], ["b", "2"]]
    assert not same_result(reference, [["a", 2], ["b", 1]])


def test_an_answer_with_too_few_columns_is_wrong() -> None:
    assert not same_result([["a", "1"]], [["a"]])
