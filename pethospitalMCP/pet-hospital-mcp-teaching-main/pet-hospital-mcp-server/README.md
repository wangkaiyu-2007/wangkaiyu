# 🐾 宠物医院 MCP Server（查询 + 写操作 + 高级查询）

把本地宠物医院 REST API（Go，`127.0.0.1:8080`，数据库 `data/pet.db`，含 1008 条模拟数据）
暴露为标准 **MCP Tools** 的 **Python MCP Server**，供 Claude / 各类支持 MCP 的 Agent 统一消费。

- **协议版本**：MCP **2026-07-28**（正式版 · 无状态 · 无会话）
- **Python SDK**：`mcp==2.2.0`（Python 3.13.7，`mcp[cli]>=2.0.0`）
- **HTTP 客户端**：`httpx>=0.27`
- **当前范围**：11 个 Tool（5 个查询 + 2 个系统/统计 + 4 个写操作），MCP Server 不直接碰数据库，一切数据只通过 REST API 间接获取。

---

## 目录结构

```
pet-hospital-mcp-server/
├── server.py          # 入口：注册 Tool + 启动（stdio 默认 / --http 切 HTTP）
├── client.py          # httpx 封装：_get/_post/_put/_patch/_delete，错误→中文 ToolError
├── config.py          # API_BASE、MCP_HOST、MCP_PORT、MCP_STATELESS_HTTP
├── pyproject.toml     # 依赖与脚本入口（pet-mcp）
├── README.md          # 本文件
└── tools/
    ├── __init__.py
    ├── pet_crud.py    # 9 个 Tool：list_pets, get_pet, search_pets, top_spenders, cost_range_pets, create_pet, update_pet, patch_pet, delete_pet
    └── system.py      # 2 个 Tool：get_stats, get_health
```

## 环境要求与安装

```bash
pip install "mcp[cli]>=2.0.0" httpx
```

验证版本：`python -c "import importlib.metadata as md; print(md.version('mcp'))"` 应输出 `2.x`（本机 2.2.0）。

## 前置：后端就绪

`pethospital.exe`（Windows amd64）需已监听 `127.0.0.1:8080`，健康检查通过：

```bash
curl http://127.0.0.1:8080/health   # → {"code":200,"message":"ok",...}
```

## 启动

### Stdio（默认，供本地 MCP 客户端拉起）

```bash
python server.py
```

### Streamable HTTP（无状态，符合 2026-07-28）

```bash
python server.py --http
```

端点：`http://127.0.0.1:8081/mcp`。SDK 已显式开启 `stateless_http=True`，
`server/discover` 自动应答 `supportedVersions: ["2026-07-28"]`，`MCP-Protocol-Version` /
`Mcp-Method` / `Mcp-Name` 三头自动校验（不一致返回 HTTP 400 + 错误码 `-32020 HeaderMismatch`）。

### 开发调试（MCP Inspector）

```bash
mcp dev server.py
```

## Tools 说明（查询 + 写操作 + 高级查询）

所有 Tool 返回 REST 响应信封中的 `data` 字段（结构化对象），出错抛中文 `ToolError`。

### 1. `list_pets` — 查询宠物列表（多参数筛选 + 排序 + 分页）

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 |
| `species` | str? | None | 种类筛选 |
| `doctor` | str? | None | 主治医生筛选 |
| `disease` | str? | None | 疾病筛选 |
| `status` | str? | None | 就诊状态筛选 |
| `owner_name` | str? | None | 主人姓名筛选 |
| `owner_phone` | str? | None | 主人电话筛选 |
| `sort_by` | str | createdAt | 排序字段 |
| `order` | str | desc | asc / desc |

- 枚举：`species` = 犬/猫/兔/鸟/仓鼠/爬宠/其他；`status` = 待就诊/就诊中/住院中/已康复/慢性病随访
- `sort_by` = id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt
- 未传的筛选参数不加入查询条件；REST 侧 camelCase 参数（`pageSize`/`sortBy`）在 Tool 内自动转换
- 返回结构：`{items, total, page, pageSize, totalPages, totalCost}`

示例：`list_pets(species="犬", status="住院中", sort_by="totalCost", order="desc", page=1, page_size=20)`

### 2. `get_pet` — 按 ID 查询单个宠物完整档案

- 参数：`id`（格式 `PET-000001`）
- 返回单只宠物完整对象（含 `records[]` 病历、`charges[]` 消费明细、`totalCost`、`visitCount`）
- ID 不存在（如 `PET-999999`）→ 抛中文 `ToolError`（`资源不存在 ...：记录不存在: id=...`），不崩溃

### 3. `search_pets` — 全文检索宠物

- 参数：`q`（空格分词 AND 匹配）
- 跨字段检索：宠物姓名、种类、品种、主人、医生、疾病、状态、病历全文、收费项目
- 示例：`q="肠胃炎"`、`q="犬 张三"`、`q="骨折 李医生"`

### 4. `top_spenders` — 消费排行榜

- 参数：`limit`（1-100，默认 5）
- 按在医院总花费降序返回
- 返回：`{limit, items, totalCost, total}`
- 示例：`top_spenders(limit=10)`

### 5. `cost_range_pets` — 按总花费区间查询

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `min_cost` | float? | None | 最低总花费（元） |
| `max_cost` | float? | None | 最高总花费（元） |
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 |

- 自动按花费降序；返回：`{items, total, page, pageSize, totalPages, totalCost}`
- 示例：`cost_range_pets(min_cost=500, max_cost=5000)`

### 6. `get_stats` — 医院经营统计

- 参数：`top`（排行条数，默认 5）
- 返回：`{totalPets, totalRecords, totalCharges, totalRevenue, averageCost, maxCost, bySpecies, byStatus, byDoctor, revenueByDoctor, ...}`

### 7. `get_health` — 健康检查

- 返回：`{status, uptime, dbFile, petCount, timestamp}`

### 8. `create_pet` — 创建新宠物档案

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | str | 是 | 宠物姓名 |
| `species` | str | 是 | 种类（犬/猫/兔/鸟/仓鼠/爬宠/其他） |
| `owner_name` | str | 是 | 主人姓名 |
| `owner_phone` | str | 是 | 主人电话 |
| `doctor` | str | 是 | 主治医生 |
| `disease` | str | 是 | 疾病 |
| `status` | str | 否 | 就诊状态（默认"待就诊"） |
| `breed` | str? | 否 | 品种 |
| `gender` | str? | 否 | 性别（公/母） |
| `age_months` | int? | 否 | 月龄 |
| `color` | str? | 否 | 毛色 |
| `chip_no` | str? | 否 | 芯片号 |
| `owner_addr` | str? | 否 | 主人住址 |
| `allergy` | str? | 否 | 过敏史 |
| `note` | str? | 否 | 备注 |

- 返回：创建的宠物档案对象（含自动生成的 ID）
- 示例：`create_pet(name="旺财", species="犬", owner_name="张三", owner_phone="13800001111", doctor="李医生", disease="急性肠胃炎")`

### 9. `update_pet` — 全量更新宠物档案

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | str | 是 | 宠物ID（格式: PET-000001） |
| `name` | str | 是 | 宠物姓名 |
| `species` | str | 是 | 种类（犬/猫/兔/鸟/仓鼠/爬宠/其他） |
| `owner_name` | str | 是 | 主人姓名 |
| `owner_phone` | str | 是 | 主人电话 |
| `doctor` | str | 是 | 主治医生 |
| `disease` | str | 是 | 疾病 |
| `status` | str | 是 | 就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访） |
| `breed` | str? | 否 | 品种 |
| `gender` | str? | 否 | 性别（公/母） |
| `age_months` | int? | 否 | 月龄 |
| `color` | str? | 否 | 毛色 |
| `chip_no` | str? | 否 | 芯片号 |
| `owner_addr` | str? | 否 | 主人住址 |
| `allergy` | str? | 否 | 过敏史 |
| `note` | str? | 否 | 备注 |

- 未传的字段会清空，如需部分更新请用 `patch_pet`
- 返回：更新后的宠物档案对象
- 示例：`update_pet(id="PET-000001", name="旺财", species="犬", owner_name="张三", owner_phone="13800001111", doctor="李医生", disease="急性肠胃炎", status="已康复")`

### 10. `patch_pet` — 局部更新宠物档案

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | str | 是 | 宠物ID（格式: PET-000001） |
| 其他参数 | 各类型 | 否 | 只更新传入的字段 |

- 只更新传入的字段，未传字段保持不变
- 返回：更新后的宠物档案对象
- 示例：`patch_pet(id="PET-000001", status="已康复")`

### 11. `delete_pet` — 删除宠物档案

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | str | 是 | 宠物ID（格式: PET-000001） |

- 返回：删除结果（含删除的 ID）
- 示例：`delete_pet(id="PET-000001")`

---

## 接入其他 Agent / MCP Client

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

先 `python server.py --http`，再用任何 2026-07-28 协议兼容的 Agent 连接：

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

## 验证清单（已全部通过）

1. ✅ 依赖：`mcp==2.2.0`、`httpx==0.28.1`
2. ✅ 语法与导入：`python -c "import server"` 无报错
3. ✅ stdio 启动：`python server.py` 正常（SDK stdio Client 拉起真实进程自动发现成功）
4. ✅ HTTP 启动：`python server.py --http`，`127.0.0.1:8081/mcp` 可用
5. ✅ `tools/list`：返回 11 个工具 `list_pets` / `get_pet` / `search_pets` / `top_spenders` / `cost_range_pets` / `get_stats` / `get_health` / `create_pet` / `update_pet` / `patch_pet` / `delete_pet`
6. ✅ `list_pets`：`species=犬`、`doctor=王医生`、`disease=急性肠胃炎`、`status=住院中` 均只返回对应数据；
   `sort_by=totalCost&order=desc` 花费降序；组合筛选生效；不传筛选返回全量分页
7. ✅ `get_pet`：真实 ID（`PET-000001`）返回完整档案；`PET-999999` 抛中文 `ToolError`（`is_error=true`），不崩溃
8. ✅ `search_pets(q="肠胃炎")` 返回非空（total=38）
9. ✅ `create_pet`：创建新宠物档案，返回完整对象（含自动生成 ID）
10. ✅ `update_pet`：全量更新宠物档案，未传字段会清空
11. ✅ `patch_pet`：局部更新宠物档案，只更新传入字段
12. ✅ `delete_pet`：删除宠物档案，返回删除结果
13. ✅ `server/discover` 自动发现：协议版本 `2026-07-28`（stdio 与 HTTP 均已确认）
14. ✅ HTTP 模式三头校验：`Mcp-Method`/`Mcp-Name`/`MCP-Protocol-Version` 由 SDK 正确处理，
    不一致时 HTTP 400 + `-32020 HeaderMismatch`
15. ⏳ `mcp dev server.py` Inspector 手工调用（需要 npx + 浏览器，本机已具备 `npx`）

## 后续迭代（本版未实现）

病历与收费写操作（`add_pet_record` / `add_pet_charge` / `get_pet_summary`）。
批量与管理类（`batch_*`、`export`、`compact`、`seed`、`get_meta`）因 Agent 场景用不到，
刻意不做，避免冗余与过度设计。