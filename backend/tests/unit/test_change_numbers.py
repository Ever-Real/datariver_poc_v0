from datetime import UTC, datetime

import pytest

from datariver.application.change_numbers import change_request_number


def test_issues_the_legacy_recognizable_system_date_random4_number() -> None:
    assert (
        change_request_number(
            "Fab System / A",
            occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
            random4="7f2a",
        )
        == "CR-FAB-SYSTEM-A-260717-7F2A"
    )


def test_falls_back_to_platform_name_and_rejects_an_invalid_suffix() -> None:
    assert (
        change_request_number(
            None,
            occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
            random4="AB12",
        )
        == "CR-DATARIVER-260717-AB12"
    )
    with pytest.raises(ValueError, match="random4"):
        change_request_number("fab", random4="unsafe-")
