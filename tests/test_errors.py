import pytest

from bugbite import errors
from bugbite.errors import ALL_CODES, InputError


def test_codes_are_stable():
    assert ALL_CODES == {
        "invalid_url",
        "not_github",
        "not_an_issue_url",
        "not_a_repo_url",
        "repo_mismatch",
        "empty_input",
    }


@pytest.mark.parametrize("code", sorted(ALL_CODES))
def test_error_carries_code_and_message(code):
    err = InputError(code, "something readable")
    assert err.code == code
    assert err.message == "something readable"
    assert str(err) == "something readable"


def test_unknown_code_rejected():
    with pytest.raises(ValueError):
        InputError("made_up", "x")


def test_empty_message_rejected():
    with pytest.raises(ValueError):
        InputError(errors.INVALID_URL, "")
