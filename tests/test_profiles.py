"""Regression coverage for profiles; see tests/README.md for isolation and runner setup."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.profile import (
    ClaimStatus,
    ClaimType,
    CredentialClaim,
    FieldVisibility,
    NurseProfile,
    ProfessionalStatus,
    ProfileStatus,
    Visibility,
)
from app.models.user import User
from app.services.profiles import field_visibility, public_field_names


@pytest.fixture
def user(db_session):
    user = User(phone="+2348012345678", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def profile(db_session, user):
    profile = NurseProfile(user=user)
    db_session.add(profile)
    db_session.commit()
    return profile


def test_one_profile_per_user(db_session, user, profile):
    db_session.add(NurseProfile(user=user))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_public_id_is_uuid7_and_distinct_from_primary_key(profile):
    assert profile.public_id != profile.id
    assert profile.public_id.version == 7


def test_profile_defaults_are_private_and_draft(profile):
    assert profile.discoverable is False
    assert profile.status == ProfileStatus.DRAFT
    assert profile.professional_status == ProfessionalStatus.STUDENT


def test_claim_defaults_to_self_declared_and_private(db_session, profile):
    claim = CredentialClaim(
        profile=profile,
        type=ClaimType.REGISTRATION,
        value="RN-123",
    )
    db_session.add(claim)
    db_session.commit()

    assert claim.status == ClaimStatus.SELF_DECLARED
    assert claim.visibility == Visibility.PRIVATE


def test_field_visibility_defaults_to_private(db_session, profile):
    assert field_visibility(db_session, profile, "bio") == Visibility.PRIVATE


def test_field_visibility_row_overrides_default(db_session, profile):
    db_session.add(
        FieldVisibility(
            profile=profile,
            field="bio",
            visibility=Visibility.PUBLIC,
        )
    )
    db_session.commit()

    assert field_visibility(db_session, profile, "bio") == Visibility.PUBLIC
    assert public_field_names(db_session, profile) == {"bio"}


def test_field_visibility_is_unique_per_profile(db_session, profile):
    db_session.add(FieldVisibility(profile=profile, field="bio"))
    db_session.commit()

    db_session.add(FieldVisibility(profile=profile, field="bio"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
