from datariver.domain.common import uuid7


def test_uuid7_has_expected_version_and_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"
