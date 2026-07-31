from datetime import date

import pytest

from railwatch.ktmb import format_ktmb_date, seat_is_ordinary


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("/Seat/Icon?id=Standard", True),
        ("/Seat/Icon?id=StdA", True),
        ("/Seat/Icon?id=StandardOKU", False),
        ("/Seat/Icon?id=Business", False),
        ("/Seat/Icon?id=VIP", False),
        (None, False),
    ],
)
def test_ordinary_seat_filter(src: str | None, expected: bool) -> None:
    assert seat_is_ordinary(src) is expected


def test_ktmb_date_format_is_locale_independent() -> None:
    assert format_ktmb_date(date(2026, 8, 3)) == "03 Aug 2026"
