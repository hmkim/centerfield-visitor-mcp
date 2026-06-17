from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator


VALID_PURPOSES = Literal[
    "visit_business", "meeting", "interview", "tour", "construction", "others"
]


class VisitorIn(BaseModel):
    visitor_name: str
    visitor_company_name: str
    visitor_mobile: str
    visitor_email: EmailStr
    visit_date: date
    visit_time: str
    visit_purpose: VALID_PURPOSES = "meeting"
    floor: Literal["12", "18"] = "12"

    @field_validator("visitor_mobile")
    @classmethod
    def normalize_mobile(cls, v: str) -> str:
        return v.replace("-", "").replace(" ", "")

    @field_validator("visit_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("visit_time must be HH:MM format")
        hour, minute = int(parts[0]), int(parts[1])
        if hour < 8 or hour > 20:
            raise ValueError("visit_time must be between 08:00 and 20:00")
        if minute not in (0, 30):
            raise ValueError("visit_time must be on 30-minute intervals")
        if hour == 20 and minute != 0:
            raise ValueError("latest time is 20:00")
        return f"{hour:02d}:{minute:02d}"


class ReservationResult(BaseModel):
    visitor_name: str
    visitor_mobile: str
    success: bool
    message: str


class BulkReservationOut(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[ReservationResult]
