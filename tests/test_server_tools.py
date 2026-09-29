from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from centerfield_visitor_mcp import server
from centerfield_visitor_mcp.models import BulkReservationOut, ReservationResult
from tests.conftest import future

KO_HEADER = "이름,회사,전화번호,이메일,방문일,방문시간,층"


def _schema(tool) -> dict:
    """Tool input schema across SDK versions (mcp 1.x: inputSchema, mcp 2.x: input_schema)."""
    return getattr(tool, "inputSchema", None) or getattr(tool, "input_schema")


@pytest.fixture
def fake_bulk(monkeypatch):
    """Replace the network-bound bulk registration with a recorder."""
    calls: list[dict] = []

    async def _fake(visitors, *, dry_run=False):
        calls.append({"visitors": visitors, "dry_run": dry_run})
        results = [ReservationResult(visitor_name=v.visitor_name, visitor_mobile=v.visitor_mobile, success=True, message="ok") for v in visitors]
        return BulkReservationOut(total=len(visitors), succeeded=len(visitors), failed=0, results=results)

    monkeypatch.setattr(server, "register_bulk", _fake)
    return calls


@pytest.fixture
def fake_single(monkeypatch):
    calls: list[dict] = []

    async def _fake(visitor, *, dry_run=False):
        calls.append({"visitor": visitor, "dry_run": dry_run})
        return ReservationResult(visitor_name=visitor.visitor_name, visitor_mobile=visitor.visitor_mobile, success=True, message="ok")

    monkeypatch.setattr(server, "register_single", _fake)
    return calls


# ── tool registry / schema ────────────────────────────────────────────────

def test_tool_registry_has_expected_names():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    expected = {"validate_configuration", "register_visitor", "preview_visitors_from_text", "register_visitors_from_text"}
    assert expected <= names
    # file tools are registered at import time according to the transport in effect
    file_tools = {"preview_visitors_from_file", "register_visitors_from_file"}
    assert (file_tools <= names) == server.settings.file_tools_enabled


def test_input_schemas_are_draft7_compatible():
    """Amazon Quick rejects tools whose properties carry a boolean `required` (Draft 3)."""
    for tool in asyncio.run(server.mcp.list_tools()):
        schema = _schema(tool)
        assert schema["type"] == "object"
        assert isinstance(schema.get("required", []), list)
        for prop in schema.get("properties", {}).values():
            assert "required" not in prop or isinstance(prop["required"], list)


def test_register_visitor_schema_marks_optional_fields():
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "register_visitor")
    schema = _schema(tool)
    props = schema["properties"]
    assert set(schema["required"]) == {"visitor_name", "visitor_company_name", "visitor_mobile", "visitor_email", "visit_date", "visit_time"}
    assert props["dry_run"]["type"] == "boolean" and props["dry_run"]["default"] is False


# ── configuration gate ────────────────────────────────────────────────────

async def test_tools_refuse_without_configuration(unconfigured):
    msg = await server.register_visitor("a", "b", "01012345678", "a@example.com", future(), "10:00")
    assert "CF_COMPANY_NAME" in msg and "CF_PERSON_IN_CHARGE_MOBILE" in msg and "읽은 .env 파일" in msg
    assert "설정이 비어" in await server.register_visitors_from_text("이름\n홍길동")
    assert "설정이 비어" in await server.validate_configuration()


async def test_preview_works_without_configuration(unconfigured):
    text = KO_HEADER + f"\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n"
    assert "파싱 결과: 1명 유효" in await server.preview_visitors_from_text(text)


# ── register_visitor ──────────────────────────────────────────────────────

async def test_register_visitor_success_and_dry_run(fake_single):
    out = await server.register_visitor("홍길동", "ABC", "010-1234-5678", "hong@example.com", future(), "10:00", floor="18")
    assert out.startswith("예약 완료: 홍길동") and "18층" in out
    assert fake_single[-1]["visitor"].visitor_mobile == "01012345678" and fake_single[-1]["dry_run"] is False
    out = await server.register_visitor("홍길동", "ABC", "01012345678", "hong@example.com", future(), "10:00", dry_run=True)
    assert out.startswith("검증 완료 (dry run") and fake_single[-1]["dry_run"] is True


async def test_register_visitor_input_error_is_compact(fake_single):
    out = await server.register_visitor("홍길동", "ABC", "", "bad", future(), "14:15")
    assert out.startswith("입력값 오류:") and "visitor_mobile" in out and "visitor_email" in out and "visit_time" in out
    assert fake_single == []


async def test_register_visitor_uses_default_floor(fake_single, configured):
    configured.default_floor = "18"
    await server.register_visitor("홍길동", "ABC", "01012345678", "hong@example.com", future(), "10:00")
    assert fake_single[-1]["visitor"].floor == "18"


# ── text tools ────────────────────────────────────────────────────────────

async def test_preview_text_with_defaults_and_errors():
    text = "이름,회사,전화번호,이메일\n홍길동,ABC,01012345678,hong@example.com\n김영희,XYZ,,kim@example.com\n"
    out = await server.preview_visitors_from_text(text, default_visit_date=future(), default_visit_time="14:00", default_floor="18")
    assert "파싱 결과: 1명 유효, 1건 오류" in out
    assert "18층" in out and "행 3" in out and "visitor_mobile" in out


async def test_preview_text_empty_and_unmapped():
    assert "비어있습니다" in await server.preview_visitors_from_text("   ")
    assert "추출할 수 없습니다" in await server.preview_visitors_from_text("foo,bar\n1,2\n")


async def test_register_text_happy_path_and_summary(fake_bulk):
    text = KO_HEADER + f"\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n김영희,XYZ,01087654321,kim@example.com,{future()},10:30,18\n"
    out = await server.register_visitors_from_text(text)
    assert out.startswith("일괄 등록 결과: 총 2명 중 2명 성공, 0명 실패")
    assert len(fake_bulk[-1]["visitors"]) == 2


async def test_register_text_dry_run_label(fake_bulk):
    text = "이름,회사,전화번호,이메일\n홍길동,ABC,01012345678,hong@example.com\n"
    out = await server.register_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", dry_run=True)
    assert out.startswith("일괄 검증 결과 (dry run, 미제출)") and fake_bulk[-1]["dry_run"] is True


async def test_register_text_reports_skipped_rows(fake_bulk):
    text = KO_HEADER + f"\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n김영희,XYZ,,kim@example.com,{future()},10:30,18\n"
    out = await server.register_visitors_from_text(text)
    assert "1명 성공" in out and "파싱 단계에서 건너뛴 행 (1건)" in out and "행 3" in out


async def test_register_text_all_invalid(fake_bulk):
    out = await server.register_visitors_from_text("이름,회사,전화번호,이메일\n홍길동,ABC,,hong@example.com\n", default_visit_date=future(), default_visit_time="10:00")
    assert out.startswith("유효한 방문자 정보가 없습니다") and fake_bulk == []


async def test_register_text_bulk_cap(fake_bulk, configured):
    configured.bulk_max_visitors = 2
    rows = "\n".join(f"v{i},ABC,0101111{i:04d},v{i}@example.com,{future()},10:00,12" for i in range(3))
    out = await server.register_visitors_from_text(KO_HEADER + "\n" + rows + "\n")
    assert "최대 2명" in out and fake_bulk == []


async def test_register_text_tsv(fake_bulk):
    text = "이름\t회사\t전화번호\t이메일\t방문일\t방문시간\n홍길동\tABC\t01012345678\thong@example.com\t" + future() + "\t10:00\n"
    out = await server.register_visitors_from_text(text)
    assert "1명 성공" in out


async def test_survey_export_through_text_tool(fake_bulk, survey_text):
    out = await server.preview_visitors_from_text(survey_text, default_visit_date=future(), default_visit_time="14:00", default_floor="18")
    # all 10 rows map (name/email/mobile/company); rows without a phone are reported as errors
    assert "파싱 결과: 2명 유효, 8건 오류" in out
    assert "visitor_mobile" in out
    # the attendance column is detected and surfaced so the agent can filter
    assert "참석 형태 컬럼 감지: 온라인 7, 오프라인 3" in out and "participation 인자" in out


async def test_participation_filter_keeps_only_offline_rows(fake_bulk, survey_text):
    out = await server.preview_visitors_from_text(
        survey_text, default_visit_date=future(), default_visit_time="14:00", default_floor="18", participation="오프라인"
    )
    assert "참석 형태 필터 '오프라인': 3건 대상, 7건 제외 (온라인 7)" in out
    # 3 offline rows: 2 without a phone -> errors, 1 valid; no online attendee leaks through
    assert "파싱 결과: 1명 유효, 2건 오류" in out
    assert "정오프라인" in out and "이온라인" not in out


@pytest.mark.parametrize("value", ["오프라인", "오프 라인", "OFFLINE".lower(), " 오프라인 "])
async def test_participation_filter_matching_is_lenient(fake_bulk, value):
    text = "이름,회사,전화번호,이메일,참석 형태\n홍길동,ABC,01012345678,hong@example.com,오프라인\n김영희,XYZ,01087654321,kim@example.com,온라인\n"
    out = await server.preview_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", participation=value)
    if value.strip().lower() == "offline":
        assert "0건 대상" in out  # Korean data, English filter: nothing matches, and that is reported
    else:
        assert "1건 대상, 1건 제외 (온라인 1)" in out and "홍길동" in out and "김영희" not in out


async def test_participation_value_never_reaches_visitor_model(fake_bulk):
    text = "이름,회사,전화번호,이메일,참석 형태\n홍길동,ABC,01012345678,hong@example.com,오프라인\n"
    out = await server.register_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", participation="오프라인")
    assert "총 1명 중 1명 성공" in out and "참석 형태 필터 '오프라인': 1건 대상, 0건 제외 (없음)" in out
    assert fake_bulk[-1]["visitors"][0].visitor_name == "홍길동"


async def test_register_with_filter_refuses_when_column_missing(fake_bulk):
    before = len(fake_bulk)
    text = "이름,회사,전화번호,이메일\n홍길동,ABC,01012345678,hong@example.com\n"
    out = await server.register_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", participation="오프라인")
    assert "참석 형태 컬럼을 찾을 수 없어" in out and len(fake_bulk) == before  # nothing registered


async def test_preview_with_filter_but_no_column_shows_unfiltered_preview():
    text = "이름,회사,전화번호,이메일\n홍길동,ABC,01012345678,hong@example.com\n"
    out = await server.preview_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", participation="오프라인")
    assert out.startswith("참석 형태 컬럼을 찾을 수 없어") and "(참석 형태 필터 미적용 미리보기)" in out and "홍길동" in out


async def test_register_with_filter_matching_nothing(fake_bulk):
    before = len(fake_bulk)
    text = "이름,회사,전화번호,이메일,참석 형태\n홍길동,ABC,01012345678,hong@example.com,온라인\n"
    out = await server.register_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", participation="오프라인")
    assert "0건 대상, 1건 제외 (온라인 1)" in out and "처리할 방문자가 없습니다" in out and len(fake_bulk) == before


async def test_rows_with_empty_participation_are_dropped_by_filter(fake_bulk):
    text = "이름,회사,전화번호,이메일,참석 형태\n홍길동,ABC,01012345678,hong@example.com,\n김영희,XYZ,01087654321,kim@example.com,오프라인\n"
    out = await server.preview_visitors_from_text(text, default_visit_date=future(), default_visit_time="10:00", participation="오프라인")
    assert "1건 대상, 1건 제외 ((빈값) 1)" in out and "김영희" in out and "홍길동" not in out


# ── file tools ────────────────────────────────────────────────────────────

async def test_preview_file_csv_and_xlsx(write_csv, write_xlsx):
    csv_path = write_csv("v.csv", KO_HEADER + f"\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n")
    assert "파싱 결과: 1명 유효, 0건 오류" in await server.preview_visitors_from_file(csv_path)
    xlsx_path = write_xlsx("v.xlsx", [["이름", "회사", "전화번호", "이메일", "방문일", "방문시간"], ["홍길동", "ABC", 1012345678, "hong@example.com", future(), "10:00"]])
    assert "01012345678" in await server.preview_visitors_from_file(xlsx_path)


async def test_preview_file_errors(tmp_path):
    assert "파일을 찾을 수 없습니다" in await server.preview_visitors_from_file(str(tmp_path / "nope.csv"))
    (tmp_path / "x.json").write_text("{}")
    assert "지원하지 않는 파일 형식" in await server.preview_visitors_from_file(str(tmp_path / "x.json"))


async def test_register_file_with_defaults(fake_bulk, write_csv):
    path = write_csv("names.csv", "Full Name,Email,연락처(오프라인 참석신청시 당일 연락 가능 번호),소속/회사 (없으시면 '개인'으로 입력)\n홍길동,hong@example.com,010-1234-5678,ABC\n")
    out = await server.register_visitors_from_file(path, default_visit_date=future(), default_visit_time="14:00", default_floor="18")
    assert "총 1명 중 1명 성공" in out
    v = fake_bulk[-1]["visitors"][0]
    assert (v.visitor_company_name, v.floor, v.visit_time) == ("ABC", "18", "14:00")


async def test_file_tools_participation_filter(fake_bulk, write_xlsx):
    fixture = Path(__file__).parent / "fixtures" / "attendee_list_no_dates.csv"
    plain = await server.preview_visitors_from_file(str(fixture), default_visit_date=future(), default_visit_time="14:00")
    assert "참석 형태 컬럼 감지" in plain
    offline = await server.preview_visitors_from_file(str(fixture), default_visit_date=future(), default_visit_time="14:00", participation="오프라인")
    assert "참석 형태 필터 '오프라인'" in offline and "온라인" not in offline.split("파싱 결과")[1]

    xlsx = write_xlsx("survey.xlsx", [
        ["Full Name", "Email", "연락처", "어떤 형태로 참석하시나요?", "소속/회사"],
        ["홍길동", "hong@example.com", 1012345678, "오프라인", "ABC"],
        ["김온라인", "kim@example.com", 1087654321, "온라인", "XYZ"],
    ])
    out = await server.register_visitors_from_file(xlsx, default_visit_date=future(), default_visit_time="14:00", participation="오프라인")
    assert "1건 대상, 1건 제외 (온라인 1)" in out and "총 1명 중 1명 성공" in out
    assert [v.visitor_name for v in fake_bulk[-1]["visitors"]] == ["홍길동"]


# ── live (opt-in) ─────────────────────────────────────────────────────────

@pytest.mark.live
async def test_live_validate_configuration(monkeypatch):
    """Read-only check against www.centerfield.co.kr using the real .env (no reservation)."""
    from centerfield_visitor_mcp.config import Settings

    real = Settings()
    if real.missing_required():
        pytest.skip("real CF_* settings not available")
    for name in ("company_name", "person_in_charge_mobile", "building", "building_key", "default_floor", "centerfield_base_url"):
        monkeypatch.setattr(server.settings, name, getattr(real, name))
    out = await server.validate_configuration()
    assert out.startswith("설정 확인 완료"), out
    assert "lower_floor" in out or "floor" in out.lower()


@pytest.mark.live
async def test_live_register_visitor_if_allowed(monkeypatch):
    """Creates ONE real reservation. Requires CF_LIVE_REGISTER=1 and CF_TEST_VISITOR_* env vars.

    The human operator verifies the result in the Centerfield mobile app.
    """
    if os.environ.get("CF_LIVE_REGISTER") != "1":
        pytest.skip("set CF_LIVE_REGISTER=1 to create a real test reservation")
    from centerfield_visitor_mcp.config import Settings

    real = Settings()
    for name in ("company_name", "person_in_charge_mobile", "building", "building_key", "default_floor", "centerfield_base_url"):
        monkeypatch.setattr(server.settings, name, getattr(real, name))
    out = await server.register_visitor(
        visitor_name=os.environ["CF_TEST_VISITOR_NAME"],
        visitor_company_name=os.environ.get("CF_TEST_VISITOR_COMPANY", "MCP Test"),
        visitor_mobile=os.environ["CF_TEST_VISITOR_MOBILE"],
        visitor_email=os.environ["CF_TEST_VISITOR_EMAIL"],
        visit_date=os.environ.get("CF_TEST_VISIT_DATE") or future(1),
        visit_time=os.environ.get("CF_TEST_VISIT_TIME", "10:00"),
        floor=os.environ.get("CF_TEST_FLOOR", ""),
    )
    assert out.startswith("예약 완료"), out
