import logging
import re

import httpx
from bs4 import BeautifulSoup

from .config import settings
from .exceptions import (
    CompanyNotFoundError,
    FloorListError,
    PersonInChargeVerificationError,
    ReservationOutcomeUnknownError,
    ReservationSubmissionError,
    SessionInitError,
)

logger = logging.getLogger(__name__)

# Transport errors raised before any request byte can have reached the site.
_NOT_SENT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.UnsupportedProtocol,
    httpx.LocalProtocolError,
)


def _success_value(value) -> bool | None:
    """True / False for an explicit site verdict, None when the value is not recognisable."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
    if isinstance(value, str):
        return {"true": True, "1": True, "y": True, "false": False, "0": False, "n": False}.get(
            value.strip().lower()
        )
    return None


class CenterfieldClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._csrf_token: str = ""
        self._csrf_field_name: str = "csrf_centerfield_name"

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _sync_csrf_from_cookie(self):
        cookie_val = self._client.cookies.get("csrf_cookie_centerfield")
        if cookie_val:
            self._csrf_token = cookie_val

    async def initialize_session(self) -> None:
        url = f"{settings.centerfield_base_url}/visitor-reservation-registration"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SessionInitError(f"Failed to load reservation page: {e}")

        soup = BeautifulSoup(resp.text, "lxml")
        csrf_input = soup.find("input", {"name": "csrf_centerfield_name"})
        if not csrf_input:
            raise SessionInitError("CSRF token not found in page HTML")
        self._csrf_token = csrf_input.get("value", "")
        if not self._csrf_token:
            raise SessionInitError("CSRF token value is empty")
        logger.info("Session initialized, CSRF token acquired")

    async def search_company(self, company_name: str) -> str:
        url = f"{settings.centerfield_base_url}/ajax/getCompanyList"
        data = {
            self._csrf_field_name: self._csrf_token,
            "company_name": company_name,
            "language": "ko",
            "signup_true": "",
            "visitor_allow_true": "y",
        }
        try:
            resp = await self._client.post(url, data=data)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise CompanyNotFoundError(f"Company search request failed: {e}")

        self._sync_csrf_from_cookie()

        html = resp.text
        if not html or not html.strip():
            raise CompanyNotFoundError(f"No company found for: {company_name}")

        soup = BeautifulSoup(html, "lxml")
        a_tag = soup.find("a", {"data-compid": True})
        if a_tag:
            company_id = a_tag.get("data-compid")
            logger.info("Found company_id: %s", company_id)
            return company_id

        li = soup.find("li")
        if li:
            company_id = li.get("data-id") or li.get("data-compid")
            if company_id:
                logger.info("Found company_id from li: %s", company_id)
                return company_id

        for tag in soup.find_all(["a", "li"]):
            onclick = tag.get("onclick", "")
            match = re.search(r"(\d+)", onclick)
            if match:
                company_id = match.group(1)
                logger.info("Found company_id from onclick: %s", company_id)
                return company_id

        raise CompanyNotFoundError(
            f"Could not extract company_id from the company search response ({len(html)} chars)"
        )

    async def verify_person_in_charge(self, mobile: str, company_id: str) -> dict:
        url = f"{settings.centerfield_base_url}/reservation/ajaxPersonInchargeMobileCheck"
        data = {
            self._csrf_field_name: self._csrf_token,
            "mobile": mobile,
            "company_id": company_id,
        }
        try:
            resp = await self._client.post(url, data=data)
            resp.raise_for_status()
            result = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PersonInChargeVerificationError(f"PIC verification failed: {e}")

        self._sync_csrf_from_cookie()

        if not result.get("success"):
            error_msg = result.get("error_message", "Unknown error")
            raise PersonInChargeVerificationError(
                f"PIC verification rejected: {error_msg}"
            )

        return {"name": result["name"], "id": str(result["id"])}

    async def get_floor_list(self, building_type: str, company_id: str) -> dict[str, str]:
        url = f"{settings.centerfield_base_url}/ajax/getFloorList"
        data = {
            self._csrf_field_name: self._csrf_token,
            "building_type": building_type,
            "company_id": company_id,
            "language": "ko",
        }
        try:
            resp = await self._client.post(url, data=data)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise FloorListError(f"Floor list request failed: {e}")

        self._sync_csrf_from_cookie()

        raw = resp.text
        if "*" in raw:
            parts = raw.split("*")
            floor_html = parts[0]
        else:
            floor_html = raw

        soup = BeautifulSoup(floor_html, "lxml")
        floors = {}
        for tag in soup.find_all(["li", "a"], {"data-key": True}):
            key = tag.get("data-key", "")
            name = tag.get("data-floorname", "") or tag.get_text(strip=True)
            if key:
                floors[key] = name

        if not floors and "*" in raw:
            parts = raw.split("*")
            if len(parts) >= 3:
                floors["raw_key"] = parts[1].strip()
                floors["raw_value"] = parts[2].strip()

        return floors

    async def submit_reservation(self, payload: dict) -> dict:
        """Submit one reservation.

        Returns the site's JSON object when it answered ``success: true``.
        Raises ReservationSubmissionError when the reservation was definitely not created
        (connection never established, unambiguous 4xx, explicit ``success: false``) and
        ReservationOutcomeUnknownError when the request may have been processed but the
        outcome could not be confirmed (see that class). Messages never contain the
        site's raw response body.
        """
        url = f"{settings.centerfield_base_url}/reservation/ajaxVistorReservation"
        payload[self._csrf_field_name] = self._csrf_token
        payload["timezone_offset_minutes"] = "-540"

        try:
            resp = await self._client.post(url, data=payload)
        except _NOT_SENT_ERRORS as e:
            raise ReservationSubmissionError(
                f"Reservation not sent: {type(e).__name__} (connection was not established)"
            ) from None
        except httpx.HTTPError as e:
            # Read/write timeouts, read/write errors, remote protocol errors, ...: the request
            # may already have been processed by the site.
            raise ReservationOutcomeUnknownError(
                f"Reservation outcome unknown: {type(e).__name__} after the request was sent"
            ) from None

        status = resp.status_code
        if status in (408, 429):
            raise ReservationOutcomeUnknownError(
                f"Reservation outcome unknown: HTTP {status} from the site", status_code=status
            )
        if 400 <= status < 500:
            raise ReservationSubmissionError(f"Reservation rejected: HTTP {status}", status_code=status)
        if not 200 <= status < 300:
            raise ReservationOutcomeUnknownError(
                f"Reservation outcome unknown: HTTP {status} from the site", status_code=status
            )

        self._sync_csrf_from_cookie()

        try:
            result = resp.json()
        except ValueError:
            raise ReservationOutcomeUnknownError(
                f"Reservation outcome unknown: response is not JSON ({len(resp.content)} bytes)",
                status_code=status,
            ) from None
        if not isinstance(result, dict) or "success" not in result:
            raise ReservationOutcomeUnknownError(
                "Reservation outcome unknown: response has no 'success' field", status_code=status
            )

        verdict = _success_value(result["success"])
        if verdict is True:
            return result
        if verdict is False:
            error_msg = result.get("error_message") or result.get("message") or "Unknown"
            raise ReservationSubmissionError(f"Reservation rejected: {error_msg}", status_code=status)
        raise ReservationOutcomeUnknownError(
            "Reservation outcome unknown: unrecognised 'success' value", status_code=status
        )

    # ── Composite flows ─────────────────────────────────────────────────

    async def prepare(self) -> dict:
        """Read-only part of the flow: session, company, approval contact, floors.

        Returns {"company_id", "pic": {"name","id"}, "floors": {key: label}}.
        Nothing is submitted, so this is safe for configuration checks and dry runs.
        """
        await self.initialize_session()
        company_id = await self.search_company(settings.company_name)
        pic = await self.verify_person_in_charge(settings.person_in_charge_mobile, company_id)
        floors = await self.get_floor_list(settings.building, company_id)
        if not floors:
            raise FloorListError("Floor list is empty for this company/building")
        return {"company_id": company_id, "pic": pic, "floors": floors}

    def build_payload(self, context: dict, *, visitor_name: str, visitor_company_name: str,
                      visitor_mobile: str, visitor_email: str, visit_date: str,
                      visit_time: str, visit_purpose: str, floor: str) -> dict:
        floor_key = self._resolve_floor_key(floor, context["floors"])
        return {
            "company_name": settings.company_name,
            "company_id": context["company_id"],
            "person_in_charge": context["pic"]["name"],
            "person_in_charge_id": context["pic"]["id"],
            "person_in_charge_mobile": settings.person_in_charge_mobile,
            "building": settings.building,
            "building_key": settings.building_key,
            "floor": floor_key,
            "floor_key": floor_key,
            "visitor_name": visitor_name,
            "visitor_company_name": visitor_company_name,
            "visitor_mobile": visitor_mobile,
            "visitor_email": visitor_email,
            "visit_date": visit_date,
            "visit_time": visit_time,
            "visit_purpose": visit_purpose,
            "privacy_policy_1": "on",
            "privacy_policy_2": "on",
        }

    async def full_workflow_single(self, **visitor_fields) -> dict:
        context = await self.prepare()
        payload = self.build_payload(context, **visitor_fields)
        return await self.submit_reservation(payload)

    @staticmethod
    def _resolve_floor_key(floor: str, floor_map: dict[str, str]) -> str:
        """Map a floor number ("12"/"18") to the site's floor key.

        Matches a key whose trailing digits equal the floor (e.g. ``lower_floor12``),
        falling back to a label match (e.g. ``12층``). Raises FloorListError instead of
        guessing a key the site may not accept.
        """
        wanted = floor.strip()
        for key in floor_map:
            digits = re.search(r"(\d+)\s*$", key)
            if digits and digits.group(1) == wanted:
                return key
        for key, label in floor_map.items():
            digits = re.search(r"(\d+)", label or "")
            if digits and digits.group(1) == wanted:
                return key
        raise FloorListError(
            f"Floor {wanted} not offered for this company (available: {', '.join(floor_map) or 'none'})"
        )
