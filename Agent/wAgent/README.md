# wAgent

`wAgent` 是把 `Practice02/main-filetools.py` 改造后的本地文件智能体。项目按 **core（业务核心）+ tui（终端界面）** 分层，核心层不依赖 Textual，便于后续扩展 Web、Desktop 等其他界面。

## 架构

```mermaid
flowchart TB
    subgraph UI["tui/ 界面层"]
        APP["WAgentApp<br/>Textual App"]
        SIDEBAR["侧边栏<br/>任务 / 用量 / 环境 / 工具"]
        HELP["HelpScreen<br/>使用帮助"]
        CSS["app.tcss<br/>界面样式"]
        APP --> SIDEBAR
        APP --> HELP
        APP --> CSS
    end

    subgraph CORE["core/ 业务核心"]
        AGENT["Agent<br/>对话编排 / 工具循环"]
        LLM["OpenAIChatClient<br/>流式 SSE / Tool Calls"]
        EVENTS["events.py<br/>AgentEvent 事件模型"]
        CFG["config.py<br/>配置加载与校验"]
        subgraph TOOLS["tools/ 工具层"]
            REG["ToolRegistry<br/>注册 / 校验 / 分发"]
            BASE["Tool / ToolResult<br/>工具抽象"]
            FS["FileSystemTools<br/>10 个文件系统工具"]
        end
        AGENT --> LLM
        AGENT --> REG
        AGENT --> EVENTS
        REG --> BASE
        REG --> FS
    end

    APP -->|"chat(text, emit)"| AGENT
    AGENT -->|"AgentEvent 回调"| APP
    CFG --> AGENT
    LLM -->|"HTTPS / SSE"| API[("OpenAI 兼容接口")]
```

### 依赖方向

```text
tui  --->  core
core -/->  tui
```

- `core` 只处理配置、大模型调用、上下文、工具注册与执行，不导入 `textual`。
- `tui` 只负责输入、展示和事件消费，通过 `Agent.chat(text, emit)` 驱动核心。
- 新增界面时，复用 `Agent` 与 `AgentEvent` 即可，不需要修改业务逻辑。

## 目录结构

```text
Agent/wAgent/
├── main.py                  # 启动入口（自动处理包路径）
├── __main__.py              # 支持 python -m wAgent
├── requirements.txt
├── config.example.ini
├── core/
│   ├── agent.py             # Agent：多轮对话 + 工具调用循环
│   ├── config.py            # 配置加载、校验、查找顺序
│   ├── events.py            # ContentDelta / ToolStarted 等事件
│   ├── llm.py               # OpenAI 兼容流式客户端
│   └── tools/
│       ├── base.py          # Tool、ToolResult 抽象
│       ├── filesystem.py    # 文件系统工具实现
│       ├── registry.py      # 工具注册与 JSON 参数分发
│       └── __init__.py      # 默认工具集装配
└── tui/
    ├── app.py               # Textual 应用、侧边栏与事件渲染
    ├── help.py              # F1 / /help 使用帮助弹窗
    ├── app.tcss             # 界面样式
    └── __init__.py
```

## 快速开始

```bash
cd D:\zuoye\Agent\wAgent
pip install -r requirements.txt
python main.py
```

也可以从 `Agent` 目录运行：

```bash
python -m wAgent
```

指定配置文件：

```bash
python main.py --config D:\path\to\config.ini
```

## 配置

复制模板并填写真实密钥：

```bash
copy config.example.ini config.ini
```

```ini
[openai]
base_url = https://api.deepseek.com/v1
api_key = your-api-key
model = deepseek-chat

[agent]
max_tool_rounds = 10
request_timeout = 60
```

配置查找顺序：

1. `--config` 指定路径
2. 环境变量 `WAGENT_CONFIG`
3. `wAgent/config.ini`
4. `Agent/Practice02/config.ini`（兼容旧配置）
5. 当前工作目录下的 `config.ini`

## TUI 操作

| 操作 | 说明 |
|------|------|
| `Enter` | 发送问题 |
| 输入 `/` | 在输入框上方弹出命令列表 |
| `Up` / `Down` | 在命令列表中选择 |
| `Tab` | 补全当前选中的命令 |
| `Enter`（命令列表打开时） | 执行当前选中的命令 |
| `Esc` | 关闭命令列表 |
| `/help`、`F1` | 打开使用帮助 |
| `/clear` | 清空对话上下文和界面记录 |
| `/quit`、`/exit` | 退出程序 |
| `Ctrl+B` | 显示或隐藏侧边栏 |
| `Ctrl+L` | 清空上下文 |
| `Ctrl+Q` | 退出程序 |

界面会实时展示：

- 模型流式输出的正文
- 每次工具调用的名称与参数
- 工具执行结果（失败时标红）
- 配置错误、接口错误等异常信息

### 视觉风格

- 主区域、侧边栏和输入框使用中性深色背景，避免大面积高亮底色。
- 边框和面板标题使用强调色，便于划分区域。
- 用户、助手、工具和错误内容使用不同的强调色标签区分，正文保持中性色。
- 命令列表使用低对比度选中背景，仅用强调色标记当前项。
### 侧边栏

右侧边栏固定展示运行状态：

- **任务进度**：当前状态、轮次进度条、本回合工具调用次数、当前工具、耗时、上下文消息数
- **模型使用**：接口请求次数、输入/输出/合计 token 用量（按会话累计）
- **运行环境**：模型、工作目录、接口地址、配置文件路径、超时、最大轮次
- **可用工具**：从工具注册表动态读取的全部工具名称

token 用量来自接口返回的 `usage` 字段。如果服务端不返回该字段，用量会显示为 0。

### 使用帮助

按 `F1` 或在输入框执行 `/help`，会打开帮助页，包含：

- 快速上手步骤
- 命令与快捷键
- 可执行任务与常用示例
- 文件类型、编码、大小限制
- 侧边栏字段说明
- 配置文件查找顺序

## 内置工具

| 工具 | 功能 |
|------|------|
| `getCurrentDirectory` | 获取当前工作目录 |
| `listDirectory` | 列出目录下的文件和子目录 |
| `getFileType` | 获取扩展名、MIME、文本/二进制类型 |
| `readTextFile` | 读取纯文本文件内容 |
| `createFile` | 创建文件，可自动创建多级目录 |
| `editFile` | 覆盖、追加、局部替换文本 |
| `createDirectory` | 创建目录 |
| `deleteDirectory` | 递归删除非空目录 |
| `deleteFile` | 删除文件 |
| `renamePath` | 重命名或移动文件/目录 |

文件工具的限制与保护：

- 仅支持纯文本，当前识别 UTF-8（含 BOM）与 GBK 编码，UTF-16 文件会被视为二进制。
- 读取文件上限为 1 MB。
- 删除和重命名会拒绝磁盘根目录。
- 工具异常统一转换为 `ToolResult(ok=False)`，不会中断对话循环。

## 核心事件流

```python
agent.chat("读取 D:/demo/a.txt", emit=on_event)
```

核心会依次产生：

```text
RoundStarted(number, max) # 新一轮模型调用
ContentDelta(text)        # 模型正文增量
UsageUpdated(tokens)      # 请求次数与 token 用量
AssistantCompleted(text)  # 一轮正文结束
ToolStarted(name, args)   # 开始执行工具
ToolFinished(name, ok)    # 工具执行结果
AgentError(message)       # 请求或配置异常
```

TUI 在后台线程中调用 `agent.chat`，通过 `call_from_thread` 把事件送回 UI 线程渲染。

## 扩展新界面

新增 Web 或 Desktop 界面时，只需要：

1. 在 `wAgent/` 下新建 `web/` 或 `desktop/` 目录。
2. 复用 `Agent` 的构造方式和 `chat(text, emit)` 接口。
3. 将 `AgentEvent` 映射到目标界面的消息模型。

例如：

```python
from wAgent.core.agent import Agent
from wAgent.core.config import load_config

agent = Agent(load_config())

def on_event(event):
    # 推送到 WebSocket、Qt 信号或 HTTP SSE
    ...

agent.chat("列出当前目录", emit=on_event)
```

不要在新的界面层里直接调用 `FileSystemTools` 或拼接大模型请求；工具调用和上下文管理应始终留在 `core`。
