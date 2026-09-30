"""全局配置：REST API 地址与 MCP Server 监听地址。"""

API_BASE = "http://127.0.0.1:8080"

MCP_HOST = "127.0.0.1"
MCP_PORT = 8081

# MCP 2026-07-28 为无状态协议：SDK 需显式开启 stateless_http
MCP_STATELESS_HTTP = True