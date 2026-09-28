import asyncio
import logging

from .client import CenterfieldClient
from .config import settings
from .exceptions import CenterfieldError
from .models import BulkReservationOut, ReservationResult, VisitorIn

logger = logging.getLogger(__name__)

DRY_RUN_MESSAGE = "Dry run: validated against Centerfield, not submitted"


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
                message = DRY_RUN_MESSAGE
            else:
                await client.submit_reservation(payload)
                message = "Reservation created successfully"
            return ReservationResult(
                visitor_name=visitor.visitor_name,
                visitor_mobile=visitor.visitor_mobile,
                success=True,
                message=message,
            )
    except CenterfieldError as e:
        logger.error("Registration failed (single): %s", e)
        return ReservationResult(
            visitor_name=visitor.visitor_name,
            visitor_mobile=visitor.visitor_mobile,
            success=False,
            message=str(e),
        )


async def register_bulk(visitors: list[VisitorIn], *, dry_run: bool = False) -> BulkReservationOut:
    results: list[ReservationResult] = []

    try:
        async with CenterfieldClient() as client:
            ctx = await client.prepare()

            for index, visitor in enumerate(visitors, 1):
                try:
                    payload = client.build_payload(ctx, **_fields(visitor))
                    if dry_run:
                        message = DRY_RUN_MESSAGE
                    else:
                        await client.submit_reservation(payload)
                        message = "Reservation created successfully"
                    results.append(
                        ReservationResult(
                            visitor_name=visitor.visitor_name,
                            visitor_mobile=visitor.visitor_mobile,
                            success=True,
                            message=message,
                        )
                    )
                except CenterfieldError as e:
                    logger.error("Bulk item %d failed: %s", index, e)
                    results.append(
                        ReservationResult(
                            visitor_name=visitor.visitor_name,
                            visitor_mobile=visitor.visitor_mobile,
                            success=False,
                            message=str(e),
                        )
                    )

                if not dry_run and index < len(visitors):
                    await asyncio.sleep(settings.request_delay)

    except CenterfieldError as e:
        logger.error("Bulk registration session setup failed: %s", e)
        for visitor in visitors[len(results):]:
            results.append(
                ReservationResult(
                    visitor_name=visitor.visitor_name,
                    visitor_mobile=visitor.visitor_mobile,
                    success=False,
                    message=f"Session setup failed: {e}",
                )
            )

    succeeded = sum(1 for r in results if r.success)
    return BulkReservationOut(
        total=len(visitors),
        succeeded=succeeded,
        failed=len(visitors) - succeeded,
        results=results,
    )
