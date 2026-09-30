# 🐾 宠物医院 MCP Server 开发提示词（MCP 2026-07-28 · Python SDK v2.2.0）

> 本文档是给「AI 开发 Agent」的结构化开发指令。请严格按「开发步骤」逐步执行，
> 每完成一步对照「验证清单」自检，全部通过后再交付。
>
> **本次只做第一版（最小可行 MCP Server）**：跑通 MCP 协议对接 + 核心查询工具，
> **只读、不做任何写操作**。后续功能在「后续迭代」中逐步补全。

---

## 一、角色与目标

你是一名 MCP Server 开发工程师。请开发一个 **Python MCP Server**：
把本地宠物医院 REST API（Go，端口 `127.0.0.1:8080`）暴露为标准 **MCP Tools**，
供其他 **Agent / MCP Client** 统一消费（如 Claude、各类支持 MCP 的 Agent 框架）。

**开发语言：只用 Python，不要用 Go。** REST API 后端才是 Go；MCP Server 一律 Python。

- **必须使用最新协议**：MCP **2026-07-28**（正式版，无会话、无状态）
- **必须使用官方 Python SDK v2**（本机已安装 `mcp==2.2.0`，Python 3.13.7）
- **MCP Server 不直接碰数据库**，一切数据只通过 REST API 间接获取
- **第一版只做基本查询：`list_pets` 等列表/检索类 Tool，支持按不同参数筛选**；写操作与其余接口留到后续迭代

### 现有系统事实（已实测核实，勿臆造）

| 项 | 值 |
|---|---|
| REST 服务 | `pethospital.exe`（Windows amd64），监听 `127.0.0.1:8080` |
| 数据库 | `data/pet.db`（单文件嵌入式，已含 1008 条模拟数据） |
| 接口总数 | 29 个（详见 `http://127.0.0.1:8080/api/v1/endpoints`） |
| 统一响应信封 | `{"code":200,"message":"ok","data":{...},"time":"..."}` |
| 健康检查 | `GET /health` → 200 |
| 启动命令 | `pethospital.exe`（双击或命令行），或 `go run . -addr 127.0.0.1:8080 -seed -count 100` |

### 关键端点实测返回结构（已实测确认）

| 端点 | `data` 字段即返回结构 |
|---|---|
| `GET /api/v1/pets` | `{items: [...], total, page, pageSize, totalPages, totalCost}` |
| `GET /api/v1/pets/{id}` | 单个宠物完整对象（含 `records[]`、`charges[]`、`totalCost`、`visitCount`） |
| `GET /api/v1/pets/search?q=` | `{items: [...], total, page, pageSize, totalPages, totalCost}` |
| `GET /api/v1/stats` | `{totalPets, totalRecords, totalCharges, totalRevenue, averageCost, maxCost, bySpecies, byStatus, byDoctor, revenueByDoctor, ...}` |

---

## 二、技术约束

1. **开发语言：Python 3.10+（本机 3.13.7）。禁止使用 Go 开发 MCP Server。**
2. 依赖：仅 `mcp[cli]>=2.0.0`（本机 2.2.0，已含 httpx）、`httpx>=0.27`
3. HTTP 客户端只允许用 `httpx`
4. **不操作数据库**，不加第三方数据库驱动
5. 工具 docstring 与错误信息使用**中文**
6. 关键逻辑注释使用**中文**
7. 工具函数用 `snake_case`，类型标注必须完整（SDK 依据类型生成 JSON Schema）
8. 每个 Tool 的 docstring 必须写清：参数取值字典、示例、返回内容结构
9. MCP 协议行为以官方规范为准，存在疑问时先查规范再写代码
10. **第一版范围克制：只做读（查询）类 Tool，不做批量/写入/导出/管理**

---

## 三、MCP 2026-07-28 协议要点（务必遵守，以下已核对官方规范）

旧协议（2025-11-25 及更早）是有会话的：先 `initialize` 握手 → 返回 `Mcp-Session-Id` → 后续每次请求携带该头。
**2026-07-28 已彻底移除会话，转为无状态协议。** 关键变化：

| 变化 | 说明 |
|---|---|
| **无状态核心** | 移除 `initialize` / `initialized` 握手（SEP-2575），移除 `Mcp-Session-Id` 头（SEP-2567）。每个请求自包含、可被任意实例处理 |
| **`_meta` 字段** | 每个请求携带 `io.modelcontextprotocol/protocolVersion`、`io.modelcontextprotocol/clientInfo`、`io.modelcontextprotocol/clientCapabilities` |
| **`server/discover`** | 客户端用它一次性获取服务器能力（替代旧握手协商） |
| **要求请求头** | Streamable HTTP 必须携带 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 三个头（SEP-2243）；头与 body 不一致时返回 `400` + 错误码 `-32020 HeaderMismatch` |
| **MRTR** | 服务端可通过 `resultType:"input_required"` + `inputResponses` 向客户端发起多轮请求（SEP-2322） |
| **列表缓存** | `tools/list`、`resource-read` 结果带 `ttlMs` 与 `cacheScope`（SEP-2549），客户端据此决定缓存时长 |
| **订阅** | `subscriptions/listen` 通过 SSE 流推送变更通知 |
| **无 C2S 通知** | Streamable HTTP 上不再有客户端→服务端通知；关闭 SSE 响应流即视为取消 |
| **弃用项** | roots / sampling / logging 已弃用（SEP-2577，仍有一年窗口期），**不要在新代码中使用** |

### 协议错误语义（实现时注意）

- 不支持的协议版本 → HTTP `400` + `UnsupportedProtocolVersionError`（需在错误中列出支持的版本）
- 未知 RPC 方法 → HTTP `404` + JSON-RPC 错误 `-32601 Method not found`

### Streamable HTTP 请求示例

```http
POST /mcp HTTP/1.1
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: search
Content-Type: application/json

{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search","arguments":{"q":"肠胃炎"},
 "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
          "io.modelcontextprotocol/clientInfo":{"name":"my-agent","version":"1.0"}}}}
```

> 用官方 Python SDK v2 开发时，以上握手/会话/头部大多由 SDK 自动完成，
> 但**对应到传输层的配置（`stateless_http=True`）必须显式开启**，且代码中不得再依赖会话。

---

## 四、Python SDK v2 用法（已在本机 v2.2.0 验证）

### 安装

```bash
pip install "mcp[cli]>=2.0.0" httpx
```

### 核心 API

```python
from mcp.server import MCPServer   # v2 中 FastMCP 已更名为 MCPServer

mcp = MCPServer("pet-hospital")

@mcp.tool()
def add(a: int, b: int) -> int:
    """两数相加。"""
    return a + b

# stdio 模式（默认，供本地 MCP 客户端拉起）
mcp.run()

# Streamable HTTP 模式（无状态，符合 2026-07-28）
mcp.run(
    transport="streamable-http",
    host="127.0.0.1",
    port=8081,
    stateless_http=True,          # 关键：显式开启无状态
)
```

- `MCPServer.run(transport="stdio"|"sse"|"streamable-http", **kwargs)`；
  HTTP 专用参数：`host`、`port`、`streamable_http_path`（默认 `/mcp`）、`json_response`、`stateless_http`
- 其余装饰器：`@mcp.resource("uri://template")`、`@mcp.prompt()`
- 错误抛出：`from mcp.server.mcpserver.exceptions import ToolError`，`raise ToolError("中文提示")`
- SDK v2 **一个端点同时服务 2025-11-25 与 2026-07-28 两种客户端**，`server/discover` 自动应答，无需手写
- 开发调试：`mcp dev server.py`（打开 MCP Inspector，需 `npx`）

---

## 五、第一版 Tool 范围（只实现这 3 个基本查询 Tool，以 `list_pets` 参数筛选为核心）

**本版只做「读」：通过不同参数筛选宠物数据，供 Agent 消费。不做任何写操作。**

响应信封统一为 `{"code","message","data","time"}`。**工具返回 `data` 字段内容**（保持为
`dict`/`list` 结构化对象），不要返回整个信封；出错时抛中文 `ToolError`。

### Tool 1：`list_pets`（重点，支持多参数筛选）

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 |
| `species` | str? | None | 按种类筛选：犬/猫/兔/鸟/仓鼠/爬宠/其他 |
| `doctor` | str? | None | 按主治医生筛选 |
| `disease` | str? | None | 按疾病筛选 |
| `status` | str? | None | 按就诊状态筛选：待就诊/就诊中/住院中/已康复/慢性病随访 |
| `sort_by` | str | createdAt | id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt |
| `order` | str | desc | asc/desc |

- 实现为可选过滤参数组合，未传的参数不加入查询条件
- REST 侧参数为 camelCase：`pageSize` `sortBy`，在 Tool 内转换
- 返回 `data` 即 `{items, total, page, pageSize, totalPages, totalCost}`

### Tool 2：`get_pet`

- 参数：`id`（格式 `PET-000001`）
- `GET /api/v1/pets/{id}`，返回单只宠物完整档案（病历、消费明细、费用汇总）
- ID 不存在（如 `PET-999999`）→ 中文 `ToolError`，不崩溃

### Tool 3：`search_pets`

- 参数：`q`（全文检索，空格分词 AND 匹配）
- `GET /api/v1/pets/search?q=`，跨字段检索（姓名、种类、品种、主人、医生、疾病、状态、病历全文、收费项目）
- 示例：`q="肠胃炎"`、`q="犬 张三"`、`q="骨折 李医生"`

### 枚举字典（写进 docstring）

- `species`：犬 / 猫 / 兔 / 鸟 / 仓鼠 / 爬宠 / 其他
- `status`：待就诊 / 就诊中 / 住院中 / 已康复 / 慢性病随访
- `sort_by`：id / name / ownerName / species / doctor / disease / status / totalCost / visitCount / createdAt / updatedAt
- `order`：asc / desc

---

## 六、后续迭代（本次**不要**实现，仅作目录规划）

| 阶段 | 内容 |
|------|------|
| 迭代 2 | 写操作：`create_pet`、`update_pet`、`patch_pet`、`delete_pet` |
| 迭代 3 | 高级查询：`pets_by_owner`、`pets_by_doctor`、`pets_by_species`、`pets_by_disease`、`pets_by_status`、`top_spenders`、`cost_range` |
| 迭代 4 | 病历与收费：`get/add_pet_record`、`get/add_pet_charge`、`get_pet_summary` |
| 迭代 5 | 批量与管理：`batch_create/delete_pets`、`get_meta`、`get_endpoints`、`export_pets`、`compact_db`、`seed_data` |
| 迭代 6 | 补充 `get_stats`、`get_health` 等系统/统计工具 |

---

## 七、项目结构（第一版）

```
pet-hospital-mcp-server/
├── server.py          # 入口：注册 Tool + 启动（stdio 默认 / --http 切 HTTP）
├── client.py          # httpx 封装：_get 等，错误→中文 ToolError
├── config.py          # API_BASE、MCP_HOST、MCP_PORT、MCP_STATELESS_HTTP
├── pyproject.toml     # 依赖与脚本入口
├── README.md          # 使用说明
└── tools/
    ├── __init__.py
    └── pet_crud.py    # 第一版：list_pets, get_pet, search_pets（查询+筛选）
```

---

## 八、代码模板（已在本机 SDK 2.2.0 验证签名）

### config.py

```python
"""全局配置：REST API 地址与 MCP Server 监听地址。"""

API_BASE = "http://127.0.0.1:8080"

MCP_HOST = "127.0.0.1"
MCP_PORT = 8081

# MCP 2026-07-28 为无状态协议：SDK 需显式开启 stateless_http
MCP_STATELESS_HTTP = True
```

### client.py

```python
"""HTTP 客户端封装：_get（第一版只用 _get）。

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


def _request(method: str, path: str, params: dict | None = None) -> dict:
    """统一请求：解包 REST 信封中的 data 字段返回。"""
    try:
        resp = _client.request(method, f"{API_BASE}{path}", params=params)
        resp.raise_for_status()
        body = resp.json()
        return body.get("data", body)
    except httpx.HTTPStatusError as e:
        _handle_error(method, path, e)


def _get(path: str, params: dict | None = None) -> dict:
    return _request("GET", path, params=params)
```

### server.py

```python
"""宠物医院 MCP Server（第一版）- 基于 MCP 2026-07-28 协议（Python SDK v2）。"""

import argparse

from mcp.server import MCPServer

from config import MCP_HOST, MCP_PORT, MCP_STATELESS_HTTP


def build_mcp() -> MCPServer:
    """注册全部 Tool 后返回 MCPServer 实例。"""
    from tools.pet_crud import register_pet_crud_tools

    mcp = MCPServer("pet-hospital")
    register_pet_crud_tools(mcp)
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
```

### tools/pet_crud.py（第一版 3 个基本查询 Tool）

```python
"""宠物档案查询工具（第一版）。

包含 3 个基本查询 Tool：
- list_pets    查询宠物列表（多参数筛选 + 排序 + 分页）
- get_pet      按 ID 查询单个宠物完整档案
- search_pets  全文检索宠物
"""

from client import _get


def register_pet_crud_tools(mcp) -> None:
    """注册本模块所有 Tool。"""

    @mcp.tool()
    def list_pets(
        page: int = 1,
        page_size: int = 20,
        species: str | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: str | None = None,
        sort_by: str = "createdAt",
        order: str = "desc",
    ) -> dict:
        """查询宠物列表，支持按种类/医生/疾病/状态筛选、排序和分页。

        species 取值: 犬/猫/兔/鸟/仓鼠/爬宠/其他
        status 取值: 待就诊/就诊中/住院中/已康复/慢性病随访
        sort_by 取值: id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt
        order 取值: asc/desc
        返回: {items, total, page, pageSize, totalPages, totalCost}
        """
        params: dict = {"page": page, "pageSize": page_size}
        if species:
            params["species"] = species
        if doctor:
            params["doctor"] = doctor
        if disease:
            params["disease"] = disease
        if status:
            params["status"] = status
        if sort_by:
            params["sortBy"] = sort_by
        if order:
            params["order"] = order
        return _get("/api/v1/pets", params)

    @mcp.tool()
    def get_pet(id: str) -> dict:
        """按 ID 查询单个宠物档案，包含完整信息（病历、消费明细、费用汇总）。

        id 格式: PET-000001, PET-000002, ...
        宠物不存在时抛中文错误提示。
        """
        return _get(f"/api/v1/pets/{id}")

    @mcp.tool()
    def search_pets(q: str) -> dict:
        """全文检索宠物（跨字段，空格分词 AND 匹配）。

        检索范围：宠物姓名、种类、品种、主人、医生、疾病、状态、病历全文、收费项目。
        示例: q="肠胃炎"、q="犬 张三"、q="骨折 李医生"
        """
        return _get("/api/v1/pets/search", {"q": q})
```

### pyproject.toml

```toml
[project]
name = "pet-hospital-mcp-server"
version = "0.1.0"
description = "宠物医院 MCP Server（第一版·查询 · MCP 2026-07-28 · Python SDK v2）"
requires-python = ">=3.10"
dependencies = [
    "mcp[cli]>=2.0.0",
    "httpx>=0.27",
]

[project.scripts]
pet-mcp = "server:main"

[tool.uv]
package = false
```

---

## 九、开发步骤（第一版）

1. **后端就绪**：启动 `pethospital.exe`（或 `go run . ...`），`curl http://127.0.0.1:8080/health` 返回 200；
   `curl -s "http://127.0.0.1:8080/api/v1/pets?species=犬&page=1&pageSize=5"` 确认 data 结构与筛选效果。
2. **搭建骨架**：创建 `config.py` / `client.py`，用 `curl` 实测 `GET /api/v1/pets`、`{id}`、`/search` 三接口，确认信封与 `data` 内容。
3. **实现 3 个 Tool**：完成 `tools/pet_crud.py` 并与 `server.py` 串联；先 stdio 跑通。
4. **验证**：按下方验证清单自检，全部通过后再交付。
5. **收尾**：补全 `README.md`，给出接入其他 MCP 客户端的配置示例（见第十一节）。
6. **不要**实现第六节的后续迭代内容，留待下一轮。

---

## 十、验证清单（全部通过才算完成）

前置：后端已启动且 `/health` 200。

1. 依赖正确：`pip show mcp` 输出 **2.x**（本机 2.2.0）。
2. 语法与导入：`python -c "import server"` 无报错。
3. **stdio 启动**：`python server.py` 正常启动、无报错。
4. **HTTP 启动**：`python server.py --http`，端点 `http://127.0.0.1:8081/mcp` 可用（可用 `mcp dev server.py` 检查）。
5. **tools/list 数量**：返回 **3 个工具**：`list_pets`、`get_pet`、`search_pets`。
6. `list_pets` 各筛选参数单独及组合生效：
   - `species=犬` 只返回犬
   - `doctor=*` 只返回该医生
   - `disease=*` 只返回该疾病
   - `status=住院中` 只返回住院中
   - `sort_by=totalCost&order=desc` 按花费降序
   - 不传筛选参数返回全量分页结果
7. `get_pet` 传入真实 ID 返回完整档案；传不存在 ID（如 `PET-999999`）抛**中文 ToolError**，不崩溃。
8. `search_pets(q="肠胃炎")` 返回非空结果。
9. `list_pets` 传非法枚举值（如 `species=龙`）返回友好错误而非 500。
10. 用官方 `Client` 走一遍自动发现（`server/discover`）确认协议版本为 `2026-07-28`。
11. HTTP 模式下 `Mcp-Method` / `Mcp-Name` / `MCP-Protocol-Version` 头部由 SDK 正确处理（用 Inspector 或抓包确认一次）。
12. `mcp dev server.py` 在 Inspector 中手工调用 3 个 Tool 成功。

> 用以下 Python 片段做自动化冒烟（stdio）：
> ```python
> import anyio
> from mcp import Client
> from server import build_mcp
>
> async def smoke() -> None:
>     async with Client(build_mcp()) as client:
>         print("protocol:", client.protocol_version)
>         tools = await client.list_tools()
>         print("tools:", sorted(t.name for t in tools.tools))
>         r = await client.call_tool("list_pets", {"page": 1, "page_size": 5, "species": "犬"})
>         print("list_pets(filtered) ok:", len(str(r.content)) > 0)
>
> anyio.run(smoke)
> ```

---

## 十一、接入其他 Agent / MCP Client 的方式

### Stdio（本地拉起，推荐给 CLI 类 Agent）

```json
{
  "mcp": {
    "pet-hospital": {
      "type": "stdio",
      "command": "python",
      "args": ["D:\\zuoye\\pet-hospital-mcp-teaching-main\\pet-hospital-mcp-server\\server.py"],
      "enabled": true
    }
  }
}
```

### Streamable HTTP（网络访问）

启动 `python server.py --http` 后，MCP 端点为 `http://127.0.0.1:8081/mcp`，
任何 **2026-07-28 协议兼容的 Agent（Claude / 各类支持 MCP 的 Agent 框架）** 均可连接：

```json
{
  "mcp": {
    "pet-hospital": {
      "type": "remote",
      "url": "http://127.0.0.1:8081/mcp",
      "enabled": true
    }
  }
}
```

---

## 十二、参考资料（仅参考，实现以官方为准）

- MCP 2026-07-28 规范：https://modelcontextprotocol.io/specification/2026-07-28
- 规范变更日志：https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Streamable HTTP：https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- Python SDK v2 文档：https://py.sdk.modelcontextprotocol.io/
- SDK v2 What's new：https://py.sdk.modelcontextprotocol.io/whats-new
- REST API 文档：项目内 `pet-hospital-windows-amd64/windows/README.md`
- 端点清单（运行时可查）：`http://127.0.0.1:8080/api/v1/endpoints`

---

*生成时间: 2026-09-18*
*协议版本: MCP 2026-07-28（正式版·无状态，配置文件 `opencode.json` 中 Bazi-MCP 亦为 remote 型，可作对照）*
*Python SDK: mcp 2.2.0（已在本机验证）*
*第一版范围: 3 个基本查询 Tool（list_pets / get_pet / search_pets），全部只读，支持参数筛选*