# Practice02 — 基于大模型 Function Calling 的命令行 Agent 实践

本目录包含三个逐步递进的命令行（CLI）对话 Agent 示例，采用 OpenAI 兼容的 `/chat/completions` 接口、**流式输出（SSE）** 与 **Function Calling（工具调用）**。

| 文件 | 说明 | 内置工具 |
| --- | --- | --- |
| `main-getdate.py` | 入门版：让模型通过工具获取本机当前日期时间 | `getDate` |
| `main-isleapyear.py` | 进阶版：在 `getDate` 基础上增加闰年判断工具 | `getDate`、`isLwapYear` |
| `main-filetools.py` | 完整版：具备本地文件/目录读写与操作能力 | 文件读写、目录列举、创建/删除/重命名等 |

> 架构图：`main-isleapyear-architecture.mmd`（Mermaid 格式，可用 Mermaid Live Editor、VS Code 插件或 Typora 渲染）

---

## 一、环境准备

### 1. 依赖

```bash
pip install requests
```

其余模块（`configparser`、`json`、`os`、`subprocess`、`sys`）均为 Python 标准库。

### 2. 配置文件

复制 `config.example.ini` 为 `config.ini`，填入真实参数：

```ini
[openai]
base_url = https://your-endpoint/v1
api_key = your-api-key
model = your-model-name
```

启动时会校验三项均非空且 `api_key` 不为占位符 `your-api-key`，否则直接退出并提示。

### 3. 运行

```bash
python main-isleapyear.py
```

---

## 二、main-isleapyear.py 详解

### 2.1 整体架构

```
配置加载校验 → 初始化 history(system) → while 主循环
      ↓
  input 用户输入（/clear、/exit 命令）
      ↓
  stream_chat(history)  ← 流式请求 + 工具调用增量拼接
      ↓
  有 tool_calls？ ──否──→ 保存 assistant 回复，进入下一轮提问
      ↓是
  execute_tool 本地执行（getDate / isLwapYear）
      ↓
  结果作为 role=tool 回填 history → 再次 stream_chat（最多 5 轮）
```

### 2.2 关键模块

| 模块 | 职责 |
| --- | --- |
| `SYSTEM_PROMPT` | 系统提示词：约束上下文记忆、禁止重复询问、强制工具调用、回复简洁 |
| `TOOLS` | OpenAI 风格工具描述数组，声明 `getDate`（无参）与 `isLwapYear`（`year: integer`） |
| `stream_chat()` | POST 流式请求，解析 `data:` 行；`content` 直接打印并累积；`tool_calls` 按 `index` 增量拼接 `id`/`name`/`arguments` |
| `execute_tool()` | 工具分发器，含 JSON 解析、缺参、类型错误等校验，返回自然语言结果 |
| `get_date()` | 调用 `cmd /c date /t` 与 `cmd /c time /t`，而非用代码计算时间 |
| `decode_cmd_output()` | 依次尝试 `gbk`、`utf-8` 解码 Windows 命令输出，失败则宽松替换 |
| `is_leap_year()` | 闰年算法：`(year % 4 == 0 and year % 100 != 0) or year % 400 == 0` |
| 异常处理 | `requests.RequestException` 回滚用户消息并继续；`KeyboardInterrupt`/`EOFError` 平滑退出 |

### 2.3 交互命令

| 输入 | 行为 |
| --- | --- |
| `/clear` 或 `clear` | 清空上下文，重置为仅含 system 消息 |
| `/exit`、`/quit`、`exit`、`quit` | 退出程序 |
| 其他非空文本 | 追加为 `user` 消息并进入 Agent 循环 |

### 2.4 设计要点

1. **流式输出**：`stream=True` + `iter_lines()` 逐 token 打印，提升响应观感。
2. **工具调用增量拼接**：服务端会把一次 `tool_calls` 拆成多个 delta，必须按 `index` 累加 `name` 与 `arguments` 片段。
3. **循环护栏**：每轮问答最多 5 次工具调用，防止模型反复调用同一工具。
4. **上下文记忆**：`history` 完整保留 user / assistant / tool 消息，保证多轮与指代理解。
5. **提示词与工具名一致**：`SYSTEM_PROMPT` 中明确要求调用 `getDate`、`isLwapYear`，与 `TOOLS` 定义严格对应。

---

## 三、目录结构

```
Practice02/
├── config.example.ini                 # 配置模板
├── config.ini                         # 本地配置（含真实密钥，勿提交）
├── main-getdate.py                    # 入门版：getDate 工具
├── main-isleapyear.py                 # 进阶版：getDate + isLwapYear
├── main-filetools.py                  # 完整版：本地文件操作工具
├── main-isleapyear-architecture.mmd   # 代码架构图（Mermaid）
└── README.md
```

---

## 四、常见问题

- **请求失败：401 / 403**：检查 `api_key` 是否有效、`base_url` 是否包含 `/v1` 等前缀路径。
- **中文乱码**：脚本已通过 `sys.stdout.reconfigure(encoding="utf-8")` 与 `decode_cmd_output()` 处理；若终端仍异常，建议使用 Windows Terminal 或设置 `chcp 65001`。
- **模型不使用工具**：确认所用模型支持 Function Calling，并检查 `SYSTEM_PROMPT` 与 `TOOLS` 是否被服务端正确接收。
- **工具参数报错**：多为模型返回的 `arguments` 非法 JSON 或缺少 `year`，`execute_tool()` 会把错误文本回填给模型自我修正。
