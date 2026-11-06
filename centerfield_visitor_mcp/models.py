from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from .config import settings

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        SITE_TZ = ZoneInfo("Asia/Seoul")
    except ZoneInfoNotFoundError:  # pragma: no cover - hosts without tz data (e.g. Windows w/o tzdata)
        SITE_TZ = timezone(timedelta(hours=9), "Asia/Seoul")
except ImportError:  # pragma: no cover
    SITE_TZ = timezone(timedelta(hours=9), "Asia/Seoul")


def _system_clock() -> datetime:
    return datetime.now(SITE_TZ)


# Test seam: replace with a callable returning an aware datetime to pin "now".
clock: Callable[[], datetime] = _system_clock


def site_now() -> datetime:
    """Current time at the building (Asia/Seoul), independent of the host time zone."""
    return clock().astimezone(SITE_TZ)

VALID_PURPOSES = Literal[
    "visit_business", "meeting", "interview", "tour", "construction", "others"
]

# Korean mobile numbers after normalization: 010/011/016/017/018/019 + 7~8 digits.
_KR_MOBILE_RE = re.compile(r"^01[016789]\d{7,8}$")
_MOBILE_STRIP_RE = re.compile(r"[\s\-\.\(\)]")


def normalize_mobile(raw: str) -> str:
    """Normalize a Korean mobile number to digits only.

    Accepts hyphens/spaces/dots/parentheses, and the international forms
    ``+82 10-1234-5678`` / ``82-10-1234-5678`` / ``+82(0)10...``.
    Raises ValueError when the result is not a Korean mobile number.
    """
    value = _MOBILE_STRIP_RE.sub("", (raw or "").strip())
    if value.startswith("+82"):
        value = "0" + value[3:].lstrip("0")
    elif value.startswith("82") and len(value) >= 12:
        value = "0" + value[2:].lstrip("0")
    if not value:
        raise ValueError("visitor_mobile is required (휴대폰 번호가 비어 있습니다)")
    if not _KR_MOBILE_RE.fullmatch(value):
        raise ValueError(
            "visitor_mobile must be a Korean mobile number, e.g. 01012345678 "
            f"(입력값 형식 오류: {len(value)} chars)"
        )
    return value


class VisitorIn(BaseModel):
    visitor_name: str
    visitor_company_name: str
    visitor_mobile: str
    visitor_email: EmailStr
    visit_date: date
    visit_time: str
    visit_purpose: VALID_PURPOSES = "meeting"
    floor: Literal["12", "18"] = settings.default_floor  # type: ignore[assignment]

    @field_validator("visitor_name", "visitor_company_name")
    @classmethod
    def non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("visitor_mobile")
    @classmethod
    def normalize_mobile_field(cls, v: str) -> str:
        return normalize_mobile(v)

    @field_validator("visit_date")
    @classmethod
    def not_in_past(cls, v: date) -> date:
        if v < site_now().date():
            raise ValueError(f"visit_date {v.isoformat()} is in the past (Asia/Seoul)")
        return v

    @field_validator("visit_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.strip().split(":")
        if len(parts) == 3 and parts[2] in ("0", "00"):
            parts = parts[:2]  # tolerate HH:MM:SS from spreadsheets
        if len(parts) != 2:
            raise ValueError("visit_time must be HH:MM format")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("visit_time must be HH:MM format") from None
        if hour < 8 or hour > 20:
            raise ValueError("visit_time must be between 08:00 and 20:00")
        if minute not in (0, 30):
            raise ValueError("visit_time must be on 30-minute intervals")
        if hour == 20 and minute != 0:
            raise ValueError("latest time is 20:00")
        return f"{hour:02d}:{minute:02d}"

    @model_validator(mode="after")
    def visit_not_already_started(self) -> "VisitorIn":
        hour, minute = (int(x) for x in self.visit_time.split(":"))
        start = datetime.combine(self.visit_date, time(hour, minute), tzinfo=SITE_TZ)
        if start < site_now():
            raise ValueError(
                f"visit {self.visit_date.isoformat()} {self.visit_time} has already passed (Asia/Seoul)"
            )
        return self

    def dedupe_key(self) -> tuple[str, str, str]:
        return (self.visitor_mobile, self.visit_date.isoformat(), self.visit_time)


ReservationStatus = Literal["SUCCEEDED", "FAILED", "UNKNOWN", "NOT_SUBMITTED"]


class ReservationResult(BaseModel):
    """Outcome of one visitor.

    status:
      SUCCEEDED      Centerfield answered ``success: true`` (dry run: validated, nothing submitted)
      FAILED         definitely not created (explicit reject, 4xx, validation/setup error)
      UNKNOWN        request may have been processed; outcome unconfirmed — never retry automatically
      NOT_SUBMITTED  skipped because an earlier row in the same bulk call was UNKNOWN
    ``success`` is kept for backward compatibility and is True only for SUCCEEDED.
    """

    visitor_name: str
    visitor_mobile: str
    success: bool
    message: str
    status: ReservationStatus = "SUCCEEDED"

    @model_validator(mode="before")
    @classmethod
    def _derive_status(cls, data):
        # Old callers pass only ``success``; derive the status from it.
        if isinstance(data, dict) and "status" not in data and "success" in data:
            data = {**data, "status": "SUCCEEDED" if data["success"] else "FAILED"}
        return data

    @model_validator(mode="after")
    def _success_matches_status(self) -> "ReservationResult":
        if self.success != (self.status == "SUCCEEDED"):
            raise ValueError("success must be true exactly when status is SUCCEEDED")
        return self


class BulkReservationOut(BaseModel):
    """``succeeded + failed + unknown + not_submitted == total``.

    ``failed`` counts only definite failures (FAILED); it no longer includes UNKNOWN or
    NOT_SUBMITTED rows (previously it was ``total - succeeded``).
    """

    total: int
    succeeded: int
    failed: int
    unknown: int = 0
    not_submitted: int = 0
    stopped_on_unknown: bool = False
    results: list[ReservationResult]
