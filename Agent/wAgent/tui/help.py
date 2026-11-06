from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static


HELP_TEXT = """
# wAgent 使用帮助

## 快速开始

1. 在底部输入框输入自然语言问题，按 `Enter` 发送。
2. 需要分段描述时按 `Shift+Enter`（或 `Ctrl+J`）换行；输入框会自动换行并随内容增高。
3. Agent 会自动判断是否需要调用文件工具。
4. 工具执行过程、结果和模型回复会实时显示在主区域。
5. 右侧边栏展示任务进度、模型用量、运行环境和可用工具。

## 命令与快捷键

- `Enter`：发送当前输入
- `Shift+Enter` 或 `Ctrl+J`：在输入框中手动换行
- 输入框支持自动换行，内容变多时会自动增高（最高 9 行，超出后内部滚动）
- `/help` 或 `F1`：打开本帮助页
- `/new` 或 `Ctrl+N`：新建会话，并自动保存当前会话
- `/resume` 或 `/sessions`：打开历史会话列表，用 `Up/Down` 选择、`Enter` 恢复、`Esc` 取消
- `/save`：保存当前会话到 `.agents/sessions/`
- `/status`：查看会话、上下文和 MCP 状态
- `/mcp`：查看已连接 MCP 服务器及其可用工具
- `/tools`：在对话区查看全部已注册工具及其简短说明
- `/skills`：在对话区查看已发现的 Agent Skills
- `/compact`：归档当前原始上下文，并调用模型生成压缩摘要
- 输入 `/`：在输入框上方显示可用命令补全引导面板
- 命令列表中可用 `Up/Down` 选择、`Enter` 执行、`Tab` 补全、`Esc` 关闭
- `/clear` 或 `Ctrl+L`：清空对话上下文和聊天记录
- `/quit`、`/exit` 或 `Ctrl+Q`：保存当前会话并退出程序
- `Ctrl+B`：显示或隐藏右侧边栏
- `Esc`：关闭当前帮助页

## 可以完成的任务

- 获取当前工作目录
- 列出目录下的文件和子目录
- 查看文件类型、大小与修改时间
- 读取纯文本文件内容
- 创建文件，并自动创建多级目录
- 覆盖、追加或局部替换文本内容
- 创建目录、删除文件、递归删除非空目录
- 重命名或移动文件与目录
- 读取网页正文并整理为 Markdown（自动去除导航、广告、页脚）
- 搜索互联网最新信息，并整理搜索摘要、来源标题与链接
- 执行本地命令行程序，并查看标准输出、标准错误和退出码
- 按需加载当前项目 `.agents/skills/` 中的 Agent Skill 说明与附件
- 通过 `recallContext` 检索 `.agents/context/` 中归档的历史上下文

## 示例指令

- `列出 D:\\zuoye\\Agent\\wAgent 目录下的内容`
- `读取 D:\\zuoye\\Agent\\wAgent\\README.md，并总结项目结构`
- `在 D:\\zuoye\\demo 下创建 note.txt，内容为 hello`
- `把 note.txt 里的 hello 替换成 hi`
- `把 D:\\zuoye\\demo\\old.txt 重命名为 new.txt`
- `删除 D:\\zuoye\\demo\\temp 目录`
- `读取 https://example.com 的主要内容并总结`
- `搜索最近一周的人工智能行业新闻，并列出参考链接`
- `运行 git --version，并告诉我执行结果`
- `用 python --version 查看当前 Python 版本`

## 文件限制

- 读取和编辑仅支持纯文本文件。
- 当前支持 UTF-8（含 BOM）与 GBK 编码，UTF-16 文件会被识别为二进制。
- 单个文本文件读取上限为 1 MB。
- Word、PDF、图片、压缩包等二进制文件不能直接读取正文。
- 网页读取需要本地已安装 curl，且只支持 http/https 地址；动态渲染或需要登录的页面可能无法提取正文。
- 命令行工具以运行 wAgent 的用户权限执行，默认超时 30 秒，过长输出会被截断；当前未提供白名单或审批机制。
- 删除目录、删除文件、重命名属于破坏性操作，请明确说明目标路径。

## 会话管理与项目约定

- 会话以 JSONL 事件日志保存在当前项目 `.agents/sessions/` 下，包含消息、标题和更新时间。
- `/save` 会写入检查点；`/new` 会先自动保存当前会话再创建新会话；退出时默认自动保存。
- `/resume` 打开历史会话面板，选择后恢复聊天历史、标题和上下文用量。
- 如果当前目录存在 `AGENTS.md`，每个会话首次加载时会把它作为一条消息注入聊天历史并写入会话日志；后续轮次直接复用，不会重复注入。
- 修改 `AGENTS.md` 后如需重新生效，可执行 `/new` 或 `/clear` 开始新的上下文。

## 上下文压缩与历史检索

- 顶部栏实时显示当前上下文用量：已用 k / 模型窗口 k / 占用百分比；无法获取窗口大小时默认按 128k 计算并标注「默认」。
- 每次模型响应后都会检查上下文；达到窗口的警告比例（默认 60%，可通过 `[agent] context_warning_ratio` 配置）时会提示执行 `/compact`，并暂停接受新的普通提示词。
- 执行 `/compact` 时，程序先把完整原始上下文保存到当前目录 `.agents/context/<编号>.jsonl`，再调用模型生成约 5,000 Tokens 的摘要。
- 保存成功后弹出左右两栏对照面板，左侧为压缩前原文，右侧为压缩后摘要，可滚动查看并关闭。
- 压缩成功后会使用摘要替换历史消息，同时保留系统提示与工具定义；摘要末尾附带归档编号说明。
- 当摘要缺少细节时，Agent 可调用 `recallContext` 工具，按关键词检索指定归档或全部归档。
- 压缩失败时原始上下文保持不变，可再次执行 `/compact`。

## 页面结构

- 顶部栏显示 wAgent 标识、当前模型和工作目录。
- 首次进入时，主区域显示居中欢迎页（标识、模型/目录/工具信息和快捷提示）。
- 发送消息后切换为对话区，展示用户消息、助手回复和工具执行结果；清空上下文后回到欢迎页。
- 底部输入区集中显示状态、命令列表、输入框和快捷键提示。
- 右侧边栏展示任务、用量、环境、技能和工具说明；终端宽度小于 100 列时默认隐藏，可按 `Ctrl+B` 打开。

## 侧边栏说明

- 任务进度：当前轮次、状态、工具调用次数和耗时。
- 模型使用：接口请求次数、累计 token 用量与当前上下文占比。
- 运行环境：工作目录、接口地址、配置文件和超时设置。
- MCP 服务器：先进入界面，再在后台异步连接；连接完成后自动刷新已连接服务器和每个服务器的可用工具。
- 可用技能：当前目录 `.agents/skills/` 下发现的所有 Skill 名称与简要说明。
- 可用工具：当前注册的全部工具名称，并附带一句话作用说明。

## 配置

程序会依次查找：

1. `--config` 指定的配置文件
2. 环境变量 `WAGENT_CONFIG`
3. 当前工作目录下的 `config.ini`
4. `wAgent/config.ini`
5. `wAgent/congfig.ini`
6. `Agent/Practice02/config.ini`

配置项包括 `base_url`、`api_key`、`model`、`max_tool_rounds` 和 `request_timeout`。可选配置 `context_window`（上下文窗口大小，支持 `128k` 写法）、`context_warning_ratio`（警告比例）、`compact_summary_tokens`、`compact_max_tokens`、`agents_md_file`，以及 `[tools]`、`[session]`、`[ui]` 下的高级参数。

如果当前目录没有 `config.ini`，程序会自动创建一份包含 mock 占位值的完整配置，并弹出提示对话框；修改 `base_url`、`api_key` 和 `model` 后重新启动即可。

搜索功能需要在 `[search]` 小节配置 `baidu_qianfan_api_key`，可选配置 `top_k` 和 `timeout`。
"""


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-dialog {
        width: 88%;
        height: 88%;
        padding: 1 2;
        border: thick $accent 70%;
        background: $surface;
    }

    #help-title {
        height: 1;
        color: $accent;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #help-scroll {
        height: 1fr;
    }

    #help-actions {
        height: 3;
        align-horizontal: right;
        padding: 1 0 0 0;
    }

    #close-help {
        background: $surface-lighten-1;
        color: $text;
        border: tall $accent;
    }
    """

    BINDINGS = [
        ("escape", "close", "关闭"),
        ("f1", "close", "关闭"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("wAgent 使用帮助", id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Markdown(HELP_TEXT)
            with Horizontal(id="help-actions"):
                yield Button("关闭 (Esc)", id="close-help")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-help":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
