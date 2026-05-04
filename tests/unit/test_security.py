import pytest

from app.core.security import hash_password, verify_password


@pytest.mark.parametrize(
    "password", ["correcthorsebatterystaple", "short", "with spaces", ""]
)
def test_hash_returns_non_plaintext_string(password):
    hashed = hash_password(password)
    assert isinstance(hashed, str)
    assert hashed != password


def test_hash_is_non_deterministic():
    assert hash_password("password") != hash_password("password")


@pytest.mark.parametrize(
    "password", ["correcthorsebatterystaple", "short", "with spaces", ""]
)
def test_verify_correct_password(password):
    assert verify_password(password, hash_password(password)) is True


@pytest.mark.parametrize(
    "password,wrong",
    [
        ("correcthorsebatterystaple", "wrong"),
        ("short", "Short"),
        ("with spaces", "withspaces"),
        ("notempty", ""),
    ],
)
def test_verify_wrong_password(password, wrong):
    assert verify_password(wrong, hash_password(password)) is False
