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
    ReservationOutcomeUnknownError,
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
    payload = {"visitor_name": "홍길동"}
    async with CenterfieldClient() as c:
        c._csrf_token = "tok"
        assert await c.submit_reservation(payload) == {"success": True}
    assert payload == {"visitor_name": "홍길동"}
    body = route.calls.last.request.content.decode()
    assert "timezone_offset_minutes=-540" in body and "csrf_centerfield_name=tok" in body


SUBMIT_URL = f"{BASE}/reservation/ajaxVistorReservation"


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"success": False, "error_message": "중복 예약"}),
        httpx.Response(200, json={"success": "false", "message": "거절"}),
        httpx.Response(200, json={"success": 0}),
        httpx.Response(400),
        httpx.Response(403, text="<html>forbidden</html>"),
        httpx.Response(404),
    ],
)
async def test_submit_reservation_definite_failures(response):
    """Explicit reject and unambiguous 4xx: the reservation was not created -> FAILED class."""
    respx.post(SUBMIT_URL).mock(return_value=response)
    async with CenterfieldClient() as c:
        with pytest.raises(ReservationSubmissionError) as exc:
            await c.submit_reservation({})
    assert not isinstance(exc.value, ReservationOutcomeUnknownError)


@respx.mock
@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.ConnectTimeout("connect timed out"), httpx.PoolTimeout("pool")],
)
async def test_submit_reservation_not_sent_is_failure(error):
    respx.post(SUBMIT_URL).mock(side_effect=error)
    async with CenterfieldClient() as c:
        with pytest.raises(ReservationSubmissionError, match="not sent"):
            await c.submit_reservation({})


@respx.mock
@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.WriteTimeout("write timed out"),
        httpx.ReadError("connection reset"),
        httpx.WriteError("broken pipe"),
        httpx.RemoteProtocolError("server disconnected without sending a response"),
    ],
)
async def test_submit_reservation_transport_errors_after_send_are_unknown(error):
    respx.post(SUBMIT_URL).mock(side_effect=error)
    async with CenterfieldClient() as c:
        with pytest.raises(ReservationOutcomeUnknownError) as exc:
            await c.submit_reservation({})
    assert type(error).__name__ in str(exc.value)
    assert not isinstance(exc.value, ReservationSubmissionError)


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(408),
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(502, text="<html>bad gateway</html>"),
        httpx.Response(503),
        httpx.Response(504),
        httpx.Response(200, text="<html>login page</html>"),
        httpx.Response(200, text=""),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(200, json={"result": "ok"}),
        httpx.Response(200, json={"success": None}),
        httpx.Response(200, json={"success": "maybe"}),
    ],
)
async def test_submit_reservation_unconfirmed_responses_are_unknown(response):
    respx.post(SUBMIT_URL).mock(return_value=response)
    async with CenterfieldClient() as c:
        with pytest.raises(ReservationOutcomeUnknownError):
            await c.submit_reservation({})


@respx.mock
@pytest.mark.parametrize("value", [True, "true", 1, "Y"])
async def test_submit_reservation_success_values(value):
    respx.post(SUBMIT_URL).mock(return_value=httpx.Response(200, json={"success": value}))
    async with CenterfieldClient() as c:
        assert (await c.submit_reservation({}))["success"] == value


@respx.mock
async def test_submit_reservation_unknown_message_omits_response_body():
    body = "<html>SECRET-BODY 010-9999-8888 someone@example.com</html>"
    respx.post(SUBMIT_URL).mock(return_value=httpx.Response(200, text=body))
    async with CenterfieldClient() as c:
        with pytest.raises(ReservationOutcomeUnknownError) as exc:
            await c.submit_reservation({})
    msg = str(exc.value)
    assert "SECRET-BODY" not in msg and "010-9999-8888" not in msg and f"{len(body.encode())} bytes" in msg


@respx.mock
async def test_search_company_error_omits_response_body():
    respx.post(f"{BASE}/ajax/getCompanyList").mock(
        return_value=httpx.Response(200, text="<ul><li>SECRET-BODY no id</li></ul>")
    )
    async with CenterfieldClient() as c:
        with pytest.raises(CompanyNotFoundError) as exc:
            await c.search_company("x")
    assert "SECRET-BODY" not in str(exc.value)


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


# ── outcome classification in the service layer (UNKNOWN / NOT_SUBMITTED) ─

def _visitors(visitor_kwargs, n: int) -> list[VisitorIn]:
    return [
        VisitorIn(**{**visitor_kwargs, "visitor_name": f"v{i}", "visitor_mobile": f"0101111{i:04d}"}) for i in range(n)
    ]


def _assert_partition(out):
    assert out.succeeded + out.failed + out.unknown + out.not_submitted == out.total == len(out.results)


@respx.mock
@pytest.mark.parametrize(
    "side_effect",
    [httpx.ReadTimeout("t"), httpx.RemoteProtocolError("p"), httpx.Response(503), httpx.Response(200, text="<html>")],
)
async def test_register_single_unknown_outcome(visitor, side_effect):
    submit = mock_happy_path(respx)
    submit.side_effect = [side_effect]
    res = await service.register_single(visitor)
    assert res.status == "UNKNOWN" and res.success is False
    assert "재시도 금지" in res.message and submit.call_count == 1


@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(400), httpx.Response(200, json={"success": False, "error_message": "중복"})])
async def test_register_single_definite_failure(visitor, response):
    submit = mock_happy_path(respx)
    submit.side_effect = [response]
    res = await service.register_single(visitor)
    assert res.status == "FAILED" and res.success is False and "재시도 금지" not in res.message


@respx.mock
async def test_register_single_success_status(visitor):
    mock_happy_path(respx)
    res = await service.register_single(visitor)
    assert res.status == "SUCCEEDED" and res.success is True


@respx.mock
async def test_register_bulk_stops_at_first_unknown(visitor_kwargs):
    submit = mock_happy_path(respx)
    submit.side_effect = [
        httpx.Response(200, json={"success": True}),
        httpx.ReadTimeout("read timed out"),
        httpx.Response(200, json={"success": True}),
        httpx.Response(200, json={"success": True}),
    ]
    out = await service.register_bulk(_visitors(visitor_kwargs, 4))
    assert submit.call_count == 2  # rows after the UNKNOWN are never sent
    assert [r.status for r in out.results] == ["SUCCEEDED", "UNKNOWN", "NOT_SUBMITTED", "NOT_SUBMITTED"]
    assert [r.visitor_name for r in out.results] == ["v0", "v1", "v2", "v3"]
    assert (out.succeeded, out.failed, out.unknown, out.not_submitted) == (1, 0, 1, 2)
    assert out.stopped_on_unknown is True
    assert [r.success for r in out.results] == [True, False, False, False]
    _assert_partition(out)


@respx.mock
async def test_register_bulk_5xx_on_first_row_submits_nothing_else(visitor_kwargs):
    submit = mock_happy_path(respx)
    submit.side_effect = [httpx.Response(502), httpx.Response(200, json={"success": True})]
    out = await service.register_bulk(_visitors(visitor_kwargs, 3))
    assert submit.call_count == 1
    assert (out.unknown, out.not_submitted, out.succeeded) == (1, 2, 0)
    _assert_partition(out)


@respx.mock
async def test_register_bulk_failure_does_not_stop_but_unknown_does(visitor_kwargs):
    submit = mock_happy_path(respx)
    submit.side_effect = [
        httpx.Response(200, json={"success": False, "error_message": "중복"}),
        httpx.Response(404),
        httpx.Response(200, json={"success": True}),
        httpx.Response(500),
        httpx.Response(200, json={"success": True}),
    ]
    out = await service.register_bulk(_visitors(visitor_kwargs, 5))
    assert [r.status for r in out.results] == ["FAILED", "FAILED", "SUCCEEDED", "UNKNOWN", "NOT_SUBMITTED"]
    assert (out.succeeded, out.failed, out.unknown, out.not_submitted) == (1, 2, 1, 1)
    assert submit.call_count == 4
    _assert_partition(out)


@respx.mock
async def test_register_bulk_without_unknown_reports_zero_counts(visitor_kwargs):
    mock_happy_path(respx)
    out = await service.register_bulk(_visitors(visitor_kwargs, 2))
    assert (out.succeeded, out.unknown, out.not_submitted, out.stopped_on_unknown) == (2, 0, 0, False)


@respx.mock
async def test_service_logs_contain_no_pii_or_site_text(visitor_kwargs, caplog):
    submit = mock_happy_path(respx)
    submit.side_effect = [
        httpx.Response(200, json={"success": False, "error_message": "SITE-TEXT 홍길동 01099998888"}),
        httpx.Response(503, text="SITE-BODY"),
    ]
    visitors = _visitors(visitor_kwargs, 2)
    mobiles = tuple(v.visitor_mobile for v in visitors)
    with caplog.at_level("DEBUG"):
        out = await service.register_bulk(visitors)
    assert [r.status for r in out.results] == ["FAILED", "UNKNOWN"]
    assert "SITE-TEXT" in out.results[0].message  # the tool output keeps the site's reason
    logged = caplog.text
    for secret in ("SITE-TEXT", "SITE-BODY", "01099998888", *mobiles, "hong@example.com", "v0", "v1"):
        assert secret not in logged
    assert "ReservationSubmissionError" in logged and "ReservationOutcomeUnknownError (HTTP 503)" in logged


def test_reservation_result_status_backward_compatible():
    from centerfield_visitor_mcp.models import ReservationResult

    assert ReservationResult(visitor_name="a", visitor_mobile="m", success=True, message="").status == "SUCCEEDED"
    assert ReservationResult(visitor_name="a", visitor_mobile="m", success=False, message="").status == "FAILED"
    r = ReservationResult(visitor_name="a", visitor_mobile="m", success=False, status="UNKNOWN", message="")
    assert r.model_dump()["status"] == "UNKNOWN" and r.model_dump()["success"] is False
    with pytest.raises(ValueError):
        ReservationResult(visitor_name="a", visitor_mobile="m", success=True, status="UNKNOWN", message="")
