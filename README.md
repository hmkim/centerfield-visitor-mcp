# Centerfield Visitor MCP

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that automates
visitor reservations for the Centerfield building (`www.centerfield.co.kr`).
Use it from any MCP-compatible agent — **Kiro CLI / Kiro IDE / KiroCrew, Claude Code, Claude Desktop,
Codex CLI, Cursor, Strands Agents (local stdio)** and **Amazon Quick or any remote client (streamable HTTP)** —
to register visitors with natural language: single entries, pasted text, survey exports, or Excel/CSV files.

> 센터필드 빌딩 방문예약을 자동화하는 MCP 서버입니다. 로컬 에이전트(Kiro, Claude Code, Codex, Cursor …)는
> stdio로, Amazon Quick 같은 원격 에이전트는 streamable HTTP로 같은 서버를 씁니다.

The stdio server runs **entirely locally** — `uvx` downloads and runs it on your machine, and it talks
directly to `www.centerfield.co.kr`. No backend service is required for local agents.

## Quick start

```bash
mkdir -p ~/.config/centerfield-visitor-mcp
cp .env.example ~/.config/centerfield-visitor-mcp/.env   # fill CF_COMPANY_NAME, CF_PERSON_IN_CHARGE_MOBILE
uvx centerfield-visitor-mcp                               # stdio; every client below can launch this
```

`~/.config/centerfield-visitor-mcp/.env` is read automatically, so client configs need no secrets.

## Client setup

| Client | How | Details |
|---|---|---|
| Kiro CLI | `~/.kiro/settings/mcp.json` | [`clients/kiro/mcp.json`](clients/kiro/mcp.json) |
| Kiro IDE | `.kiro/settings/mcp.json` (workspace) | same file |
| KiroCrew | agent JSON `mcpServers` + `tools` | [`clients/kirocrew/agent-snippet.json`](clients/kirocrew/agent-snippet.json) |
| Claude Code | `claude mcp add centerfield-visitor --scope user -- uvx centerfield-visitor-mcp` | [`clients/claude-code/`](clients/claude-code/README.md) |
| Claude Desktop | `claude_desktop_config.json` | [`clients/claude-desktop/`](clients/claude-desktop/claude_desktop_config.json) |
| Codex CLI | `~/.codex/config.toml` `[mcp_servers.centerfield-visitor]` | [`clients/codex/config.toml`](clients/codex/config.toml) |
| Cursor | `.cursor/mcp.json` | [`clients/cursor/mcp.json`](clients/cursor/mcp.json) |
| Strands Agents | `MCPClient(stdio_client(...))` | [`clients/strands/example.py`](clients/strands/example.py) |
| Amazon Quick | remote streamable HTTP + OAuth 2LO | [`clients/remote/README.md`](clients/remote/README.md) |

Agent skill (Agent Skills spec, works in Claude Code / Kiro / KiroCrew): [`SKILL.md`](SKILL.md) —
also shipped as the project skill `.claude/skills/centerfield-visitor/SKILL.md`.

## Tools

| Tool | Side effect | Notes |
|---|---|---|
| `validate_configuration()` | none | Checks company, approval contact and floor list against the live site |
| `preview_visitors_from_text(text, default_visit_date, default_visit_time, default_floor, default_purpose)` | none | Parse + validate pasted CSV/TSV |
| `register_visitor(..., dry_run)` | **creates a reservation** | `dry_run=true` validates (input + site) without submitting |
| `register_visitors_from_text(text, defaults…, dry_run)` | **creates reservations** | Sequential, one summary string returned |
| `preview_visitors_from_file(file_path, defaults…)` | none | stdio deployments only (needs a shared filesystem) |
| `register_visitors_from_file(file_path, defaults…, dry_run)` | **creates reservations** | stdio deployments only |

Recommended flow: `validate_configuration` once → `preview_*` → human confirms → `register_*`.
The `default_*` arguments fill columns that attendee lists usually lack (visit date/time/floor).

## Input constraints

| Field | Rule |
|-------|------|
| `visit_time` | `HH:MM`, 30-minute intervals, `08:00`–`20:00` (`HH:MM:SS` from spreadsheets tolerated) |
| `visit_date` | `YYYY-MM-DD`, today or later |
| `floor` | `12` or `18`; if omitted, `CF_DEFAULT_FLOOR` (default `12`) |
| `visit_purpose` | `meeting` (default), `visit_business`, `interview`, `tour`, `construction`, `others` |
| `visitor_mobile` | Korean mobile; `010-1234-5678`, `010 1234 5678`, `+82 10-1234-5678` are normalized to `01012345678`; empty or non-mobile values are rejected |
| `visitor_email` | valid email address |
| duplicates | rows with the same mobile + date + time inside one request are skipped and reported |

## File / text format

Header row in Korean or English; survey-export headers are recognized too
(`Full Name`, `Email`, `연락처(…)`, `소속/회사 (…)`). Unknown columns are ignored.

```
이름,회사,전화번호,이메일,방문일,방문시간,층
홍길동,ABC주식회사,01012345678,hong@abc.com,2026-11-15,10:00,12
```

Lists without date/time columns: pass `default_visit_date="2026-11-15"`, `default_visit_time="10:00"`.

## Configuration

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `CF_COMPANY_NAME` | Tenant company name as registered in Centerfield | _(empty)_ | ✅ |
| `CF_PERSON_IN_CHARGE_MOBILE` | Mobile number of the approval contact registered in Centerfield | _(empty)_ | ✅ |
| `CF_BUILDING` / `CF_BUILDING_KEY` | Building code / display key | `east` / `East` | |
| `CF_DEFAULT_FLOOR` | Floor when a row omits it (`12` or `18`) | `12` | |
| `CF_TRANSPORT` | `stdio` or `streamable-http` | `stdio` | |
| `CF_HTTP_HOST` / `CF_HTTP_PORT` / `CF_HTTP_PATH` | HTTP bind address and path | `127.0.0.1` / `8000` / `/mcp` | |
| `CF_HTTP_STATELESS` / `CF_HTTP_JSON_RESPONSE` | Streamable HTTP mode | `true` / `true` | |
| `CF_HTTP_ALLOWED_HOSTS` | Host allow-list for DNS-rebinding protection (`host:*` = any port). Empty: loopback binds use a built-in localhost list; other binds run with protection off and log a warning | _(empty)_ | |
| `CF_EXPOSE_FILE_TOOLS` | Force file tools on/off | on for stdio, off for HTTP | |
| `CF_CENTERFIELD_BASE_URL` | Centerfield base URL | `https://www.centerfield.co.kr` | |
| `CF_REQUEST_TIMEOUT` | HTTP timeout (seconds) | `30` | |
| `CF_BULK_MAX_VISITORS` | Max visitors per bulk request (use `10` for Amazon Quick's 60 s limit) | `200` | |
| `CF_REQUEST_DELAY` | Delay between submissions (seconds) | `0.5` | |
| `CF_ENV_FILE` | Extra `.env` to load | _(unset)_ | |

`.env` load order (later overrides earlier): `~/.config/centerfield-visitor-mcp/.env` → `./.env` → `$CF_ENV_FILE`;
process environment variables always win. Startup logs (stderr) list the files read and any problems.

> `CF_PERSON_IN_CHARGE_MOBILE` must be the mobile number registered as the tenant's approval contact.
> Run `validate_configuration` after setup — it checks both values live without creating a reservation.

## Remote mode (Amazon Quick, hosted deployments)

```bash
CF_TRANSPORT=streamable-http CF_HTTP_HOST=0.0.0.0 uvx centerfield-visitor-mcp    # http://host:8000/mcp
docker build --platform linux/arm64 -t centerfield-visitor-mcp .                 # or the container image
```

See [`clients/remote/README.md`](clients/remote/README.md) for the AgentCore Runtime + Cognito recipe and the
Amazon Quick connector steps. Works with mcp SDK 1.x and 2.x.

## Development & testing

```bash
uv sync --group dev
uv run pytest                          # offline unit tests (mocked HTTP)
uv run --with "mcp<2" pytest           # same suite on mcp SDK 1.x
uv run python scripts/smoke_http.py    # streamable-http transport smoke test
uv run pytest -m live                  # read-only checks against the live site (needs a real .env)
CF_LIVE_REGISTER=1 CF_TEST_VISITOR_NAME=... CF_TEST_VISITOR_MOBILE=... CF_TEST_VISITOR_EMAIL=... uv run pytest -m live
```

The last command creates one real reservation; confirm it in the Centerfield mobile app and cancel it there
(there is no cancel API).

## How it works

The server holds a single session against the Centerfield site, manages CSRF tokens, verifies the tenant company
and approval contact, resolves the floor key, then submits the reservation form. Bulk requests are processed
sequentially with a configurable delay.

## License

[MIT](LICENSE)
