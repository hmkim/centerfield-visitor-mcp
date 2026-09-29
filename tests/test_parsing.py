import datetime as dt

import pytest

from centerfield_visitor_mcp import server
from centerfield_visitor_mcp.server import (
    RowDefaults,
    _build_visitors,
    _detect_delimiter,
    _map_columns,
    _normalize_column,
    _parse_csv_text,
    _parse_excel,
    _read_file_records,
)
from tests.conftest import SURVEY_HEADERS, future

KO_HEADER = "이름,회사,전화번호,이메일,방문일,방문시간,층"


# ── header mapping ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "header, field",
    [
        ("이름", "visitor_name"), ("성명", "visitor_name"), ("Name", "visitor_name"), (" visitor_name ", "visitor_name"),
        ("Full Name", "visitor_name"), ("방문자 이름", "visitor_name"),
        ("회사", "visitor_company_name"), ("소속", "visitor_company_name"), ("Company", "visitor_company_name"),
        ("소속/회사 (없으시면 '개인'으로 입력)", "visitor_company_name"), ("회사명", "visitor_company_name"),
        ("전화번호", "visitor_mobile"), ("휴대폰", "visitor_mobile"), ("Mobile", "visitor_mobile"), ("Phone", "visitor_mobile"),
        ("연락처(오프라인 참석신청시 당일 연락 가능 번호)", "visitor_mobile"), ("핸드폰 번호", "visitor_mobile"),
        ("이메일", "visitor_email"), ("Email", "visitor_email"), ("E-mail", "visitor_email"), ("이메일 주소", "visitor_email"),
        ("방문일", "visit_date"), ("Date", "visit_date"), ("방문 날짜", "visit_date"),
        ("방문시간", "visit_time"), ("Time", "visit_time"),
        ("목적", "visit_purpose"), ("방문목적", "visit_purpose"),
        ("층", "floor"), ("Floor", "floor"), ("방문 층", "floor"),
    ],
)
def test_normalize_column_maps(header, field):
    assert _normalize_column(header) == field


@pytest.mark.parametrize(
    "header",
    ["Submission ID", "Submitted On", "Submission Locale", "Internal Tags", "Comments", "직책/역할",
     "주최측에 더 전달하고 싶은 내용이 있다면 자유롭게 남겨주세요.", "", "   "],
)
def test_normalize_column_ignores_metadata(header):
    assert _normalize_column(header) is None


@pytest.mark.parametrize(
    "header",
    ["어떤 형태로 참석하시나요?", "참석 형태", "참석형태", "참가 방식", "참석 유형", "Participation", "participation_type",
     "Attendance type", "어떤 형태로 참가하시나요"],
)
def test_normalize_column_maps_participation(header):
    assert _normalize_column(header) == "participation"


def test_participation_header_does_not_steal_visitor_fields():
    # The mobile header mentions 오프라인 inside parentheses; parentheses are stripped before matching.
    assert _normalize_column("연락처(오프라인 참석신청시 당일 연락 가능 번호)") == "visitor_mobile"
    assert _normalize_column("참석자 이름") == "visitor_name"


def test_map_columns_survey_export():
    mapping = _map_columns(SURVEY_HEADERS)
    assert set(mapping.values()) == {"visitor_name", "visitor_email", "visitor_mobile", "visitor_company_name", "participation"}
    assert mapping[4] == "visitor_name" and mapping[5] == "visitor_email"


def test_map_columns_first_column_wins_on_duplicates():
    mapping = _map_columns(["이름", "성명", "이메일"])
    assert mapping == {0: "visitor_name", 2: "visitor_email"}


# ── csv / tsv ─────────────────────────────────────────────────────────────

def test_parse_csv_basic():
    text = KO_HEADER + f"\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n"
    records = _parse_csv_text(text)
    assert len(records) == 1
    assert records[0]["visitor_name"] == "홍길동"
    assert records[0]["floor"] == "12"
    assert records[0]["_row"] == 2


def test_parse_csv_skips_blank_and_nameless_rows():
    text = KO_HEADER + f"\n,,,,,,\n\n,ABC,01012345678,x@example.com,{future()},10:00,12\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n"
    records = _parse_csv_text(text)
    assert [r["visitor_name"] for r in records] == ["홍길동"]
    assert records[0]["_row"] == 5


def test_parse_csv_unknown_headers_returns_empty():
    assert _parse_csv_text("foo,bar\n1,2\n") == []
    assert _parse_csv_text("") == []


def test_detect_delimiter_and_tsv():
    text = "이름\t회사\t전화번호\t이메일\t방문일\t방문시간\n홍길동\tABC\t01012345678\thong@example.com\t" + future() + "\t10:00\n"
    assert _detect_delimiter(text) == "\t"
    records = _parse_csv_text(text, delimiter="\t")
    assert records[0]["visitor_company_name"] == "ABC"


def test_parse_csv_missing_cells_are_absent_not_empty():
    text = "이름,회사,전화번호,이메일\n홍길동,ABC,,hong@example.com\n"
    records = _parse_csv_text(text)
    assert "visitor_mobile" not in records[0]


def test_read_file_records_csv_with_bom(write_csv):
    path = write_csv("bom.csv", "\ufeff" + KO_HEADER + f"\n홍길동,ABC,01012345678,hong@example.com,{future()},10:00,12\n")
    records, err = _read_file_records(path)
    assert err is None and records[0]["visitor_name"] == "홍길동"


def test_read_file_records_tsv_and_unsupported(write_csv, tmp_path):
    path = write_csv("v.tsv", "이름\t이메일\n홍길동\th@example.com\n")
    records, err = _read_file_records(path)
    assert err is None and records[0]["visitor_email"] == "h@example.com"
    (tmp_path / "v.xls").write_bytes(b"")
    records, err = _read_file_records(str(tmp_path / "v.xls"))
    assert records is None and "지원하지 않는 파일 형식" in err
    records, err = _read_file_records(str(tmp_path / "missing.csv"))
    assert records is None and "파일을 찾을 수 없습니다" in err


# ── xlsx ──────────────────────────────────────────────────────────────────

def test_parse_excel_cell_types(write_xlsx):
    visit = dt.date.today() + dt.timedelta(days=10)
    path = write_xlsx(
        "v.xlsx",
        [
            ["이름", "회사", "전화번호", "이메일", "방문일", "방문시간", "층"],
            ["홍길동", "ABC", 1012345678, "hong@example.com", dt.datetime(visit.year, visit.month, visit.day), dt.time(14, 0), 18],
            ["김영희", "XYZ", "010-8765-4321", "kim@example.com", visit.isoformat(), 0.4375, 12.0],  # 0.4375 day = 10:30
            [None, None, None, None, None, None, None],
        ],
    )
    records = _parse_excel(path)
    assert len(records) == 2
    assert records[0]["visitor_mobile"] == "01012345678"  # leading zero restored
    assert records[0]["visit_date"] == visit.isoformat()
    assert records[0]["visit_time"] == "14:00"
    assert records[0]["floor"] == "18"
    assert records[1]["visit_time"] == "10:30"
    assert records[1]["floor"] == "12"


def test_parse_excel_empty_and_unmapped(write_xlsx):
    assert _parse_excel(write_xlsx("empty.xlsx", [[None]])) == []
    assert _parse_excel(write_xlsx("hdr.xlsx", [["foo", "bar"], [1, 2]])) == []


# ── build visitors: defaults + dedupe ─────────────────────────────────────

def test_build_visitors_applies_defaults_and_row_numbers():
    records = _parse_csv_text("이름,회사,전화번호,이메일\n홍길동,ABC,01012345678,hong@example.com\n")
    visitors, errors = _build_visitors(records, RowDefaults(visit_date=future(), visit_time="14:00", floor="18", purpose="tour"))
    assert errors == []
    v = visitors[0]
    assert (v.visit_time, v.floor, v.visit_purpose) == ("14:00", "18", "tour")


def test_build_visitors_without_date_default_reports_row():
    records = _parse_csv_text("이름,회사,전화번호,이메일\n홍길동,ABC,01012345678,hong@example.com\n")
    visitors, errors = _build_visitors(records)
    assert visitors == []
    assert errors and errors[0].startswith("  행 2:") and "visit_date" in errors[0]


def test_build_visitors_reports_field_errors_compactly():
    records = _parse_csv_text(f"이름,회사,전화번호,이메일,방문일,방문시간\n홍길동,ABC,,hong@example,{future()},14:15\n")
    visitors, errors = _build_visitors(records)
    assert visitors == []
    assert "visitor_mobile" in errors[0] and "visitor_email" in errors[0] and "visit_time" in errors[0]
    assert "Value error" not in errors[0]


def test_build_visitors_dedupes_same_mobile_and_slot():
    d = future()
    text = f"이름,회사,전화번호,이메일,방문일,방문시간\n홍길동,ABC,01012345678,a@example.com,{d},10:00\n홍길동,ABC,010-1234-5678,b@example.com,{d},10:00\n김영희,ABC,01099998888,c@example.com,{d},10:00\n"
    visitors, errors = _build_visitors(_parse_csv_text(text))
    assert [v.visitor_name for v in visitors] == ["홍길동", "김영희"]
    assert len(errors) == 1 and "중복" in errors[0] and "행 3" in errors[0]


def test_build_visitors_row_default_floor_from_settings(configured):
    configured.default_floor = "18"
    records = _parse_csv_text(f"이름,회사,전화번호,이메일,방문일,방문시간\n홍길동,ABC,01012345678,a@example.com,{future()},10:00\n")
    visitors, _ = _build_visitors(records)
    assert visitors[0].floor == "18"


# ── survey export end-to-end (offline) ────────────────────────────────────

def test_survey_export_parses_after_filtering(survey_text):
    # Agent-side step: keep offline attendees only, drop the host row.
    lines = survey_text.lstrip("\ufeff").splitlines()
    import csv
    import io

    rows = list(csv.reader(io.StringIO("\n".join(lines))))
    header, body = rows[0], rows[1:]
    mode_idx = header.index("어떤 형태로 참석하시나요?")
    kept = [header] + [r for r in body if r[mode_idx] == "오프라인" and r[4] != "Host Person"]
    buf = io.StringIO()
    csv.writer(buf).writerows(kept)
    records = _parse_csv_text(buf.getvalue())
    assert len(records) == 2
    visitors, errors = _build_visitors(records, RowDefaults(visit_date=future(), visit_time="14:00", floor="18"))
    assert [v.visitor_name for v in visitors] == ["정오프라인"]
    assert len(errors) == 1 and "visitor_mobile" in errors[0]  # the blank-phone attendee is reported, not silently sent


def test_survey_export_raw_preview_maps_columns(survey_text):
    records = _parse_csv_text(survey_text.lstrip("\ufeff"))
    assert len(records) == 10
    assert all("visitor_name" in r and "visitor_email" in r for r in records)
