import datetime as dt

import pytest
from pydantic import ValidationError

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


def test_past_date_rejected(visitor_kwargs):
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError) as exc:
        VisitorIn(**{**visitor_kwargs, "visit_date": yesterday})
    assert "in the past" in str(exc.value)


def test_today_accepted(visitor_kwargs):
    assert VisitorIn(**{**visitor_kwargs, "visit_date": dt.date.today().isoformat()}).visit_date == dt.date.today()


@pytest.mark.parametrize("field", ["visitor_name", "visitor_company_name"])
def test_blank_name_or_company_rejected(visitor_kwargs, field):
    with pytest.raises(ValidationError):
        VisitorIn(**{**visitor_kwargs, field: "   "})


def test_name_stripped(visitor_kwargs):
    assert VisitorIn(**{**visitor_kwargs, "visitor_name": "  홍길동 "}).visitor_name == "홍길동"


def test_dedupe_key(visitor_kwargs):
    v = VisitorIn(**visitor_kwargs)
    assert v.dedupe_key() == ("01012345678", visitor_kwargs["visit_date"], "10:00")
