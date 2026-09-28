#!/usr/bin/env python3
"""Smoke-test the streamable-http transport end to end (no Centerfield calls).

Starts `centerfield-visitor-mcp` with CF_TRANSPORT=streamable-http on a free port, then
speaks raw MCP JSON-RPC over HTTP (initialize -> notifications/initialized -> tools/list ->
tools/call preview_visitors_from_text). Works with mcp SDK 1.x and 2.x because it does not
use the SDK client. Exit code 0 = pass.

Usage:  uv run python scripts/smoke_http.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time

import httpx

PROTOCOL_VERSION = "2025-06-18"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rpc(client: httpx.Client, url: str, method: str, params: dict | None = None, *, rpc_id: int | None = 1, session: str | None = None):
    body: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if rpc_id is not None:
        body["id"] = rpc_id
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if session:
        headers["Mcp-Session-Id"] = session
    resp = client.post(url, json=body, headers=headers, timeout=30)
    return resp


def parse_result(resp: httpx.Response) -> dict:
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise RuntimeError(f"no data frame in SSE response: {resp.text[:200]}")
    return resp.json()


def main() -> int:
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CF_")}
    env.update(
        {
            "CF_TRANSPORT": "streamable-http",
            "CF_HTTP_HOST": "127.0.0.1",
            "CF_HTTP_PORT": str(port),
            "CF_HTTP_PATH": "/mcp",
            "CF_COMPANY_NAME": "Smoke Tenant",
            "CF_PERSON_IN_CHARGE_MOBILE": "01000000000",
            "CF_DEFAULT_FLOOR": "18",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "centerfield_visitor_mcp.server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        with httpx.Client() as client:
            deadline = time.time() + 30
            resp = None
            while time.time() < deadline:
                try:
                    resp = rpc(
                        client,
                        url,
                        "initialize",
                        {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}},
                    )
                    break
                except httpx.HTTPError:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.3)
            if resp is None or proc.poll() is not None:
                print("server did not start:", (proc.stderr.read() if proc.stderr else "")[-2000:])
                return 2
            assert resp.status_code == 200, (resp.status_code, resp.text[:300])
            init = parse_result(resp)
            assert init["result"]["serverInfo"]["name"].startswith("Centerfield"), init
            session = resp.headers.get("mcp-session-id")

            note = rpc(client, url, "notifications/initialized", {}, rpc_id=None, session=session)
            assert note.status_code in (200, 202, 204), (note.status_code, note.text[:200])

            tools = parse_result(rpc(client, url, "tools/list", {}, rpc_id=2, session=session))["result"]["tools"]
            names = sorted(t["name"] for t in tools)
            assert "preview_visitors_from_text" in names and "register_visitors_from_text" in names, names
            assert "register_visitors_from_file" not in names, "file tools must be hidden in HTTP mode"
            for t in tools:
                schema = t["inputSchema"]
                assert isinstance(schema.get("required", []), list), t["name"]

            visit = (dt.date.today() + dt.timedelta(days=7)).isoformat()
            text = f"이름,회사,전화번호,이메일\n홍길동,ABC,010-1234-5678,hong@example.com\n"
            call = parse_result(
                rpc(
                    client,
                    url,
                    "tools/call",
                    {"name": "preview_visitors_from_text", "arguments": {"text": text, "default_visit_date": visit, "default_visit_time": "14:00"}},
                    rpc_id=3,
                    session=session,
                )
            )
            content = call["result"]["content"][0]["text"]
            assert "파싱 결과: 1명 유효, 0건 오류" in content, content
            assert "01012345678" in content and "18층" in content, content

        print(f"OK streamable-http on {url}: tools={names}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
