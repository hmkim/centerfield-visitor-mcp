import logging
import re

import httpx
from bs4 import BeautifulSoup

from .config import settings
from .exceptions import (
    CompanyNotFoundError,
    FloorListError,
    PersonInChargeVerificationError,
    ReservationSubmissionError,
    SessionInitError,
)

logger = logging.getLogger(__name__)


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
            logger.info(f"Found company_id: {company_id}")
            return company_id

        li = soup.find("li")
        if li:
            company_id = li.get("data-id") or li.get("data-compid")
            if company_id:
                logger.info(f"Found company_id from li: {company_id}")
                return company_id

        for tag in soup.find_all(["a", "li"]):
            onclick = tag.get("onclick", "")
            match = re.search(r"(\d+)", onclick)
            if match:
                company_id = match.group(1)
                logger.info(f"Found company_id from onclick: {company_id}")
                return company_id

        raise CompanyNotFoundError(
            f"Could not extract company_id from HTML. Response: {html[:500]}"
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
        url = f"{settings.centerfield_base_url}/reservation/ajaxVistorReservation"
        payload[self._csrf_field_name] = self._csrf_token
        payload["timezone_offset_minutes"] = "-540"

        try:
            resp = await self._client.post(url, data=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ReservationSubmissionError(f"Reservation submission failed: {e}")

        self._sync_csrf_from_cookie()

        try:
            result = resp.json()
        except ValueError:
            raise ReservationSubmissionError(
                f"Invalid JSON response: {resp.text[:300]}"
            )

        if not result.get("success"):
            error_msg = result.get("error_message", result.get("message", "Unknown"))
            raise ReservationSubmissionError(f"Reservation rejected: {error_msg}")

        return result

    async def full_workflow_single(
        self,
        visitor_name: str,
        visitor_company_name: str,
        visitor_mobile: str,
        visitor_email: str,
        visit_date: str,
        visit_time: str,
        visit_purpose: str,
        floor: str,
    ) -> dict:
        await self.initialize_session()
        company_id = await self.search_company(settings.company_name)
        pic = await self.verify_person_in_charge(
            settings.person_in_charge_mobile, company_id
        )
        floor_map = await self.get_floor_list(settings.building, company_id)
        floor_key = self._resolve_floor_key(floor, floor_map)

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

        return await self.submit_reservation(payload)

    def _resolve_floor_key(self, floor: str, floor_map: dict[str, str]) -> str:
        for key in floor_map:
            if floor in key:
                return key
        return f"lower_floor{floor}"
