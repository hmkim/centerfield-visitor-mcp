import asyncio
import logging

from .client import CenterfieldClient
from .config import settings
from .exceptions import CenterfieldError, ReservationOutcomeUnknownError
from .models import BulkReservationOut, ReservationResult, VisitorIn

logger = logging.getLogger(__name__)

DRY_RUN_MESSAGE = "Dry run: validated against Centerfield, not submitted"
SUCCESS_MESSAGE = "Reservation created successfully"
UNKNOWN_ADVICE = (
    "예약이 이미 생성됐을 수 있습니다. 자동 재시도 금지: 다시 시도하지 마세요. "
    "센터필드 앱/사이트에서 예약 여부를 먼저 확인하세요."
)
NOT_SUBMITTED_MESSAGE = (
    "미제출(NOT_SUBMITTED): 앞선 행의 결과가 불명이라 제출하지 않았습니다. "
    "결과 불명 행을 확인한 뒤 새 preview와 승인을 거쳐 등록하세요."
)


def _fields(visitor: VisitorIn) -> dict:
    return dict(
        visitor_name=visitor.visitor_name,
        visitor_company_name=visitor.visitor_company_name,
        visitor_mobile=visitor.visitor_mobile,
        visitor_email=visitor.visitor_email,
        visit_date=visitor.visit_date.isoformat(),
        visit_time=visitor.visit_time,
        visit_purpose=visitor.visit_purpose,
        floor=visitor.floor,
    )


def _log_error(context: str, exc: CenterfieldError) -> None:
    """Log the error class and HTTP status only: never the site's text or visitor data."""
    status = getattr(exc, "status_code", None)
    logger.error("%s: %s%s", context, type(exc).__name__, f" (HTTP {status})" if status else "")


def _result(visitor: VisitorIn, status: str, message: str) -> ReservationResult:
    return ReservationResult(
        visitor_name=visitor.visitor_name,
        visitor_mobile=visitor.visitor_mobile,
        success=status == "SUCCEEDED",
        status=status,
        message=message,
    )


def _unknown(visitor: VisitorIn, exc: ReservationOutcomeUnknownError) -> ReservationResult:
    return _result(visitor, "UNKNOWN", f"{exc} — {UNKNOWN_ADVICE}")


async def check_configuration() -> dict:
    """Verify company / approval contact / floors against the live site. No submission.

    Returns {"company_id", "pic_name", "floors": {key: label}}. Raises CenterfieldError.
    """
    async with CenterfieldClient() as client:
        ctx = await client.prepare()
    return {"company_id": ctx["company_id"], "pic_name": ctx["pic"]["name"], "floors": ctx["floors"]}


async def register_single(visitor: VisitorIn, *, dry_run: bool = False) -> ReservationResult:
    try:
        async with CenterfieldClient() as client:
            ctx = await client.prepare()
            payload = client.build_payload(ctx, **_fields(visitor))
            if dry_run:
                return _result(visitor, "SUCCEEDED", DRY_RUN_MESSAGE)
            await client.submit_reservation(payload)
            return _result(visitor, "SUCCEEDED", SUCCESS_MESSAGE)
    except ReservationOutcomeUnknownError as e:
        _log_error("Registration outcome unknown (single)", e)
        return _unknown(visitor, e)
    except CenterfieldError as e:
        _log_error("Registration failed (single)", e)
        return _result(visitor, "FAILED", str(e))


def _bulk_out(visitors: list[VisitorIn], results: list[ReservationResult], stopped: bool) -> BulkReservationOut:
    def count(status: str) -> int:
        return sum(1 for r in results if r.status == status)

    return BulkReservationOut(
        total=len(visitors),
        succeeded=count("SUCCEEDED"),
        failed=count("FAILED"),
        unknown=count("UNKNOWN"),
        not_submitted=count("NOT_SUBMITTED"),
        stopped_on_unknown=stopped,
        results=results,
    )


async def register_bulk(visitors: list[VisitorIn], *, dry_run: bool = False) -> BulkReservationOut:
    """Submit visitors one by one; stop at the first UNKNOWN and mark the rest NOT_SUBMITTED."""
    results: list[ReservationResult] = []
    stopped = False

    try:
        async with CenterfieldClient() as client:
            ctx = await client.prepare()

            for index, visitor in enumerate(visitors, 1):
                try:
                    payload = client.build_payload(ctx, **_fields(visitor))
                    if dry_run:
                        results.append(_result(visitor, "SUCCEEDED", DRY_RUN_MESSAGE))
                    else:
                        await client.submit_reservation(payload)
                        results.append(_result(visitor, "SUCCEEDED", SUCCESS_MESSAGE))
                except ReservationOutcomeUnknownError as e:
                    _log_error(f"Bulk item {index} outcome unknown; stopping", e)
                    results.append(_unknown(visitor, e))
                    stopped = True
                    break
                except CenterfieldError as e:
                    _log_error(f"Bulk item {index} failed", e)
                    results.append(_result(visitor, "FAILED", str(e)))

                if not dry_run and index < len(visitors):
                    await asyncio.sleep(settings.request_delay)

    except CenterfieldError as e:
        # Only prepare() can get here: nothing has been submitted yet.
        _log_error("Bulk registration session setup failed", e)
        for visitor in visitors[len(results):]:
            results.append(_result(visitor, "FAILED", f"Session setup failed: {e}"))

    if stopped:
        for visitor in visitors[len(results):]:
            results.append(_result(visitor, "NOT_SUBMITTED", NOT_SUBMITTED_MESSAGE))

    return _bulk_out(visitors, results, stopped)
