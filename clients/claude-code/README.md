# Claude Code

```bash
# user scope (all projects). ~/.config/centerfield-visitor-mcp/.env is read automatically.
claude mcp add centerfield-visitor --scope user -- uvx centerfield-visitor-mcp
# or point at a specific .env
claude mcp add centerfield-visitor --scope user -e CF_ENV_FILE=/abs/path/.env -- uvx centerfield-visitor-mcp
# remote (Amazon Quick-style deployment)
claude mcp add --transport http centerfield-visitor-remote https://<endpoint>/mcp
claude mcp list        # expect: centerfield-visitor ... ✓ Connected
```

Project scope: copy `.mcp.json` from this folder to the repository root and commit it (values stay in `.env`).

Skill: `.claude/skills/centerfield-visitor/SKILL.md` ships in this repository (project skill).
Personal install: `cp -r .claude/skills/centerfield-visitor ~/.claude/skills/`.
Preview/validate tools are pre-approved by the skill's `allowed-tools`; `register_*` always prompts.

Headless acceptance check (spends tokens):

```bash
claude -p "센터필드 방문자 명단 미리보기: $(pwd)/tests/fixtures/visitors_ko.csv" \
  --allowedTools "mcp__centerfield-visitor__preview_visitors_from_file"
```
Expected output contains `파싱 결과: N명 유효`.
