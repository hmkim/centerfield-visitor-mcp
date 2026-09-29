"""Centerfield Visitor Reservation MCP Server.

Exposes visitor registration as MCP tools for AI agents (Kiro CLI/IDE, KiroCrew,
Claude Code, Codex, Cursor, Amazon Quick, Strands, ...).

Transports:
    stdio            (default)  — local agents
    streamable-http             — remote agents; set CF_TRANSPORT=streamable-http

Usage:
    uvx centerfield-visitor-mcp
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from ._compat import MCP_MAJOR, create_server, run_server
from .config import settings
from .exceptions import CenterfieldError
from .models import VisitorIn
from .service import check_configuration, register_bulk, register_single

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = create_server("Centerfield Visitor Reservation", settings, version=__version__)

# ── Column mapping ────────────────────────────────────────────────────────

COLUMN_ALIASES = {
    "visitor_name": ["이름", "name", "visitor_name", "성명", "방문자명", "방문자이름", "full name", "full_name"],
    "visitor_company_name": ["회사", "company", "visitor_company_name", "소속", "회사명", "소속회사", "소속/회사"],
    "visitor_mobile": ["전화번호", "mobile", "visitor_mobile", "휴대폰", "연락처", "phone", "핸드폰", "mobile phone"],
    "visitor_email": ["이메일", "email", "visitor_email", "메일", "e-mail"],
    "visit_date": ["방문일", "date", "visit_date", "날짜", "방문날짜", "방문일자"],
    "visit_time": ["방문시간", "time", "visit_time", "시간"],
    "visit_purpose": ["목적", "purpose", "visit_purpose", "방문목적"],
    "floor": ["층", "floor", "방문층", "층수"],
    # Attendance type of a survey/attendee export (e.g. 오프라인/온라인). Not a VisitorIn field:
    # it only drives the optional `participation` filter of the list tools.
    "participation": [
        "참석형태", "참석 형태", "참가형태", "참가 형태", "참석방식", "참가방식", "참석유형", "참가유형",
        "participation", "participation type", "attendance", "attendance type", "attendance_type",
    ],
}

# Fuzzy fallback: (normalized stem, field). Longest/most specific stems first.
_STEMS: list[tuple[str, str]] = [
    ("방문시간", "visit_time"), ("방문일자", "visit_date"), ("방문날짜", "visit_date"),
    ("방문목적", "visit_purpose"), ("방문자이름", "visitor_name"), ("방문자명", "visitor_name"),
    ("방문층", "floor"), ("방문일", "visit_date"),
    ("참석형태", "participation"), ("참가형태", "participation"), ("참석방식", "participation"),
    ("참가방식", "participation"), ("참석유형", "participation"), ("participation", "participation"),
    ("attendance", "participation"), ("형태로참석", "participation"), ("형태로참가", "participation"),
    ("visitorname", "visitor_name"), ("fullname", "visitor_name"),
    ("companyname", "visitor_company_name"), ("visitorcompany", "visitor_company_name"),
    ("회사이름", "visitor_company_name"), ("회사명", "visitor_company_name"),
    ("전화번호", "visitor_mobile"), ("휴대폰", "visitor_mobile"), ("핸드폰", "visitor_mobile"),
    ("연락처", "visitor_mobile"), ("mobile", "visitor_mobile"), ("phone", "visitor_mobile"),
    ("이메일", "visitor_email"), ("email", "visitor_email"), ("메일", "visitor_email"),
    ("회사", "visitor_company_name"), ("소속", "visitor_company_name"),
    ("company", "visitor_company_name"), ("organization", "visitor_company_name"),
    ("affiliation", "visitor_company_name"),
    ("목적", "visit_purpose"), ("purpose", "visit_purpose"),
    ("성명", "visitor_name"), ("이름", "visitor_name"), ("name", "visitor_name"),
    ("날짜", "visit_date"), ("date", "visit_date"),
    ("시간", "visit_time"), ("time", "visit_time"),
    ("floor", "floor"), ("층", "floor"),
]

# Normalized headers that must never map (typical survey-export metadata).
_EXCLUDED_HEADERS = {
    "submissionid", "submittedon", "submissionlocale", "internaltags", "comments", "comment",
    "id", "status", "locale",
}

_PAREN_RE = re.compile(r"\([^)]*\)|（[^）]*）|\[[^\]]*\]")
_NON_TOKEN_RE = re.compile(r"[^0-9a-z가-힣]")


def _norm(col: str) -> str:
    text = _PAREN_RE.sub("", str(col or "")).lower()
    return _NON_TOKEN_RE.sub("", text)


_EXACT_ALIASES = {
    _norm(alias): field for field, aliases in COLUMN_ALIASES.items() for alias in aliases
}


def _normalize_column(col: str) -> str | None:
    n = _norm(col)
    if not n or n in _EXCLUDED_HEADERS:
        return None
    if n in _EXACT_ALIASES:
        return _EXACT_ALIASES[n]
    for stem, field in _STEMS:
        if stem in n:
            return field
    return None


def _map_columns(headers: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    taken: set[str] = set()
    for idx, header in enumerate(headers):
        field = _normalize_column(header)
        if field and field not in taken:
            mapping[idx] = field
            taken.add(field)
    return mapping


# ── Parsing ───────────────────────────────────────────────────────────────

def _parse_csv_text(text: str, delimiter: str = ",") -> list[dict]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []

    col_map = _map_columns(rows[0])
    if not col_map:
        return []

    records = []
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        record: dict = {"_row": line_no}
        for idx, field in col_map.items():
            if idx < len(row) and row[idx].strip():
                record[field] = row[idx].strip()
        if record.get("visitor_name"):
            records.append(record)
    return records


def _normalize_excel_cell(field: str, value) -> str:
    """Convert openpyxl cell values into the string formats VisitorIn expects."""
    if field == "visit_date" and hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    if field == "visit_time":
        if hasattr(value, "strftime"):  # datetime.time / datetime.datetime
            return value.strftime("%H:%M")
        if isinstance(value, float) and 0 <= value < 1:  # Excel fraction-of-day
            minutes = round(value * 24 * 60)
            return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if field == "floor" and isinstance(value, (int, float)):
        return str(int(value))
    if field == "visitor_mobile" and isinstance(value, (int, float)):
        digits = str(int(value))
        # Excel drops the leading 0 of Korean mobile numbers (01012345678 -> 1012345678)
        return "0" + digits if digits.startswith("1") and len(digits) == 10 else digits
    return str(value).strip()


def _parse_excel(file_path: str) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    headers = [str(cell) if cell else "" for cell in rows[0]]
    col_map = _map_columns(headers)
    if not col_map:
        return []

    records = []
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell for cell in row):
            continue
        record: dict = {"_row": line_no}
        for idx, field in col_map.items():
            if idx < len(row) and row[idx] is not None and str(row[idx]).strip():
                record[field] = _normalize_excel_cell(field, row[idx])
        if record.get("visitor_name"):
            records.append(record)
    return records


def _read_file_records(file_path: str) -> tuple[list[dict] | None, str | None]:
    """Return (records, error_message)."""
    path = Path(file_path)
    if not path.exists():
        return None, f"파일을 찾을 수 없습니다: {file_path}"
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return _parse_excel(str(path)), None
    if ext in (".csv", ".tsv", ".txt"):
        text = path.read_text(encoding="utf-8-sig")
        return _parse_csv_text(text, delimiter=_detect_delimiter(text)), None
    return None, f"지원하지 않는 파일 형식입니다: {ext} (xlsx, csv, tsv만 지원)"


def _detect_delimiter(text: str) -> str:
    first = text.split("\n", 1)[0]
    return "\t" if "\t" in first else ","


# ── Validation ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RowDefaults:
    visit_date: str = ""
    visit_time: str = ""
    floor: str = ""
    purpose: str = ""


_VALUE_NOISE_RE = re.compile(r"[\s\-_/·.]")


def _norm_value(value) -> str:
    return _VALUE_NOISE_RE.sub("", str(value or "")).lower()


_NO_PARTICIPATION_COLUMN_MSG = (
    "참석 형태 컬럼을 찾을 수 없어 participation 필터를 적용할 수 없습니다. "
    "헤더에 '참석 형태' / '어떤 형태로 참석하시나요?' / 'participation' 같은 컬럼이 있어야 합니다. "
    "필터 없이 전체를 처리하려면 participation 인자를 비워두세요."
)


def _apply_participation_filter(records: list[dict], participation: str) -> tuple[list[dict], list[str], str | None]:
    """Return (kept_records, info_lines, error).

    - Empty filter: records pass through. If the input has a participation column, one info line
      summarises its values so the agent can decide whether to filter.
    - Filter given but no participation column: error (nothing must be processed by mistake).
    - Filter given: keep rows whose participation value contains the filter text
      (case/space/hyphen-insensitive); rows with an empty value are dropped and reported.
    """
    has_col = any("participation" in rec for rec in records)
    wanted = _norm_value(participation)
    if not wanted:
        if not has_col:
            return records, [], None
        counts = Counter(rec.get("participation", "") or "(빈값)" for rec in records)
        summary = ", ".join(f"{value} {n}" for value, n in counts.most_common())
        return records, [
            f"참석 형태 컬럼 감지: {summary} — 특정 형태만 처리하려면 participation 인자를 지정하세요 (예: 오프라인)"
        ], None
    if not has_col:
        return records, [], _NO_PARTICIPATION_COLUMN_MSG
    kept = [rec for rec in records if wanted in _norm_value(rec.get("participation"))]
    dropped = Counter(
        rec.get("participation", "") or "(빈값)" for rec in records if wanted not in _norm_value(rec.get("participation"))
    )
    detail = ", ".join(f"{value} {n}" for value, n in dropped.most_common()) or "없음"
    info = [f"참석 형태 필터 '{participation.strip()}': {len(kept)}건 대상, {sum(dropped.values())}건 제외 ({detail})"]
    return kept, info, None


def _build_visitors(records: list[dict], defaults: RowDefaults = RowDefaults()) -> tuple[list[VisitorIn], list[str]]:
    visitors: list[VisitorIn] = []
    errors: list[str] = []
    seen: dict[tuple[str, str, str], int] = {}
    for i, rec in enumerate(records):
        row = rec.pop("_row", i + 2)
        rec.pop("participation", None)  # filter-only column, not part of VisitorIn
        try:
            if not rec.get("visit_date") and defaults.visit_date:
                rec["visit_date"] = defaults.visit_date
            if not rec.get("visit_time") and defaults.visit_time:
                rec["visit_time"] = defaults.visit_time
            if not rec.get("visit_purpose"):
                rec["visit_purpose"] = defaults.purpose or "meeting"
            if not rec.get("floor"):
                rec["floor"] = defaults.floor or settings.default_floor
            visitor = VisitorIn(**rec)
        except Exception as e:  # pydantic ValidationError
            errors.append(f"  행 {row}: {_short_validation_error(e)}")
            continue
        key = visitor.dedupe_key()
        if key in seen:
            errors.append(f"  행 {row}: 행 {seen[key]}과(와) 중복 (같은 휴대폰·방문일시) — 건너뜀")
            continue
        seen[key] = row
        visitors.append(visitor)

    if errors:
        logger.warning("Validation skipped %d row(s)", len(errors))

    return visitors, errors


def _short_validation_error(exc: Exception) -> str:
    """Compact pydantic error text: 'field: message; field2: message'."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    parts = []
    for err in errors():
        loc = ".".join(str(x) for x in err.get("loc", ())) or "input"
        msg = err.get("msg", "")
        msg = re.sub(r"^Value error, ", "", msg)
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts) or str(exc)


def _config_error() -> str | None:
    """Return a user-facing message when required settings are missing."""
    missing = settings.missing_required()
    if not missing:
        return None
    loaded = settings.loaded_env_files() or ["(없음)"]
    return (
        "센터필드 MCP 설정이 비어 있어 등록할 수 없습니다: " + ", ".join(missing) + "\n"
        "읽은 .env 파일: " + ", ".join(loaded) + "\n"
        ".env.example을 .env로 복사해 값을 채우고, MCP 설정에 CF_ENV_FILE=<.env 절대경로>를 지정하세요."
    )


def _defaults(default_visit_date: str, default_visit_time: str, default_floor: str, default_purpose: str) -> RowDefaults:
    return RowDefaults(
        visit_date=default_visit_date.strip(),
        visit_time=default_visit_time.strip(),
        floor=default_floor.strip(),
        purpose=default_purpose.strip(),
    )


def _preview_text(visitors: list[VisitorIn], errors: list[str], info: list[str] | None = None) -> str:
    lines = list(info or [])
    lines.append(f"파싱 결과: {len(visitors)}명 유효, {len(errors)}건 오류\n")
    for i, v in enumerate(visitors, 1):
        lines.append(
            f"  {i}. {v.visitor_name} | {v.visitor_company_name} | "
            f"{v.visitor_mobile} | {v.visitor_email} | "
            f"{v.visit_date} {v.visit_time} | {v.visit_purpose} | {v.floor}층"
        )
    if errors:
        lines.append(f"\n검증 오류 ({len(errors)}건):")
        lines.extend(errors)
    return "\n".join(lines)


def _bulk_summary(result, errors: list[str], dry_run: bool, info: list[str] | None = None) -> str:
    head = "일괄 검증 결과 (dry run, 미제출)" if dry_run else "일괄 등록 결과"
    summary = f"{head}: 총 {result.total}명 중 {result.succeeded}명 성공, {result.failed}명 실패"
    if info:
        summary = "\n".join(info) + "\n" + summary
    if errors:
        summary += f"\n\n파싱 단계에서 건너뛴 행 ({len(errors)}건):\n" + "\n".join(errors)
    if result.failed > 0:
        failed_details = [f"  - {r.visitor_name}: {r.message}" for r in result.results if not r.success]
        summary += "\n\n실패 상세:\n" + "\n".join(failed_details)
    return summary


def _preview_records(records: list[dict], defaults: RowDefaults, participation: str) -> str:
    records, info, err = _apply_participation_filter(records, participation)
    visitors, errors = _build_visitors(records, defaults)
    if err:
        # Show what would be processed, but make the failed filter impossible to miss.
        return err + "\n\n(참석 형태 필터 미적용 미리보기)\n" + _preview_text(visitors, errors)
    return _preview_text(visitors, errors, info)


async def _register_records(
    records: list[dict], defaults: RowDefaults, dry_run: bool, empty_msg: str, participation: str = ""
) -> str:
    if not records:
        return empty_msg
    records, info, err = _apply_participation_filter(records, participation)
    if err:
        return err
    if not records:
        return "\n".join(info) + "\n참석 형태 필터에 해당하는 행이 없어 처리할 방문자가 없습니다."
    visitors, errors = _build_visitors(records, defaults)
    if not visitors:
        return "\n".join(info + ["유효한 방문자 정보가 없습니다.", "검증 오류:"] + errors)
    if len(visitors) > settings.bulk_max_visitors:
        return (
            f"한 번에 최대 {settings.bulk_max_visitors}명까지 등록할 수 있습니다 "
            f"(입력: {len(visitors)}명). 명단을 나눠서 다시 시도해주세요."
        )
    result = await register_bulk(visitors, dry_run=dry_run)
    return _bulk_summary(result, errors, dry_run, info)


_EMPTY_TEXT_MSG = (
    "텍스트에서 방문자 정보를 추출할 수 없습니다.\n"
    "첫 줄에 헤더가 필요합니다. 예시:\n"
    "이름,회사,전화번호,이메일,방문일,방문시간\n"
    "홍길동,ABC회사,01012345678,hong@abc.com,2026-01-15,10:00\n"
    "(방문일/방문시간 컬럼이 없으면 default_visit_date / default_visit_time 인자를 함께 넘기세요)"
)
_EMPTY_FILE_MSG = (
    "파일에서 방문자 정보를 추출할 수 없습니다.\n"
    "헤더 행에 다음 컬럼명이 필요합니다: 이름, 회사, 전화번호, 이메일, 방문일, 방문시간\n"
    "(방문일/방문시간 컬럼이 없으면 default_visit_date / default_visit_time 인자를 함께 넘기세요)"
)



# ── Tools (always available) ──────────────────────────────────────────────

@mcp.tool(description="센터필드 MCP 설정(입주사명, 승인 담당자, 층 목록)을 실제 사이트에 조회해 확인합니다. 예약을 생성하지 않습니다. Keywords: 센터필드 설정 확인, validate configuration, 담당자 확인, dry run, 연결 테스트")
async def validate_configuration() -> str:
    """Check company name / approval contact / floor list against Centerfield without registering anyone."""
    if err := _config_error():
        return err
    summary = settings.public_summary()
    try:
        info = await check_configuration()
    except CenterfieldError as e:
        return (
            "설정 확인 실패: " + str(e) + "\n"
            f"입주사: {summary['company_name']} / 승인 담당자 휴대폰: {summary['person_in_charge_mobile']} / "
            f"빌딩: {summary['building']} / 읽은 .env: {summary['env_files']}"
        )
    floors = ", ".join(f"{k}({v})" for k, v in info["floors"].items())
    return (
        "설정 확인 완료 (예약 미생성)\n"
        f"  입주사: {summary['company_name']} (company_id {info['company_id']})\n"
        f"  승인 담당자: {info['pic_name']} ({summary['person_in_charge_mobile']})\n"
        f"  빌딩: {summary['building']} / 기본 층: {summary['default_floor']}\n"
        f"  선택 가능한 층 키: {floors}\n"
        f"  전송: {summary['transport']} / 파일 도구: {summary['file_tools']} / .env: {summary['env_files']}"
    )


@mcp.tool(description="센터필드 빌딩 방문자 1명을 예약 등록합니다. dry_run=true면 사이트 검증까지만 하고 제출하지 않습니다. Keywords: 센터필드, 방문자 등록, 방문 예약, 방문 신청, visitor registration, centerfield reservation, register visitor, book visitor")
async def register_visitor(
    visitor_name: str,
    visitor_company_name: str,
    visitor_mobile: str,
    visitor_email: str,
    visit_date: str,
    visit_time: str,
    visit_purpose: str = "meeting",
    floor: str = "",
    dry_run: bool = False,
) -> str:
    """Register a single visitor to Centerfield building.

    Args:
        visitor_name: 방문자 이름
        visitor_company_name: 방문자 소속 회사명
        visitor_mobile: 방문자 휴대폰 번호 (예: 01012345678, 010-1234-5678, +82 10-1234-5678)
        visitor_email: 방문자 이메일 주소
        visit_date: 방문 날짜 (YYYY-MM-DD, 오늘 이후)
        visit_time: 방문 시간 (HH:MM, 30분 단위, 08:00~20:00)
        visit_purpose: 방문 목적 (meeting, visit_business, interview, tour, construction, others)
        floor: 방문 층수 (12 또는 18). 생략 시 CF_DEFAULT_FLOOR 값을 사용합니다.
        dry_run: true면 입력 검증 + 사이트 설정 검증(회사/담당자/층)까지만 수행하고 예약을 제출하지 않습니다.
    """
    if err := _config_error():
        return err
    try:
        visitor = VisitorIn(
            visitor_name=visitor_name,
            visitor_company_name=visitor_company_name,
            visitor_mobile=visitor_mobile,
            visitor_email=visitor_email,
            visit_date=visit_date,
            visit_time=visit_time,
            visit_purpose=visit_purpose,
            floor=floor or settings.default_floor,
        )
    except Exception as e:
        return f"입력값 오류: {_short_validation_error(e)}"

    result = await register_single(visitor, dry_run=dry_run)
    label = "검증 완료 (dry run, 미제출)" if dry_run else "예약 완료"
    if result.success:
        return f"{label}: {visitor.visitor_name} ({visitor.visit_date} {visitor.visit_time}, {visitor.floor}층)"
    return f"예약 실패: {visitor.visitor_name} - {result.message}"


@mcp.tool(description="텍스트(복사/붙여넣기)로 방문자 목록을 입력받아 등록 없이 파싱·검증 결과만 보여줍니다. 등록 전에 먼저 호출하세요. Keywords: 센터필드, 방문자 미리보기, 명단 확인, preview visitors, 텍스트 확인, 등록 전 확인")
async def preview_visitors_from_text(
    text: str,
    default_visit_date: str = "",
    default_visit_time: str = "",
    default_floor: str = "",
    default_purpose: str = "",
    participation: str = "",
) -> str:
    """Preview parsed visitor rows from pasted CSV/TSV text without registering.

    Args:
        text: 헤더 포함 방문자 목록 텍스트 (CSV 또는 탭 구분). 헤더는 한/영 자동 매핑 (설문 export 헤더 포함)
        default_visit_date: 행에 방문일이 없을 때 적용할 날짜 (YYYY-MM-DD). 참석자 명단처럼 날짜 컬럼이 없는 입력에 사용
        default_visit_time: 행에 방문시간이 없을 때 적용할 시간 (HH:MM, 30분 단위, 08:00~20:00)
        default_floor: 행에 층이 없을 때 적용할 층 (12 또는 18). 생략 시 CF_DEFAULT_FLOOR
        default_purpose: 행에 목적이 없을 때 적용할 방문 목적. 생략 시 meeting
        participation: 참석 형태 필터 (예: 오프라인). 참석 형태 컬럼('어떤 형태로 참석하시나요?' 등) 값에 이 문자열이 포함된 행만 처리
    """
    if not text.strip():
        return "입력 텍스트가 비어있습니다. 헤더행과 데이터를 포함해주세요."
    records = _parse_csv_text(text, delimiter=_detect_delimiter(text))
    if not records:
        return _EMPTY_TEXT_MSG
    return _preview_records(records, _defaults(default_visit_date, default_visit_time, default_floor, default_purpose), participation)


@mcp.tool(description="텍스트(복사/붙여넣기)로 방문자 목록을 입력받아 일괄 등록합니다. 날짜/시간 컬럼이 없는 참석자 명단은 default_visit_date/default_visit_time을 함께 지정하세요. dry_run=true면 제출하지 않습니다. Keywords: 센터필드, 방문자 등록, 텍스트 입력, 복사 붙여넣기, paste visitors, text registration, 일괄 등록, 방문자 목록")
async def register_visitors_from_text(
    text: str,
    default_visit_date: str = "",
    default_visit_time: str = "",
    default_floor: str = "",
    default_purpose: str = "",
    participation: str = "",
    dry_run: bool = False,
) -> str:
    """Register multiple visitors from pasted text (CSV-like or tab-separated).

    The first line must be a header row (Korean or English; survey-export headers such as
    "Full Name" / "연락처(...)" / "소속/회사 (...)" are recognized).

    Example input:
        이름,회사,전화번호,이메일,방문일,방문시간
        홍길동,ABC주식회사,01012345678,hong@abc.com,2026-11-15,10:00

    Args:
        text: 헤더 포함 방문자 목록 텍스트 (CSV 또는 탭 구분)
        default_visit_date: 행에 방문일이 없을 때 적용할 날짜 (YYYY-MM-DD). 참석자 명단처럼 날짜 컬럼이 없는 입력에 사용
        default_visit_time: 행에 방문시간이 없을 때 적용할 시간 (HH:MM, 30분 단위, 08:00~20:00)
        default_floor: 행에 층이 없을 때 적용할 층 (12 또는 18). 생략 시 CF_DEFAULT_FLOOR
        default_purpose: 행에 목적이 없을 때 적용할 방문 목적. 생략 시 meeting
        participation: 참석 형태 필터 (예: 오프라인). 지정하면 참석 형태 컬럼 값에 이 문자열이 포함된 행만 등록하고, 컬럼이 없으면 등록하지 않고 중단
        dry_run: true면 사이트 검증까지만 수행하고 예약을 제출하지 않습니다
    """
    if err := _config_error():
        return err
    if not text.strip():
        return "입력 텍스트가 비어있습니다. 헤더행과 데이터를 포함해주세요."
    records = _parse_csv_text(text, delimiter=_detect_delimiter(text))
    return await _register_records(
        records, _defaults(default_visit_date, default_visit_time, default_floor, default_purpose), dry_run, _EMPTY_TEXT_MSG,
        participation,
    )


# ── File tools (local/stdio deployments only by default) ─────────────────

async def preview_visitors_from_file(
    file_path: str,
    default_visit_date: str = "",
    default_visit_time: str = "",
    default_floor: str = "",
    default_purpose: str = "",
    participation: str = "",
) -> str:
    """Preview parsed visitor data from a file without registering.

    Args:
        file_path: 파일의 절대 경로 (.xlsx, .csv, .tsv)
        default_visit_date: 행에 방문일이 없을 때 적용할 날짜 (YYYY-MM-DD). 참석자 명단처럼 날짜 컬럼이 없는 입력에 사용
        default_visit_time: 행에 방문시간이 없을 때 적용할 시간 (HH:MM, 30분 단위, 08:00~20:00)
        default_floor: 행에 층이 없을 때 적용할 층 (12 또는 18). 생략 시 CF_DEFAULT_FLOOR
        default_purpose: 행에 목적이 없을 때 적용할 방문 목적. 생략 시 meeting
        participation: 참석 형태 필터 (예: 오프라인). 참석 형태 컬럼('어떤 형태로 참석하시나요?' 등) 값에 이 문자열이 포함된 행만 처리
    """
    records, err = _read_file_records(file_path)
    if err:
        return err
    if not records:
        return _EMPTY_FILE_MSG
    return _preview_records(records, _defaults(default_visit_date, default_visit_time, default_floor, default_purpose), participation)


async def register_visitors_from_file(
    file_path: str,
    default_visit_date: str = "",
    default_visit_time: str = "",
    default_floor: str = "",
    default_purpose: str = "",
    participation: str = "",
    dry_run: bool = False,
) -> str:
    """Register multiple visitors from an Excel (.xlsx) or CSV/TSV file.

    The file must have a header row. Column names can be in Korean or English.

    Args:
        file_path: 파일의 절대 경로 (.xlsx, .csv, .tsv)
        default_visit_date: 행에 방문일이 없을 때 적용할 날짜 (YYYY-MM-DD). 참석자 명단처럼 날짜 컬럼이 없는 입력에 사용
        default_visit_time: 행에 방문시간이 없을 때 적용할 시간 (HH:MM, 30분 단위, 08:00~20:00)
        default_floor: 행에 층이 없을 때 적용할 층 (12 또는 18). 생략 시 CF_DEFAULT_FLOOR
        default_purpose: 행에 목적이 없을 때 적용할 방문 목적. 생략 시 meeting
        participation: 참석 형태 필터 (예: 오프라인). 지정하면 참석 형태 컬럼 값에 이 문자열이 포함된 행만 등록하고, 컬럼이 없으면 등록하지 않고 중단
        dry_run: true면 사이트 검증까지만 수행하고 예약을 제출하지 않습니다
    """
    if err := _config_error():
        return err
    records, err = _read_file_records(file_path)
    if err:
        return err
    return await _register_records(
        records, _defaults(default_visit_date, default_visit_time, default_floor, default_purpose), dry_run, _EMPTY_FILE_MSG,
        participation,
    )


if settings.file_tools_enabled:
    mcp.tool(description="파일(.xlsx/.csv/.tsv)의 방문자 목록을 미리 확인합니다 (실제 등록하지 않음). Keywords: 센터필드, 방문자 미리보기, 파일 확인, preview visitors, 명단 확인, 등록 전 확인")(preview_visitors_from_file)
    mcp.tool(description="Excel/CSV/TSV 파일에서 방문자 목록을 읽어 일괄 등록합니다. 날짜/시간 컬럼이 없으면 default_visit_date/default_visit_time 지정. dry_run=true면 미제출. Keywords: 센터필드, 방문자 일괄 등록, 대량 등록, bulk registration, 엑셀 등록, CSV 등록, 파일로 등록, batch visitor, 방문자 명단")(register_visitors_from_file)


def main():
    # stdio transport: logs go to stderr, never stdout
    logger.info("centerfield-visitor-mcp starting (mcp SDK major=%d, transport=%s)", MCP_MAJOR, settings.transport)
    logger.info("Loaded .env files: %s", settings.loaded_env_files() or "none")
    for problem in settings.startup_problems():
        logger.warning("Configuration problem: %s", problem)
    missing = settings.missing_required()
    if missing:
        logger.warning("Missing required settings: %s — registration tools will refuse to run", ", ".join(missing))
    if settings.transport == "streamable-http":
        logger.info("Serving streamable HTTP on %s:%s%s (file tools %s)",
                    settings.http_host, settings.http_port, settings.http_path,
                    "on" if settings.file_tools_enabled else "off")
    run_server(mcp, settings)


if __name__ == "__main__":
    main()
