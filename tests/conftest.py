from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from centerfield_visitor_mcp.config import settings

# Synthetic survey export: same 12 headers as the real registration form, fake people.
SURVEY_HEADERS = [
    "Submission ID", "Submitted On", "Submission Locale", "Internal Tags", "Full Name", "Email",
    "연락처(오프라인 참석신청시 당일 연락 가능 번호)", "어떤 형태로 참석하시나요?",
    "소속/회사 (없으시면 '개인'으로 입력)", "직책/역할", "주최측에 더 전달하고 싶은 내용이 있다면 자유롭게 남겨주세요.", "Comments",
]


def future(days: int = 14) -> str:
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """Every unit test runs with a fake, complete configuration and stdio transport."""
    monkeypatch.setattr(settings, "company_name", "Test Tenant Inc.")
    monkeypatch.setattr(settings, "person_in_charge_mobile", "01000000000")
    monkeypatch.setattr(settings, "building", "east")
    monkeypatch.setattr(settings, "building_key", "East")
    monkeypatch.setattr(settings, "default_floor", "12")
    monkeypatch.setattr(settings, "bulk_max_visitors", 200)
    monkeypatch.setattr(settings, "request_delay", 0.0)
    monkeypatch.setattr(settings, "centerfield_base_url", "https://cf.test")
    yield settings


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "company_name", "")
    monkeypatch.setattr(settings, "person_in_charge_mobile", "")
    return settings


@pytest.fixture
def future_date() -> str:
    return future()


@pytest.fixture
def visitor_kwargs(future_date):
    return dict(
        visitor_name="홍길동",
        visitor_company_name="ABC주식회사",
        visitor_mobile="010-1234-5678",
        visitor_email="hong@example.com",
        visit_date=future_date,
        visit_time="10:00",
    )


@pytest.fixture
def write_csv(tmp_path: Path):
    def _write(name: str, text: str, encoding: str = "utf-8") -> str:
        p = tmp_path / name
        p.write_text(text, encoding=encoding)
        return str(p)

    return _write


@pytest.fixture
def write_xlsx(tmp_path: Path):
    def _write(name: str, rows: list[list]) -> str:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        p = tmp_path / name
        wb.save(p)
        return str(p)

    return _write


@pytest.fixture
def survey_text() -> str:
    """10 fake submissions: 3 offline (one with a blank phone), 7 online."""
    rows = [SURVEY_HEADERS]
    people = [
        ("SurveySubmission-A1", "2026-09-20 23:57:45", "Host Person", "host@example.com", "", "오프라인", "aws", "", ""),
        ("SurveySubmission-A2", "2026-09-21 10:09:05", "김온라인", "on1@example.com", "", "온라인", "연구원", "석사후연구원", ""),
        ("SurveySubmission-A3", "2026-09-21 10:26:19", "이온라인", "on2@example.com", "01011112222", "온라인", "대학교", "대학원생", ""),
        ("SurveySubmission-A4", "2026-09-21 10:29:33", "박온라인", "on3@example.com", "", "온라인", "개인", "", ""),
        ("SurveySubmission-A5", "2026-09-22 06:52:44", "최온라인", "on4@example.com", "", "온라인", "개인", "", ""),
        ("SurveySubmission-A6", "2026-09-22 15:33:40", "정오프라인", "off1@example.com", "010-2222-3333", "오프라인", "테스트바이오", "", ""),
        ("SurveySubmission-A7", "2026-09-22 16:45:23", "강온라인", "on5@example.com", "", "온라인", "클라우드", "매니저", ""),
        ("SurveySubmission-A8", "2026-09-22 16:52:33", "조온라인", "on6@example.com", "", "온라인", "클라우드", "", ""),
        ("SurveySubmission-A9", "2026-09-25 00:29:42", "윤온라인", "on7@example.com", "", "온라인", "커뮤니티", "", "고맙습니다."),
        ("SurveySubmission-B1", "2026-09-28 15:24:16", "Off Nophone", "off2@example.com", "", "오프라인", "TESTCO", "", ""),
    ]
    for sid, ts, name, email, phone, mode, org, role, comment in people:
        rows.append([sid, ts, "en-US", "", name, email, phone, mode, org, role, comment, ""])
    import csv
    import io

    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return "\ufeff" + buf.getvalue()  # exported with a UTF-8 BOM, like the real file
