# Remote deployment (streamable HTTP) — Amazon Quick and other remote MCP clients

The same package serves MCP over HTTP:

```bash
# .env: CF_TRANSPORT=streamable-http, CF_HTTP_HOST=0.0.0.0, CF_HTTP_PORT=8000
uvx centerfield-visitor-mcp
# container: docker build --platform linux/arm64 -t centerfield-visitor-mcp . && docker run -p 8000:8000 --env-file .env centerfield-visitor-mcp
```

Endpoint: `http://<host>:8000/mcp` (stateless, JSON responses). File-path tools are hidden in this mode;
agents paste the list as text (`*_from_text`). Smoke test: `uv run python scripts/smoke_http.py`.

DNS-rebinding protection: a `0.0.0.0` bind has no built-in Host allow-list, so set
`CF_HTTP_ALLOWED_HOSTS` to the hostname(s) clients use (e.g. `mcp.example.com:*`, or the AgentCore
runtime endpoint host). Left empty, the server starts with protection off and logs a warning; only do
that when the HTTPS front in front of it validates `Host`/`Origin` itself.

## Amazon Quick (Connectors → Model Context Protocol)

Facts from the Quick user guide (checked 2026-09): remote servers only (stdio not supported), Streamable HTTP
preferred, OAuth user (3LO) / service (2LO client credentials) / no-auth, **no custom HTTP headers**,
**60-second per-operation timeout (HTTP 424, no retry)**, tool `inputSchema` must be JSON Schema Draft 7+
(this server passes: `required` is an array at the schema root), custom connectors need a manual **Sync**
after tool changes, Quick Enterprise subscription required.

Recommended hosting: **Amazon Bedrock AgentCore Runtime** (MCP protocol, container on `0.0.0.0:8000/mcp`)
with a Cognito user pool as the OAuth server.

1. Push the image to ECR (arm64). Create an AgentCore Runtime with protocol `MCP`, environment
   `CF_COMPANY_NAME`, `CF_PERSON_IN_CHARGE_MOBILE` (inject from Secrets Manager), `CF_DEFAULT_FLOOR`,
   `CF_BULK_MAX_VISITORS=10`.
2. Cognito: user pool + domain + resource server (scope e.g. `centerfield/visitor.write`) + **M2M app client**
   (client credentials). Configure the runtime's JWT authorizer with the pool's OIDC discovery URL and
   `allowedClients=[<app client id>]`.
3. Quick: Connectors → Create for your team → Model Context Protocol → endpoint = the runtime's invocation
   URL, Connection type **Public network**, Auth server **Public network**, **Service authentication** with the
   Cognito client id/secret and token URL `https://<domain>.auth.<region>.amazoncognito.com/oauth2/token`.
4. Review discovered actions (`validate_configuration`, `preview_visitors_from_text`, `register_visitor`,
   `register_visitors_from_text`), enable them, share with the team. After redeploying with tool changes,
   press **Sync** on the connector.

Time budget: one live reservation submit measured about 4–5 s (n=1, 2026-09-29), so keep
`CF_BULK_MAX_VISITORS=10` (≈55 s worst case) for Quick; the agent splits larger lists.

Verify on first setup: Cognito accepts the RFC 8707 `resource` parameter Quick sends to the token endpoint
(Entra ID is known to reject it); the runtime works without custom headers (Quick cannot send any).

Why not ECS + a public ALB: AgentCore Runtime already provides the HTTPS endpoint and JWT authorization, so
an internet-facing load balancer adds surface without adding value (and accounts with VPC Block Public Access
enabled cannot create one); a private ALB would need a Quick VPC connection with Route 53 Resolver inbound
endpoints.

## Other remote-capable clients

- Kiro CLI/IDE: `clients/kiro/mcp.remote.json` (`url` + `headers`)
- Claude Code: `claude mcp add --transport http centerfield-visitor-remote https://<endpoint>/mcp`
- Codex: `[mcp_servers.x] url = "https://<endpoint>/mcp"`
