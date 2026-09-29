# Client setup matrix

One server, two transports. Values (company name, approval-contact mobile) live in a `.env`;
`~/.config/centerfield-visitor-mcp/.env` is read automatically by every client, so most configs need no `env` block.

| Client | Transport | Config | Skill location |
|---|---|---|---|
| Kiro CLI | stdio | `~/.kiro/settings/mcp.json` ← `kiro/mcp.json` | `~/.kiro/skills/centerfield-visitor/SKILL.md` |
| Kiro IDE | stdio | `.kiro/settings/mcp.json` (workspace) or `~/.kiro/settings/mcp.json` ← `kiro/mcp.json` | `.kiro/skills/centerfield-visitor/SKILL.md` |
| KiroCrew | stdio | `~/.kiro/agents/<agent>.json` ← `kirocrew/agent-snippet.json` | `~/.kiro/crew/skills/centerfield-visitor/SKILL.md` |
| Claude Code | stdio / http | `claude mcp add …` or `.mcp.json` ← `claude-code/` | `.claude/skills/centerfield-visitor/SKILL.md` (in this repo) |
| Claude Desktop | stdio | `claude-desktop/claude_desktop_config.json` | — |
| Codex CLI | stdio / http | `~/.codex/config.toml` ← `codex/config.toml` | — |
| Cursor | stdio | `.cursor/mcp.json` ← `cursor/mcp.json` | — |
| Strands Agents | stdio / http | `strands/example.py` | — |
| Amazon Quick | streamable-http | `remote/README.md` (AgentCore Runtime + Cognito 2LO) | Quick connector actions |

Verification per client: list tools (expect `validate_configuration`, `preview_visitors_from_text`,
`register_visitor`, `register_visitors_from_text`, plus the two `*_from_file` tools on stdio), call
`validate_configuration`, then preview a list. Registration runs only after the human confirms and is
verified by the approver in the Centerfield mobile app.
