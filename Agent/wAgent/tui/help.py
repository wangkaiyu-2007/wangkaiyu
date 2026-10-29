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
- 输入 `/`：在输入框上方显示可用命令列表
- 命令列表中可用 `Up/Down` 选择、`Enter` 执行、`Tab` 补全、`Esc` 关闭
- `/clear` 或 `Ctrl+L`：清空对话上下文和聊天记录
- `/quit`、`/exit` 或 `Ctrl+Q`：退出程序
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

## 侧边栏说明

- 任务进度：当前轮次、状态、工具调用次数和耗时。
- 模型使用：接口请求次数与累计 token 用量。
- 运行环境：工作目录、接口地址、配置文件和超时设置。
- 可用工具：当前注册的全部工具名称。

## 配置

程序会依次查找：

1. `--config` 指定的配置文件
2. 环境变量 `WAGENT_CONFIG`
3. `wAgent/config.ini`
4. `wAgent/congfig.ini`
5. `Agent/Practice02/config.ini`
6. 当前工作目录下的 `config.ini`

配置项包括 `base_url`、`api_key`、`model`、`max_tool_rounds` 和 `request_timeout`。

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
