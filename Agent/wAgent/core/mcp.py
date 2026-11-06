from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import threading
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .tools.base import ToolResult


MCP_CONFIG_FILE_NAME = ".mcp.json"
DEFAULT_CALL_TIMEOUT = 60.0
DEFAULT_CONNECT_TIMEOUT = 30.0
MAX_TOOL_NAME_LENGTH = 64
_TOOL_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")


class MCPConfigError(ValueError):
    """MCP 配置或连接参数不合法。"""


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    transport: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None
    cwd: str | None = None
    url: str | None = None
    headers: Mapping[str, str] | None = None
    timeout: float = DEFAULT_CALL_TIMEOUT


@dataclass(slots=True)
class _Connection:
    config: MCPServerConfig
    stack: AsyncExitStack
    session: Any
    server_info: str = ""


@dataclass(slots=True)
class _Command:
    kind: str
    future: concurrent.futures.Future
    server: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout: float = DEFAULT_CALL_TIMEOUT


def _normalize_transport(entry: Mapping[str, Any], name: str) -> str:
    raw = entry.get("type")
    if raw is None:
        raw = entry.get("transport")
    if raw is None:
        if entry.get("command") is not None:
            return "stdio"
        if entry.get("url") is not None:
            return "streamable_http"
        raise MCPConfigError(f"MCP Server「{name}」缺少 type、command 或 url")

    value = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "stdio": "stdio",
        "http": "streamable_http",
        "streamablehttp": "streamable_http",
        "streamable_http": "streamable_http",
        "sse": "sse",
    }
    transport = aliases.get(value)
    if transport is None:
        raise MCPConfigError(f"MCP Server「{name}」使用了不支持的协议：{raw!r}")
    return transport


def _string_map(value: Any, label: str) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise MCPConfigError(f"{label} 必须是 JSON 对象")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[str(key)] = os.path.expandvars(str(item))
    return result


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise MCPConfigError(f"{label} 必须是字符串数组")
    args: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise MCPConfigError(f"{label} 中的每一项都必须是字符串")
        args.append(item)
    return tuple(args)


def _positive_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MCPConfigError(f"timeout 必须是数字，当前值为：{value!r}") from exc
    return number if number > 0 else default


def _parse_server(
    name: str,
    entry: Any,
    default_call_timeout: float = DEFAULT_CALL_TIMEOUT,
) -> MCPServerConfig:
    if not isinstance(entry, Mapping):
        raise MCPConfigError(f"MCP Server「{name}」的配置必须是 JSON 对象")

    transport = _normalize_transport(entry, name)
    timeout = _positive_float(entry.get("timeout"), default_call_timeout)

    if transport == "stdio":
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            raise MCPConfigError(f"MCP Server「{name}」的 command 不能为空")
        cwd = entry.get("cwd")
        if cwd is not None:
            cwd = os.path.expanduser(os.path.expandvars(str(cwd)))
        return MCPServerConfig(
            name=name,
            transport=transport,
            command=command.strip(),
            args=_string_list(entry.get("args"), f"MCP Server「{name}」的 args"),
            env=_string_map(entry.get("env"), f"MCP Server「{name}」的 env"),
            cwd=cwd,
            timeout=timeout,
        )

    url = entry.get("url")
    if not isinstance(url, str) or not url.strip():
        raise MCPConfigError(f"MCP Server「{name}」的 url 不能为空")
    if not url.strip().lower().startswith(("http://", "https://")):
        raise MCPConfigError(f"MCP Server「{name}」的 url 必须以 http:// 或 https:// 开头")
    return MCPServerConfig(
        name=name,
        transport=transport,
        url=url.strip(),
        headers=_string_map(entry.get("headers"), f"MCP Server「{name}」的 headers"),
        timeout=timeout,
    )


def load_mcp_config(
    project_root: str | Path | None = None,
    default_call_timeout: float = DEFAULT_CALL_TIMEOUT,
) -> tuple[list[MCPServerConfig], list[str]]:
    """读取项目目录（默认当前工作目录）下的 .mcp.json。"""

    env_path = os.environ.get("WAGENT_MCP_CONFIG")
    if env_path:
        path = Path(env_path).expanduser()
    else:
        root = Path(project_root).expanduser() if project_root is not None else Path.cwd()
        path = root / MCP_CONFIG_FILE_NAME

    if not path.is_file():
        return [], []

    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except OSError as exc:
        return [], [f"无法读取 MCP 配置文件 {path}：{exc}"]
    except ValueError as exc:
        return [], [f"MCP 配置文件 {path} 不是合法的 JSON：{exc}"]

    if not isinstance(payload, Mapping):
        return [], [f"MCP 配置文件 {path} 的顶层必须是 JSON 对象"]

    servers = payload.get("mcpServers")
    if servers is None:
        servers = payload.get("servers")
    if servers is None:
        return [], [f"MCP 配置文件 {path} 缺少 mcpServers 字段"]
    if not isinstance(servers, Mapping):
        return [], [f"MCP 配置文件 {path} 的 mcpServers 必须是 JSON 对象"]

    configs: list[MCPServerConfig] = []
    warnings: list[str] = []
    for name, entry in servers.items():
        server_name = str(name)
        if isinstance(entry, Mapping) and entry.get("disabled") is True:
            continue
        try:
            configs.append(
                _parse_server(server_name, entry, default_call_timeout)
            )
        except MCPConfigError as exc:
            warnings.append(str(exc))
    return configs, warnings


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            value = obj[name]
        else:
            try:
                value = getattr(obj, name)
            except (AttributeError, TypeError):
                continue
        if value is not None:
            return value
    return default


def _sanitize_tool_name(name: str) -> str:
    cleaned = _TOOL_NAME_PATTERN.sub("_", name).strip("_")
    if not cleaned:
        cleaned = "tool"
    return cleaned


def _describe_exception(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [_describe_exception(item) for item in exc.exceptions]
        parts = [part for part in parts if part]
        return "；".join(parts) if parts else exc.__class__.__name__
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _format_call_result(result: Any) -> ToolResult:
    result_type = _attr(result, "result_type", default=None)
    if result_type in ("input_required", "inputRequired"):
        return ToolResult(
            "MCP 工具要求额外的用户输入（elicitation/input_required），当前客户端未启用该能力。",
            ok=False,
        )

    parts: list[str] = []
    content = _attr(result, "content", default=None) or ()
    if not isinstance(content, (list, tuple)):
        content = (content,)

    for block in content:
        kind = _attr(block, "type", default="")
        if kind == "text":
            parts.append(str(_attr(block, "text", default="")))
        elif kind in ("image", "audio"):
            mime = _attr(block, "mime_type", "mimeType", default="未知类型")
            data = _attr(block, "data", default="") or ""
            parts.append(f"[{kind} 内容，类型 {mime}，base64 长度 {len(data)}，已省略原始数据]")
        elif kind == "resource":
            resource = _attr(block, "resource", default=None)
            uri = _attr(resource, "uri", default="未知 URI")
            text = _attr(resource, "text", default=None)
            if text is not None:
                parts.append(f"[资源 {uri}]\n{text}")
            else:
                mime = _attr(resource, "mime_type", "mimeType", default="未知类型")
                blob = _attr(resource, "blob", default="") or ""
                parts.append(
                    f"[二进制资源 {uri}，类型 {mime}，base64 长度 {len(blob)}，已省略原始数据]"
                )
        elif kind == "resource_link":
            name = _attr(block, "name", default="资源")
            uri = _attr(block, "uri", default="")
            parts.append(f"[资源链接 {name}：{uri}]")
        else:
            text = _attr(block, "text", default=None)
            parts.append(str(text) if text is not None else str(block))

    structured = _attr(result, "structured_content", "structuredContent", default=None)
    if structured is not None:
        try:
            rendered = json.dumps(structured, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            rendered = str(structured)
        parts.append(f"结构化数据：\n{rendered}")

    is_error = bool(_attr(result, "is_error", "isError", default=False))
    if not parts:
        parts.append("工具执行成功，但未返回任何内容。")

    text = "\n".join(part for part in parts if part)
    if is_error:
        text = f"MCP 工具返回错误：\n{text}"
    return ToolResult(text, ok=not is_error)


@dataclass(frozen=True, slots=True)
class MCPTool:
    name: str
    description: str
    parameters: dict[str, Any]
    server: str = field(repr=False)
    original_name: str = field(repr=False)
    manager: "MCPClientManager" = field(repr=False, compare=False)

    def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        return self.manager.call_tool(self.name, dict(arguments))

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class MCPClientManager:
    """维护 MCP Server 连接，并把远端工具适配为本地 Function Calling 工具。"""

    def __init__(
        self,
        configs: Iterable[MCPServerConfig] = (),
        *,
        local_tool_names: Iterable[str] = (),
        warnings: Iterable[str] = (),
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        self._configs = tuple(configs)
        self._local_tool_names = set(local_tool_names)
        self._warnings: list[str] = list(warnings)
        self._connect_timeout = connect_timeout
        self._connections: dict[str, _Connection] = {}
        self._tools: list[MCPTool] = []
        self._tool_map: dict[str, tuple[str, str]] = {}
        self._server_tools: dict[str, list[str]] = {}

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[_Command | None] | None = None
        self._ready_event = threading.Event()
        self._ready_async: asyncio.Event | None = None
        self._started = False
        self._closed = False
        self._lock = threading.Lock()

    @property
    def configs(self) -> tuple[MCPServerConfig, ...]:
        return self._configs

    @property
    def tools(self) -> tuple[MCPTool, ...]:
        return tuple(self._tools)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def tool_map(self) -> dict[str, tuple[str, str]]:
        return dict(self._tool_map)

    @property
    def server_tools(self) -> dict[str, tuple[str, ...]]:
        return {name: tuple(tools) for name, tools in self._server_tools.items()}

    @property
    def connected_servers(self) -> tuple[str, ...]:
        return tuple(self._connections)

    def add_warning(self, message: str) -> None:
        with self._lock:
            self._warnings.append(message)

    def start(self) -> "MCPClientManager":
        if self._started or self._closed:
            return self
        if not self._configs:
            self._started = True
            return self

        self._thread = threading.Thread(
            target=self._thread_main,
            name="wAgent-mcp",
            daemon=True,
        )
        self._thread.start()
        wait_seconds = 15.0 + sum(
            min(max(config.timeout, 1.0), self._connect_timeout)
            for config in self._configs
        )
        if not self._ready_event.wait(wait_seconds):
            self.add_warning("MCP 客户端初始化超时，将跳过尚未就绪的 MCP Server")
        self._started = True
        return self

    def call_tool(self, exposed_name: str, arguments: Mapping[str, Any]) -> ToolResult:
        mapping = self._tool_map.get(exposed_name)
        if mapping is None:
            return ToolResult(f"未知 MCP 工具：{exposed_name}", ok=False)
        server_name, original_name = mapping

        if not self._started or self._closed:
            return ToolResult("MCP 客户端尚未启动或已关闭", ok=False)
        if self._loop is None or self._queue is None:
            return ToolResult("MCP 客户端事件循环不可用", ok=False)

        config = next((item for item in self._configs if item.name == server_name), None)
        timeout = config.timeout if config else DEFAULT_CALL_TIMEOUT
        future: concurrent.futures.Future = concurrent.futures.Future()
        command = _Command(
            kind="call",
            future=future,
            server=server_name,
            tool=original_name,
            arguments=dict(arguments),
            timeout=timeout,
        )
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, command)
        except RuntimeError as exc:
            return ToolResult(f"MCP 客户端已停止：{exc}", ok=False)

        try:
            return future.result(timeout=timeout + 10)
        except concurrent.futures.TimeoutError:
            return ToolResult(
                f"MCP 工具 {exposed_name} 调用超时（{timeout:g} 秒）", ok=False
            )
        except BaseException as exc:
            return ToolResult(
                f"MCP 工具 {exposed_name} 调用失败：{_describe_exception(exc)}",
                ok=False,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._started or self._loop is None or self._queue is None:
            return

        future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, _Command(kind="shutdown", future=future)
            )
            with suppress(BaseException):
                future.result(timeout=10)
        except RuntimeError:
            pass
        finally:
            with suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=10)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async())
        except BaseException as exc:
            self.add_warning(f"MCP 客户端启动失败：{_describe_exception(exc)}")
            self._ready_event.set()
            loop.close()
            return
        self._ready_event.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                loop.close()

    async def _start_async(self) -> None:
        self._queue = asyncio.Queue()
        self._ready_async = asyncio.Event()
        asyncio.create_task(self._worker_main())
        await self._ready_async.wait()

    async def _worker_main(self) -> None:
        try:
            await self._connect_all()
        except BaseException as exc:
            self.add_warning(f"MCP 客户端连接过程异常：{_describe_exception(exc)}")
        finally:
            if self._ready_async is not None:
                self._ready_async.set()

        assert self._queue is not None
        while True:
            command = await self._queue.get()
            if command is None or command.kind == "shutdown":
                try:
                    await self._close_connections()
                except BaseException as exc:
                    self.add_warning(f"关闭 MCP 连接时出错：{_describe_exception(exc)}")
                if command is not None and not command.future.done():
                    command.future.set_result(None)
                break

            try:
                connection = self._connections.get(command.server)
                if connection is None:
                    raise RuntimeError(
                        f"MCP Server「{command.server}」未连接"
                    )
                result = await asyncio.wait_for(
                    connection.session.call_tool(
                        command.tool, arguments=command.arguments
                    ),
                    timeout=command.timeout,
                )
                command.future.set_result(_format_call_result(result))
            except BaseException as exc:
                if not command.future.done():
                    command.future.set_exception(exc)

        await self._close_connections()

    async def _connect_all(self) -> None:
        discovered: list[tuple[str, list[Any]]] = []
        for config in self._configs:
            try:
                connection, tools = await self._open_connection(config)
            except BaseException as exc:
                self.add_warning(
                    f"MCP Server「{config.name}」连接失败：{_describe_exception(exc)}"
                )
                continue

            self._connections[config.name] = connection
            if not tools:
                self.add_warning(f"MCP Server「{config.name}」已连接，但没有提供任何工具")
                continue
            discovered.append((config.name, tools))

        self._register_tools(discovered)

    async def _open_connection(
        self, config: MCPServerConfig
    ) -> tuple[_Connection, list[Any]]:
        try:
            from mcp import ClientSession, StdioServerParameters
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的友好提示
            raise RuntimeError(
                "缺少 mcp 依赖，请先执行：pip install -r requirements.txt"
            ) from exc

        stack = AsyncExitStack()
        try:
            if config.transport == "stdio":
                from mcp.client.stdio import stdio_client

                parameters = StdioServerParameters(
                    command=config.command or "",
                    args=list(config.args),
                    env=dict(config.env) if config.env else None,
                    cwd=config.cwd,
                )
                streams = await stack.enter_async_context(stdio_client(parameters))
            elif config.transport == "streamable_http":
                streams = await self._enter_streamable_http(stack, config)
            elif config.transport == "sse":
                streams = await self._enter_sse(stack, config)
            else:  # pragma: no cover - 配置解析阶段已拦截
                raise MCPConfigError(f"不支持的 MCP 协议：{config.transport}")

            read_stream, write_stream = streams[0], streams[1]
            try:
                session = ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=config.timeout,
                )
            except TypeError:  # 兼容旧版 SDK 的参数差异
                session = ClientSession(read_stream, write_stream)
            session = await stack.enter_async_context(session)

            initialize_result = await session.initialize()
            list_result = await session.list_tools()
            tools = list(_attr(list_result, "tools", default=()) or ())

            server_info = _attr(
                initialize_result, "server_info", "serverInfo", default=None
            )
            info_name = _attr(server_info, "name", "title", default="") or ""
            return _Connection(
                config=config,
                stack=stack,
                session=session,
                server_info=str(info_name),
            ), tools
        except BaseException:
            with suppress(BaseException):
                await stack.aclose()
            raise

    async def _enter_streamable_http(
        self, stack: AsyncExitStack, config: MCPServerConfig
    ) -> Any:
        try:
            from mcp.client.streamable_http import (
                streamable_http_client as new_client,
            )
        except ImportError:
            from mcp.client.streamable_http import (
                streamablehttp_client as legacy_client,
            )

            return await stack.enter_async_context(
                legacy_client(
                    config.url or "",
                    headers=dict(config.headers) if config.headers else None,
                    timeout=min(config.timeout, self._connect_timeout),
                    sse_read_timeout=config.timeout,
                )
            )

        http_client = None
        if config.headers:
            try:
                from mcp.client.streamable_http import create_mcp_http_client

                http_client = await stack.enter_async_context(
                    create_mcp_http_client(headers=dict(config.headers))
                )
            except (ImportError, TypeError):
                http_client = None
        return await stack.enter_async_context(
            new_client(config.url or "", http_client=http_client)
        )

    async def _enter_sse(
        self, stack: AsyncExitStack, config: MCPServerConfig
    ) -> Any:
        try:
            from mcp.client.sse import sse_client
        except ImportError as exc:
            raise RuntimeError("当前 mcp 版本不支持 SSE 传输") from exc
        return await stack.enter_async_context(
            sse_client(
                config.url or "",
                headers=dict(config.headers) if config.headers else None,
                timeout=min(config.timeout, self._connect_timeout),
                sse_read_timeout=config.timeout,
            )
        )

    def _register_tools(self, discovered: list[tuple[str, list[Any]]]) -> None:
        sanitized: list[tuple[str, str, Any, str]] = []
        base_counts: dict[str, int] = {}

        for server_name, tools in discovered:
            for tool in tools:
                original_name = str(_attr(tool, "name", default="") or "")
                if not original_name:
                    continue
                base = _sanitize_tool_name(original_name)[:MAX_TOOL_NAME_LENGTH]
                base_counts[base] = base_counts.get(base, 0) + 1
                sanitized.append((server_name, original_name, tool, base))

        used: set[str] = set()
        for server_name, original_name, tool, base in sanitized:
            needs_prefix = (
                base in self._local_tool_names or base_counts.get(base, 0) > 1
            )
            preferred = base
            if needs_prefix:
                preferred = _sanitize_tool_name(f"{server_name}__{original_name}")

            exposed = preferred[:MAX_TOOL_NAME_LENGTH]
            index = 2
            while exposed in used:
                suffix = f"__{index}"
                exposed = preferred[: MAX_TOOL_NAME_LENGTH - len(suffix)] + suffix
                index += 1
            used.add(exposed)

            schema = _attr(tool, "input_schema", "inputSchema", default=None)
            if not isinstance(schema, Mapping):
                schema = {"type": "object", "properties": {}}
            else:
                schema = dict(schema)
                schema.setdefault("type", "object")
                schema.setdefault("properties", {})

            raw_description = str(_attr(tool, "description", default="") or "").strip()
            if not raw_description:
                raw_description = f"MCP 工具 {original_name}"
            description = f"[MCP:{server_name}] {raw_description}"

            mcp_tool = MCPTool(
                name=exposed,
                description=description,
                parameters=schema,
                server=server_name,
                original_name=original_name,
                manager=self,
            )
            self._tools.append(mcp_tool)
            self._tool_map[exposed] = (server_name, original_name)
            self._server_tools.setdefault(server_name, []).append(exposed)

    async def _close_connections(self) -> None:
        connections = list(self._connections.values())
        self._connections.clear()
        for connection in reversed(connections):
            with suppress(BaseException):
                await connection.stack.aclose()
