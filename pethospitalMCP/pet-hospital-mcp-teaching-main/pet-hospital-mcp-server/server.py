"""宠物医院 MCP Server（第一版）- 基于 MCP 2026-07-28 协议（Python SDK v2）。"""

import argparse

from mcp.server import MCPServer

from config import MCP_HOST, MCP_PORT, MCP_STATELESS_HTTP


def build_mcp() -> MCPServer:
    """注册全部 Tool 后返回 MCPServer 实例。"""
    from tools.pet_crud import register_pet_crud_tools
    from tools.system import register_system_tools

    mcp = MCPServer("pet-hospital")
    register_pet_crud_tools(mcp)
    register_system_tools(mcp)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="宠物医院 MCP Server（第一版）")
    parser.add_argument("--http", action="store_true", help="Streamable HTTP 模式（默认 stdio）")
    args = parser.parse_args()

    mcp = build_mcp()
    if args.http:
        mcp.run(
            transport="streamable-http",
            host=MCP_HOST,
            port=MCP_PORT,
            stateless_http=MCP_STATELESS_HTTP,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()