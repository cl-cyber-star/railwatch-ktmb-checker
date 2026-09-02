from datetime import date

import pytest

from railwatch.ktmb import (
    coach_from_metadata,
    format_ktmb_date,
    seat_is_ordinary,
    seat_number_from_metadata,
)


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


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"seatNo": "7A", "seatType": "Standard"}, "7A"),
        ({"seatData": '{"SeatNumber":"B12","SeatType":"Standard"}'}, "B12"),
        ({"ariaLabel": "Seat 9C"}, "9C"),
        ({"seatData": {"SeatName": "14"}}, "14"),
        ({"seatData": "Standard", "title": "Available"}, None),
    ],
)
def test_seat_number_from_metadata(metadata: object, expected: str | None) -> None:
    assert seat_number_from_metadata(metadata) == expected


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"coachNo": "A"}, "A"),
        ({"seatData": '{"CoachNumber":"C2","SeatNumber":"7A"}'}, "C2"),
        ({"coachContext": [{"text": "Coach B"}]}, "B"),
        ({"attributes": {"data-carriage": "3"}}, "3"),
        ({"seatNo": "7A", "seatType": "Standard"}, None),
    ],
)
def test_coach_from_metadata(metadata: object, expected: str | None) -> None:
    assert coach_from_metadata(metadata) == expected


def test_numeric_coach_is_not_mistaken_for_seat_number() -> None:
    metadata = {"coachNo": "3", "seatNo": "7A"}
    assert seat_number_from_metadata(metadata) == "7A"
    assert coach_from_metadata(metadata) == "3"
