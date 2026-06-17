import asyncio
import logging

from .client import CenterfieldClient
from .config import settings
from .exceptions import CenterfieldError
from .models import BulkReservationOut, ReservationResult, VisitorIn

logger = logging.getLogger(__name__)


async def register_single(visitor: VisitorIn) -> ReservationResult:
    try:
        async with CenterfieldClient() as client:
            await client.full_workflow_single(
                visitor_name=visitor.visitor_name,
                visitor_company_name=visitor.visitor_company_name,
                visitor_mobile=visitor.visitor_mobile,
                visitor_email=visitor.visitor_email,
                visit_date=visitor.visit_date.isoformat(),
                visit_time=visitor.visit_time,
                visit_purpose=visitor.visit_purpose,
                floor=visitor.floor,
            )
            return ReservationResult(
                visitor_name=visitor.visitor_name,
                visitor_mobile=visitor.visitor_mobile,
                success=True,
                message="Reservation created successfully",
            )
    except CenterfieldError as e:
        logger.error(f"Registration failed for {visitor.visitor_name}: {e}")
        return ReservationResult(
            visitor_name=visitor.visitor_name,
            visitor_mobile=visitor.visitor_mobile,
            success=False,
            message=str(e),
        )


async def register_bulk(visitors: list[VisitorIn]) -> BulkReservationOut:
    results: list[ReservationResult] = []

    try:
        async with CenterfieldClient() as client:
            await client.initialize_session()
            company_id = await client.search_company(settings.company_name)
            pic = await client.verify_person_in_charge(
                settings.person_in_charge_mobile, company_id
            )
            floor_map = await client.get_floor_list(settings.building, company_id)

            for visitor in visitors:
                try:
                    floor_key = client._resolve_floor_key(visitor.floor, floor_map)
                    payload = {
                        "company_name": settings.company_name,
                        "company_id": company_id,
                        "person_in_charge": pic["name"],
                        "person_in_charge_id": pic["id"],
                        "person_in_charge_mobile": settings.person_in_charge_mobile,
                        "building": settings.building,
                        "building_key": settings.building_key,
                        "floor": floor_key,
                        "floor_key": floor_key,
                        "visitor_name": visitor.visitor_name,
                        "visitor_company_name": visitor.visitor_company_name,
                        "visitor_mobile": visitor.visitor_mobile,
                        "visitor_email": visitor.visitor_email,
                        "visit_date": visitor.visit_date.isoformat(),
                        "visit_time": visitor.visit_time,
                        "visit_purpose": visitor.visit_purpose,
                        "privacy_policy_1": "on",
                        "privacy_policy_2": "on",
                    }
                    await client.submit_reservation(payload)
                    results.append(
                        ReservationResult(
                            visitor_name=visitor.visitor_name,
                            visitor_mobile=visitor.visitor_mobile,
                            success=True,
                            message="Reservation created successfully",
                        )
                    )
                except CenterfieldError as e:
                    logger.error(f"Bulk item failed for {visitor.visitor_name}: {e}")
                    results.append(
                        ReservationResult(
                            visitor_name=visitor.visitor_name,
                            visitor_mobile=visitor.visitor_mobile,
                            success=False,
                            message=str(e),
                        )
                    )

                await asyncio.sleep(settings.request_delay)

    except CenterfieldError as e:
        logger.error(f"Bulk registration session setup failed: {e}")
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
