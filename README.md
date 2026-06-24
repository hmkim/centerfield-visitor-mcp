# Centerfield Visitor MCP

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that automates
visitor reservations for the Centerfield building (`www.centerfield.co.kr`).
Use it from any MCP-compatible AI agent (Kiro CLI, Claude Code, Strands Agents, …)
to register visitors with natural language — single entries, pasted text, or Excel/CSV files.

> 센터필드 빌딩 방문예약을 자동화하는 MCP 서버입니다. Kiro CLI, Claude Code, Strands Agents 등
> MCP 호환 AI 에이전트에서 자연어로 방문자를 등록할 수 있습니다.

This server runs **entirely locally** — `uvx` downloads and runs it on your machine,
and it talks directly to `www.centerfield.co.kr`. No backend service, API gateway, or
hosting account is required.

> 이 서버는 **로컬에서 단독 실행**됩니다. `uvx`가 내 컴퓨터에서 서버를 받아 실행하고,
> 센터필드 사이트(`www.centerfield.co.kr`)에 직접 요청합니다. 별도의 백엔드 서버나 클라우드 계정이 필요 없습니다.

## Installation

No manual install needed — run directly with [`uvx`](https://docs.astral.sh/uv/):

```bash
uvx centerfield-visitor-mcp
```

## MCP client configuration

**Set your own registered values via environment variables** — nothing is hardcoded.

### Claude Code

Register the server with the `claude mcp add` command:

```bash
claude mcp add centerfield-visitor \
  -e CF_COMPANY_NAME="Your Company Name" \
  -e CF_PERSON_IN_CHARGE_MOBILE="010XXXXXXXX" \
  -e CF_BUILDING="east" \
  -e CF_BUILDING_KEY="East" \
  -- uvx centerfield-visitor-mcp
```

Verify it is connected:

```bash
claude mcp list
```

Then just ask in natural language, e.g.
*"센터필드에 홍길동(ABC주식회사, 01012345678, hong@abc.com)을 2026-07-26 15:00, 18층으로 방문 등록해줘"*.

### Kiro CLI / other MCP clients

Add the server to your MCP client config (example: Kiro CLI `mcp.json`):

```json
{
  "mcpServers": {
    "centerfield-visitor": {
      "command": "uvx",
      "args": ["centerfield-visitor-mcp"],
      "env": {
        "CF_COMPANY_NAME": "Your Company Name",
        "CF_PERSON_IN_CHARGE_MOBILE": "010XXXXXXXX",
        "CF_BUILDING": "east",
        "CF_BUILDING_KEY": "East"
      }
    }
  }
}
```

## Configuration (environment variables)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `CF_COMPANY_NAME` | Tenant company name as registered in Centerfield | _(empty)_ | ✅ |
| `CF_PERSON_IN_CHARGE_MOBILE` | Mobile number of the approval contact registered in Centerfield | _(empty)_ | ✅ |
| `CF_BUILDING` | Building code | `east` | |
| `CF_BUILDING_KEY` | Building display key | `East` | |
| `CF_CENTERFIELD_BASE_URL` | Centerfield base URL | `https://www.centerfield.co.kr` | |
| `CF_REQUEST_TIMEOUT` | HTTP timeout (seconds) | `30` | |
| `CF_BULK_MAX_VISITORS` | Max visitors per bulk request | `200` | |
| `CF_REQUEST_DELAY` | Delay between bulk requests (seconds) | `0.5` | |

> **`CF_PERSON_IN_CHARGE_MOBILE` must be the mobile number registered as the tenant's
> approval contact in Centerfield.** Reservations submitted with an unregistered number
> will fail. Provide it through your environment — never commit a real phone number.
>
> There is no separate "validate credentials" endpoint: the company name and approval
> contact are checked live during a registration attempt. The fastest way to confirm
> your values are correct is to register one visitor (or preview a bulk file first).

## Tools

| Tool | Description |
|------|-------------|
| `register_visitor` | Register a single visitor |
| `register_visitors_from_file` | Bulk register from an Excel (`.xlsx`) or CSV file |
| `register_visitors_from_text` | Bulk register from pasted tab/CSV text |
| `preview_visitors_from_file` | Preview parsed visitors from a file (no registration) |

> **Recommended bulk workflow:** run `preview_visitors_from_file` first to confirm the
> parsed rows look correct, then `register_visitors_from_file` to submit.

## Input constraints

Values are validated before any request is sent:

| Field | Rule |
|-------|------|
| `visit_time` | `HH:MM`, 30-minute intervals, between `08:00` and `20:00` |
| `floor` | `12` or `18` only |
| `visit_purpose` | `meeting` (default), `visit_business`, `interview`, `tour`, `construction`, `others` |
| `visitor_mobile` | hyphens/spaces are stripped automatically (`010-1234-5678` → `01012345678`) |
| `visitor_email` | must be a valid email address |
| `visit_date` | `YYYY-MM-DD` |

## File format

Bulk tools accept Excel/CSV with these columns (Korean or English headers are auto-mapped):

```
visitor_name, visitor_company_name, visitor_mobile, visitor_email, visit_date, visit_time
홍길동, ABC Inc., 01012345678, hong@abc.com, 2026-01-15, 10:00
```

## How it works

The server holds a single authenticated session against the Centerfield site,
manages CSRF tokens automatically, verifies the tenant company and approval contact,
then submits the reservation form. Bulk requests are processed sequentially with a
configurable delay to avoid rate limiting.

## License

[MIT](LICENSE)
