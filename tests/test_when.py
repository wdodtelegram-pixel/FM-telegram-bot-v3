import datetime

import pytest

from core.when import parse_range, parse_when, quick_range

NOW = datetime.datetime(2026, 11, 20, 15, 45)
D = datetime.datetime


@pytest.mark.parametrize('text,expected', [
    ('now', NOW),
    ('14:30', D(2026, 11, 20, 14, 30)),
    ('yesterday 14:30', D(2026, 11, 19, 14, 30)),
    ('yesterday', D(2026, 11, 19, 15, 45)),
    ('25 Nov', D(2026, 11, 25)),
    ('25 November 2026 09:00', D(2026, 11, 25, 9, 0)),
    ('25/11', D(2026, 11, 25)),
    ('25/11/2026 08:15', D(2026, 11, 25, 8, 15)),
    ('2026-11-25 17:30', D(2026, 11, 25, 17, 30)),
    ('Nov 3', D(2026, 11, 3)),
    ('3rd dec', D(2026, 12, 3)),
    ('25/11/26', D(2026, 11, 25)),
])
def test_parse_when(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize('text', ['', 'banana', '31/02', '25:00', '14:75', 'soon', '99 Nov'])
def test_parse_when_rejects_what_it_cannot_read(text):
    assert parse_when(text, NOW) is None


def test_parse_range_single_day_and_span():
    day = parse_range('25 Nov', NOW.date())
    assert day == (D(2026, 11, 25, 0, 0), D(2026, 11, 25, 23, 59, 59))
    span = parse_range('25/11 - 30/11', NOW.date())
    assert span == (D(2026, 11, 25), D(2026, 11, 30, 23, 59, 59))
    assert parse_range('25 Nov to 27 Nov', NOW.date())[1].day == 27


def test_parse_range_rejects_backwards_or_unreadable():
    assert parse_range('30/11 - 25/11', NOW.date()) is None
    assert parse_range('nonsense', NOW.date()) is None
    assert parse_range('', NOW.date()) is None


def test_quick_ranges():
    t = NOW.date()
    assert quick_range('today', t) == (D(2026, 11, 20), D(2026, 11, 20, 23, 59, 59))
    assert quick_range('tomorrow', t)[0] == D(2026, 11, 21)
    s, e = quick_range('week', t)
    assert (e.date() - s.date()).days == 6
    with pytest.raises(ValueError):
        quick_range('fortnight', t)
