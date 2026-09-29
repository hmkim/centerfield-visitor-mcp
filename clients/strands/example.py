"""Strands Agents example: local stdio server via uvx.

pip install strands-agents strands-agents-tools mcp
"""
from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.tools.mcp import MCPClient

client = MCPClient(
    lambda: stdio_client(
        StdioServerParameters(
            command="uvx",
            args=["centerfield-visitor-mcp"],
            env={"CF_ENV_FILE": "/absolute/path/to/.env"},
        )
    )
)

with client:
    agent = Agent(tools=client.list_tools_sync())
    agent(
        "센터필드 설정을 확인하고, 다음 명단을 2026-10-15 14:00 18층으로 미리보기 해줘:\n"
        "이름,회사,전화번호,이메일\n홍길동,ABC,010-1234-5678,hong@example.com"
    )
