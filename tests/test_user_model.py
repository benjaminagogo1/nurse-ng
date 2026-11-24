"""Regression coverage for user model; see tests/README.md for isolation and runner setup."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user import User, UserStatus


def test_phone_is_normalised_and_id_is_uuid7(db_session):
    user = User(phone="0801 234 5678", hashed_password="x")
    user.set_password("s3cret-pass")

    db_session.add(user)
    db_session.commit()

    assert user.phone == "+2348012345678"
    assert user.id.version == 7
    assert user.status == UserStatus.ACTIVE
    assert user.is_active is True
    assert user.is_staff is False
    assert user.check_password("s3cret-pass")
    assert not user.check_password("wrong")


def test_invalid_phone_is_rejected():
    with pytest.raises(ValueError):
        User(phone="not-a-phone", hashed_password="x")


def test_phone_must_be_unique(db_session):
    db_session.add(User(phone="+2348012345678", hashed_password="x"))
    db_session.commit()

    db_session.add(User(phone="08012345678", hashed_password="x"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_email_domain_is_lowercased():
    user = User(phone="+2348012345678", email="Nurse@Example.COM", hashed_password="x")

    assert user.email == "Nurse@example.com"


def test_empty_email_becomes_null():
    user = User(phone="+2348012345678", email="", hashed_password="x")

    assert user.email is None
