"""HTTP 客户端封装：_get/_post/_delete（第一版只用 _get）。

所有方法把 HTTP 状态错误转换为 MCP ToolError（中文提示），
MCP 客户端收到的是携带友好错误信息的调用结果而非崩溃。
"""

import httpx

from config import API_BASE
from mcp.server.mcpserver.exceptions import ToolError

_client = httpx.Client(timeout=30.0)


def _detail(exc: httpx.HTTPStatusError) -> str:
    """从错误响应中提取中文错误描述。"""
    try:
        body = exc.response.json()
        if isinstance(body, dict) and body.get("message"):
            return str(body["message"])
    except Exception:
        pass
    return exc.response.text[:200]


def _handle_error(method: str, path: str, exc: httpx.HTTPStatusError) -> None:
    """把 HTTP 状态错误转换为友好的中文 ToolError。"""
    status = exc.response.status_code
    detail = _detail(exc)
    if status == 404:
        msg = f"资源不存在 ({method} {path})"
    elif 400 <= status < 500:
        msg = f"请求参数错误 ({method} {path})"
    else:
        msg = f"请求失败 ({method} {path})"
    if detail:
        msg += f"：{detail}"
    raise ToolError(msg) from exc


def _request(method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
    """统一请求：解包 REST 信封中的 data 字段返回。"""
    try:
        resp = _client.request(method, f"{API_BASE}{path}", params=params, json=json)
        resp.raise_for_status()
        body = resp.json()
        return body.get("data", body)
    except httpx.HTTPStatusError as e:
        _handle_error(method, path, e)


def _get(path: str, params: dict | None = None) -> dict:
    return _request("GET", path, params=params)


def _post(path: str, json: dict | None = None, params: dict | None = None) -> dict:
    return _request("POST", path, params=params, json=json)


def _put(path: str, json: dict | None = None, params: dict | None = None) -> dict:
    return _request("PUT", path, params=params, json=json)


def _patch(path: str, json: dict | None = None, params: dict | None = None) -> dict:
    return _request("PATCH", path, params=params, json=json)


def _delete(path: str, params: dict | None = None) -> dict:
    return _request("DELETE", path, params=params)