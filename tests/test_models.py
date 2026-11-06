import datetime as dt

import pytest
from pydantic import ValidationError

from centerfield_visitor_mcp import models
from centerfield_visitor_mcp.models import VisitorIn, normalize_mobile


@pytest.mark.parametrize(
    "raw, expected",
    [("8:00", "08:00"), ("08:00", "08:00"), ("20:00", "20:00"), ("14:00:00", "14:00"), ("9:30", "09:30")],
)
def test_time_accepted_and_normalized(visitor_kwargs, raw, expected):
    v = VisitorIn(**{**visitor_kwargs, "visit_time": raw})
    assert v.visit_time == expected


@pytest.mark.parametrize("raw", ["20:30", "07:30", "14:15", "1400", "25:00", "ab:cd", "", "14:00:30"])
def test_time_rejected(visitor_kwargs, raw):
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, "visit_time": raw})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("010-1234-5678", "01012345678"),
        ("010 1234 5678", "01012345678"),
        ("010.1234.5678", "01012345678"),
        ("(010) 1234-5678", "01012345678"),
        ("+82 10-1234-5678", "01012345678"),
        ("+82-10-1234-5678", "01012345678"),
        ("+82(0)10-1234-5678", "01012345678"),
        ("821012345678", "01012345678"),
        ("01112345678", "01112345678"),
        ("0101234567", "0101234567"),  # 10-digit legacy form
    ],
)
def test_mobile_normalized(raw, expected):
    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", "0212345678", "010123456", "010123456789", "12345678901"])
def test_mobile_rejected(visitor_kwargs, raw):
    with pytest.raises(ValidationError) as exc:
        VisitorIn(**{**visitor_kwargs, "visitor_mobile": raw})
    assert "visitor_mobile" in str(exc.value)


@pytest.mark.parametrize("raw", ["a@b", "홍길동", "hong@", "@example.com"])
def test_email_rejected(visitor_kwargs, raw):
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, "visitor_email": raw})


def test_floor_literal(visitor_kwargs):
    assert VisitorIn(**visitor_kwargs, floor="18").floor == "18"
    with pytest.raises(ValidationError):
        VisitorIn(**visitor_kwargs, floor="13")


def test_floor_defaults_to_settings(visitor_kwargs):
    assert VisitorIn(**visitor_kwargs).floor in ("12", "18")


@pytest.mark.parametrize("purpose", ["meeting", "visit_business", "interview", "tour", "construction", "others"])
def test_purpose_accepted(visitor_kwargs, purpose):
    assert VisitorIn(**visitor_kwargs, visit_purpose=purpose).visit_purpose == purpose


def test_purpose_rejected(visitor_kwargs):
    with pytest.raises(ValidationError):
        VisitorIn(**visitor_kwargs, visit_purpose="방문")


@pytest.mark.parametrize("raw", ["2026/10/15", "10-15", "15.10.2026", "tomorrow"])
def test_date_format_rejected(visitor_kwargs, raw):
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, "visit_date": raw})


def _pin(monkeypatch, when: dt.datetime) -> None:
    monkeypatch.setattr(models, "clock", lambda: when)


SEOUL = models.SITE_TZ
UTC = dt.timezone.utc


def test_past_date_rejected(visitor_kwargs, monkeypatch):
    _pin(monkeypatch, dt.datetime(2026, 11, 6, 9, 0, tzinfo=SEOUL))
    with pytest.raises(ValidationError) as exc:
        VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-05"})
    assert "in the past" in str(exc.value)


def test_today_later_time_accepted(visitor_kwargs, monkeypatch):
    _pin(monkeypatch, dt.datetime(2026, 11, 6, 9, 59, tzinfo=SEOUL))
    v = VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-06", "visit_time": "10:00"})
    assert v.visit_date == dt.date(2026, 11, 6)


def test_today_exact_start_accepted(visitor_kwargs, monkeypatch):
    _pin(monkeypatch, dt.datetime(2026, 11, 6, 10, 0, 0, tzinfo=SEOUL))
    assert VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-06", "visit_time": "10:00"}).visit_time == "10:00"


@pytest.mark.parametrize("now", [dt.datetime(2026, 11, 6, 10, 0, 1), dt.datetime(2026, 11, 6, 15, 7)])
def test_today_time_already_passed_rejected(visitor_kwargs, monkeypatch, now):
    _pin(monkeypatch, now.replace(tzinfo=SEOUL))
    with pytest.raises(ValidationError) as exc:
        VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-06", "visit_time": "10:00"})
    assert "already passed (Asia/Seoul)" in str(exc.value)


def test_utc_host_late_evening_uses_seoul_date(visitor_kwargs, monkeypatch):
    """At 2026-11-05 16:00 UTC it is already 2026-11-06 01:00 in Seoul: the 5th is in the past."""
    _pin(monkeypatch, dt.datetime(2026, 11, 5, 16, 0, tzinfo=UTC))
    with pytest.raises(ValidationError) as exc:
        VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-05", "visit_time": "20:00"})
    assert "in the past (Asia/Seoul)" in str(exc.value)
    assert VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-06", "visit_time": "08:00"})


def test_us_host_morning_uses_seoul_time(visitor_kwargs, monkeypatch):
    """09:00 in US Pacific (UTC-8) on Nov 5 is 02:00 Nov 6 in Seoul; a Nov 5 visit has passed."""
    pacific = dt.timezone(dt.timedelta(hours=-8))
    _pin(monkeypatch, dt.datetime(2026, 11, 5, 9, 0, tzinfo=pacific))
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-05", "visit_time": "18:00"})


def test_ahead_host_does_not_reject_seoul_today(visitor_kwargs, monkeypatch):
    """A host in UTC+14 already on Nov 7 must not reject a Seoul Nov 6 afternoon visit."""
    kiritimati = dt.timezone(dt.timedelta(hours=14))
    _pin(monkeypatch, dt.datetime(2026, 11, 7, 0, 0, tzinfo=kiritimati))  # = 2026-11-06 19:00 Seoul
    assert VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-06", "visit_time": "20:00"}).visit_time == "20:00"
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, "visit_date": "2026-11-06", "visit_time": "18:30"})


def test_site_now_is_seoul_and_default_clock_is_aware():
    now = models.site_now()
    assert now.tzinfo is not None and now.utcoffset() == dt.timedelta(hours=9)
    assert models.clock is models._system_clock


@pytest.mark.parametrize("field", ["visitor_name", "visitor_company_name"])
def test_blank_name_or_company_rejected(visitor_kwargs, field):
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, field: "   "})


def test_name_stripped(visitor_kwargs):
    assert VisitorIn(**{**visitor_kwargs, "visitor_name": "  홍길동 "}).visitor_name == "홍길동"


def test_dedupe_key(visitor_kwargs):
    v = VisitorIn(**visitor_kwargs)
    assert v.dedupe_key() == ("01012345678", visitor_kwargs["visit_date"], "10:00")
