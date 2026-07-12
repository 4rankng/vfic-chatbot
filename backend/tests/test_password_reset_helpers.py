"""Characterization of the pure OTP helpers in password_reset_service.

The DB-bound lifecycle (issue / expire / consume / attempt-counting) is
integration-level by repo convention (no live DB in this suite), but the
security-sensitive pure helpers are pinned here: HMAC OTP hashing, six-digit
generation, email normalization, and the error type callers catch.
"""

from app.services import password_reset_service as prs


def test_normalize_email_strips_and_lowercases():
    assert prs._normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_hash_otp_is_deterministic_and_sensitive_to_otp_and_email():
    a = prs._hash_otp("user@example.com", "123456")
    b = prs._hash_otp("user@example.com", "123456")
    same_otp_diff_email = prs._hash_otp("other@example.com", "123456")
    same_email_diff_otp = prs._hash_otp("user@example.com", "654321")

    assert a == b  # deterministic for the same email + OTP
    assert a != same_otp_diff_email  # the email binds the hash (can't replay across accounts)
    assert a != same_email_diff_otp  # the OTP must affect the hash
    assert len(a) == 64  # sha256 hex digest
    assert all(ch in "0123456789abcdef" for ch in a)


def test_new_otp_is_a_six_digit_zero_padded_numeric_string():
    seen = set()
    for _ in range(500):
        otp = prs._new_otp()
        assert len(otp) == 6
        assert otp.isdigit()
        assert 0 <= int(otp) <= 999_999
        seen.add(otp)
    # Across 500 draws of a 10^6 space, collisions should be rare — sanity that
    # the OTP isn't degenerate (e.g. always "000000").
    assert len(seen) > 400


def test_password_reset_error_is_a_value_error_subclass():
    # Callers' ``except ValueError`` must still catch it.
    assert issubclass(prs.PasswordResetError, ValueError)
    assert str(prs.PasswordResetError("boom")) == "boom"
