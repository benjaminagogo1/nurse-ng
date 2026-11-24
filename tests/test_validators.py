"""Regression coverage for validators; see tests/README.md for isolation and runner setup."""

import pytest

from app.core.validators import normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+234 801 234 5678", "+2348012345678"),
        ("08012345678", "+2348012345678"),
        ("002348012345678", "+2348012345678"),
        ("2348012345678", "+2348012345678"),
        ("+234-801-(234)-5678", "+2348012345678"),
        ("", ""),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
