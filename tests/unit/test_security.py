import time

import jwt
import pytest

from app.core.security import (
    hash_password,
    verify_password,
    encrypt_payload,
    decrypt_payload,
    KEY,
    ALGORITHM,
)


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
        pytest.param("correcthorsebatterystaple", "wrong", id="completely_wrong"),
        pytest.param("short", "Short", id="case_sensitive"),
        pytest.param("with spaces", "withspaces", id="spaces_matter"),
        pytest.param("notempty", "", id="empty_vs_nonempty"),
    ],
)
def test_verify_wrong_password(password, wrong):
    assert verify_password(wrong, hash_password(password)) is False


def test_encrypt_payload_is_valid_jwt():
    token = encrypt_payload({"user_id": "alice", "role": "admin"})
    decoded = jwt.decode(token, key=KEY, algorithms=[ALGORITHM])
    assert decoded["user_id"] == "alice"
    assert decoded["role"] == "admin"


def test_encrypt_payload_includes_exp():
    token = encrypt_payload({"user_id": "alice", "role": "admin"})
    decoded = jwt.decode(token, key=KEY, algorithms=[ALGORITHM])
    assert "exp" in decoded
    assert decoded["exp"] > time.time()


def test_decrypt_payload_returns_claims():
    token = encrypt_payload({"user_id": "bob", "role": "user"})
    claims = decrypt_payload(token)
    assert claims["user_id"] == "bob"
    assert claims["role"] == "user"
