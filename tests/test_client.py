from __future__ import annotations

import httpx
import pytest
import respx

from centerfield_visitor_mcp import service
from centerfield_visitor_mcp.client import CenterfieldClient
from centerfield_visitor_mcp.exceptions import (
    CompanyNotFoundError,
    FloorListError,
    PersonInChargeVerificationError,
    ReservationSubmissionError,
    SessionInitError,
)
from centerfield_visitor_mcp.models import VisitorIn

BASE = "https://cf.test"
PAGE_HTML = '<html><form><input type="hidden" name="csrf_centerfield_name" value="tok-1"></form></html>'
COMPANY_HTML = '<ul><li><a href="#" data-compid="4242">Test Tenant Inc.</a></li></ul>'
FLOOR_HTML = '<li data-key="lower_floor12" data-floorname="12층">12층</li><li data-key="upper_floor18" data-floorname="18층">18층</li>*x*y'


def mock_happy_path(router: respx.Router, submit_json=None):
    router.get(f"{BASE}/visitor-reservation-registration").mock(return_value=httpx.Response(200, text=PAGE_HTML))
    router.post(f"{BASE}/ajax/getCompanyList").mock(return_value=httpx.Response(200, text=COMPANY_HTML))
    router.post(f"{BASE}/reservation/ajaxPersonInchargeMobileCheck").mock(
        return_value=httpx.Response(200, json={"success": True, "name": "담당자", "id": 77})
    )
    router.post(f"{BASE}/ajax/getFloorList").mock(return_value=httpx.Response(200, text=FLOOR_HTML))
    return router.post(f"{BASE}/reservation/ajaxVistorReservation").mock(
        return_value=httpx.Response(200, json=submit_json or {"success": True})
    )


@pytest.fixture
def visitor(visitor_kwargs) -> VisitorIn:
    return VisitorIn(**visitor_kwargs, floor="18")


# ── initialize_session ────────────────────────────────────────────────────

@respx.mock
async def test_initialize_session_extracts_csrf():
    respx.get(f"{BASE}/visitor-reservation-registration").mock(return_value=httpx.Response(200, text=PAGE_HTML))
    async with CenterfieldClient() as c:
        await c.initialize_session()
        assert c._csrf_token == "tok-1"


@respx.mock
@pytest.mark.parametrize("html", ["<html>no input</html>", '<input name="csrf_centerfield_name" value="">'])
async def test_initialize_session_missing_token(html):
    respx.get(f"{BASE}/visitor-reservation-registration").mock(return_value=httpx.Response(200, text=html))
    async with CenterfieldClient() as c:
        with pytest.raises(SessionInitError):
            await c.initialize_session()


@respx.mock
async def test_initialize_session_http_error():
    respx.get(f"{BASE}/visitor-reservation-registration").mock(return_value=httpx.Response(503))
    async with CenterfieldClient() as c:
        with pytest.raises(SessionInitError):
            await c.initialize_session()


@respx.mock
async def test_csrf_cookie_refresh_is_used_on_next_request():
    respx.get(f"{BASE}/visitor-reservation-registration").mock(return_value=httpx.Response(200, text=PAGE_HTML))
    respx.post(f"{BASE}/ajax/getCompanyList").mock(
        return_value=httpx.Response(200, text=COMPANY_HTML, headers={"set-cookie": "csrf_cookie_centerfield=tok-2; Path=/"})
    )
    pic = respx.post(f"{BASE}/reservation/ajaxPersonInchargeMobileCheck").mock(
        return_value=httpx.Response(200, json={"success": True, "name": "n", "id": 1})
    )
    async with CenterfieldClient() as c:
        await c.initialize_session()
        await c.search_company("Test Tenant Inc.")
        assert c._csrf_token == "tok-2"
        await c.verify_person_in_charge("01000000000", "4242")
    assert "csrf_centerfield_name=tok-2" in pic.calls.last.request.content.decode()


# ── search_company ────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.parametrize(
    "html, expected",
    [
        (COMPANY_HTML, "4242"),
        ('<ul><li data-id="55">X</li></ul>', "55"),
        ('<ul><li onclick="selectCompany(99)">X</li></ul>', "99"),
    ],
)
async def test_search_company_variants(html, expected):
    respx.post(f"{BASE}/ajax/getCompanyList").mock(return_value=httpx.Response(200, text=html))
    async with CenterfieldClient() as c:
        assert await c.search_company("x") == expected


@respx.mock
@pytest.mark.parametrize("html", ["", "   ", "<ul><li>no id here</li></ul>"])
async def test_search_company_not_found(html):
    respx.post(f"{BASE}/ajax/getCompanyList").mock(return_value=httpx.Response(200, text=html))
    async with CenterfieldClient() as c:
        with pytest.raises(CompanyNotFoundError):
            await c.search_company("x")


@respx.mock
async def test_search_company_sends_expected_form():
    route = respx.post(f"{BASE}/ajax/getCompanyList").mock(return_value=httpx.Response(200, text=COMPANY_HTML))
    async with CenterfieldClient() as c:
        c._csrf_token = "tok"
        await c.search_company("Test Tenant Inc.")
    body = route.calls.last.request.content.decode()
    assert "company_name=Test+Tenant+Inc." in body and "visitor_allow_true=y" in body and "csrf_centerfield_name=tok" in body


# ── verify_person_in_charge ───────────────────────────────────────────────

@respx.mock
async def test_verify_pic_success():
    respx.post(f"{BASE}/reservation/ajaxPersonInchargeMobileCheck").mock(
        return_value=httpx.Response(200, json={"success": True, "name": "담당자", "id": 77})
    )
    async with CenterfieldClient() as c:
        assert await c.verify_person_in_charge("01000000000", "4242") == {"name": "담당자", "id": "77"}


@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json={"success": False, "error_message": "등록되지 않은 번호"}), httpx.Response(200, text="not json"), httpx.Response(500)],
)
async def test_verify_pic_failures(response):
    respx.post(f"{BASE}/reservation/ajaxPersonInchargeMobileCheck").mock(return_value=response)
    async with CenterfieldClient() as c:
        with pytest.raises(PersonInChargeVerificationError):
            await c.verify_person_in_charge("01000000000", "4242")


# ── get_floor_list / floor key ────────────────────────────────────────────

@respx.mock
async def test_get_floor_list_parses_keys():
    respx.post(f"{BASE}/ajax/getFloorList").mock(return_value=httpx.Response(200, text=FLOOR_HTML))
    async with CenterfieldClient() as c:
        assert await c.get_floor_list("east", "4242") == {"lower_floor12": "12층", "upper_floor18": "18층"}


@respx.mock
async def test_get_floor_list_star_fallback():
    respx.post(f"{BASE}/ajax/getFloorList").mock(return_value=httpx.Response(200, text="<p>none</p>*KEY*VALUE"))
    async with CenterfieldClient() as c:
        assert await c.get_floor_list("east", "4242") == {"raw_key": "KEY", "raw_value": "VALUE"}


def test_resolve_floor_key_by_key_digits_and_label():
    floors = {"lower_floor12": "12층", "upper_floor18": "18층"}
    assert CenterfieldClient._resolve_floor_key("12", floors) == "lower_floor12"
    assert CenterfieldClient._resolve_floor_key("18", floors) == "upper_floor18"
    assert CenterfieldClient._resolve_floor_key("18", {"k1": "12층", "k2": "18층"}) == "k2"


def test_resolve_floor_key_does_not_guess():
    with pytest.raises(FloorListError):
        CenterfieldClient._resolve_floor_key("18", {})
    with pytest.raises(FloorListError):
        CenterfieldClient._resolve_floor_key("18", {"lower_floor12": "12층"})
    with pytest.raises(FloorListError):
        CenterfieldClient._resolve_floor_key("1", {"lower_floor12": "12층", "upper_floor18": "18층"})


# ── submit_reservation ────────────────────────────────────────────────────

@respx.mock
async def test_submit_reservation_payload_and_success():
    route = respx.post(f"{BASE}/reservation/ajaxVistorReservation").mock(return_value=httpx.Response(200, json={"success": True}))
    async with CenterfieldClient() as c:
        c._csrf_token = "tok"
        assert await c.submit_reservation({"visitor_name": "홍길동"}) == {"success": True}
    body = route.calls.last.request.content.decode()
    assert "timezone_offset_minutes=-540" in body and "csrf_centerfield_name=tok" in body


@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json={"success": False, "error_message": "중복 예약"}), httpx.Response(200, text="<html>"), httpx.Response(502)],
)
async def test_submit_reservation_failures(response):
    respx.post(f"{BASE}/reservation/ajaxVistorReservation").mock(return_value=response)
    async with CenterfieldClient() as c:
        with pytest.raises(ReservationSubmissionError):
            await c.submit_reservation({})


# ── prepare / build_payload ───────────────────────────────────────────────

@respx.mock
async def test_prepare_and_build_payload(visitor):
    mock_happy_path(respx)
    async with CenterfieldClient() as c:
        ctx = await c.prepare()
        payload = c.build_payload(ctx, **service._fields(visitor))
    assert ctx["company_id"] == "4242" and ctx["pic"] == {"name": "담당자", "id": "77"}
    assert payload["floor"] == payload["floor_key"] == "upper_floor18"
    assert payload["person_in_charge_mobile"] == "01000000000"
    assert payload["privacy_policy_1"] == payload["privacy_policy_2"] == "on"
    assert payload["visit_date"] == visitor.visit_date.isoformat()


@respx.mock
async def test_prepare_rejects_empty_floor_list():
    mock_happy_path(respx)
    respx.post(f"{BASE}/ajax/getFloorList").mock(return_value=httpx.Response(200, text="<p></p>"))
    async with CenterfieldClient() as c:
        with pytest.raises(FloorListError):
            await c.prepare()


# ── service layer ─────────────────────────────────────────────────────────

@respx.mock
async def test_register_single_success_and_dry_run(visitor):
    submit = mock_happy_path(respx)
    ok = await service.register_single(visitor)
    assert ok.success and submit.call_count == 1
    dry = await service.register_single(visitor, dry_run=True)
    assert dry.success and dry.message == service.DRY_RUN_MESSAGE and submit.call_count == 1


@respx.mock
async def test_register_single_reports_rejection(visitor):
    mock_happy_path(respx, submit_json={"success": False, "error_message": "시간 초과"})
    res = await service.register_single(visitor)
    assert not res.success and "시간 초과" in res.message


@respx.mock
async def test_register_bulk_isolates_failures_and_keeps_order(visitor_kwargs):
    submit = mock_happy_path(respx)
    submit.side_effect = [
        httpx.Response(200, json={"success": True}),
        httpx.Response(200, json={"success": False, "error_message": "중복"}),
        httpx.Response(200, json={"success": True}),
    ]
    visitors = [
        VisitorIn(**{**visitor_kwargs, "visitor_name": f"v{i}", "visitor_mobile": f"0101111{i:04d}"}) for i in range(3)
    ]
    out = await service.register_bulk(visitors)
    assert (out.total, out.succeeded, out.failed) == (3, 2, 1)
    assert [r.visitor_name for r in out.results] == ["v0", "v1", "v2"]
    assert not out.results[1].success and "중복" in out.results[1].message
    assert submit.call_count == 3


@respx.mock
async def test_register_bulk_session_setup_failure_marks_all(visitor_kwargs):
    respx.get(f"{BASE}/visitor-reservation-registration").mock(return_value=httpx.Response(500))
    visitors = [VisitorIn(**{**visitor_kwargs, "visitor_mobile": f"0101111{i:04d}"}) for i in range(2)]
    out = await service.register_bulk(visitors)
    assert out.failed == 2 and all("Session setup failed" in r.message for r in out.results)


@respx.mock
async def test_register_bulk_dry_run_never_submits(visitor_kwargs):
    submit = mock_happy_path(respx)
    visitors = [VisitorIn(**{**visitor_kwargs, "visitor_mobile": f"0101111{i:04d}"}) for i in range(2)]
    out = await service.register_bulk(visitors, dry_run=True)
    assert out.succeeded == 2 and submit.call_count == 0


@respx.mock
async def test_register_bulk_floor_not_offered_is_per_row_failure(visitor_kwargs):
    submit = mock_happy_path(respx)
    respx.post(f"{BASE}/ajax/getFloorList").mock(
        return_value=httpx.Response(200, text='<li data-key="lower_floor12" data-floorname="12층">12층</li>')
    )
    visitors = [VisitorIn(**visitor_kwargs, floor="18"), VisitorIn(**{**visitor_kwargs, "visitor_mobile": "01099990000"}, floor="12")]
    out = await service.register_bulk(visitors)
    assert out.succeeded == 1 and out.failed == 1 and "Floor 18" in out.results[0].message
    assert submit.call_count == 1


@respx.mock
async def test_check_configuration_returns_context():
    mock_happy_path(respx)
    info = await service.check_configuration()
    assert info == {"company_id": "4242", "pic_name": "담당자", "floors": {"lower_floor12": "12층", "upper_floor18": "18층"}}
