from mcp.server import MCPServer
from config import validate, ANYTHINGLLM_WORKSPACE_SLUG
from anythingllm_client import get_client

mcp = MCPServer("AnythingLLM")


@mcp.tool()
async def ask_workspace(question: str) -> str:
    """向 AnythingLLM 工作区提问，获取基于该工作区文档的回答。question 是你要问的问题。"""
    client = get_client()
    return await client.chat(question)


def main() -> None:
    validate()
    print(f"AnythingLLM MCP Server starting (workspace: {ANYTHINGLLM_WORKSPACE_SLUG})")
    mcp.run()


if __name__ == "__main__":
    main()
