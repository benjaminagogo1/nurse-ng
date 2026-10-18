import uuid

from app.core.uuid import uuid7


def test_uuid7_has_version_and_variant():
    value = uuid7()

    assert isinstance(value, uuid.UUID)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_unique_across_many_calls():
    assert len({uuid7() for _ in range(1000)}) == 1000
