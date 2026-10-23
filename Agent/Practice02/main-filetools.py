import configparser
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

SYSTEM_PROMPT = (
    "你是一个具备完整上下文记忆、并支持本地文件操作工具调用的对话助手，严格遵守以下规则：\n"
    "1. 基于全部历史上下文理解用户当前输入，禁止脱离对话语境单独作答；\n"
    "2. 用户在历史中已经提供过的信息，不得重复询问；\n"
    "3. 当用户使用指代性表述时，准确对应历史内容，保持话题连贯；\n"
    "4. 涉及本地文件或目录的操作，必须调用对应的工具完成，禁止自行编造结果；\n"
    "5. 读取或编辑文件内容时，只支持纯文本格式文件；遇到二进制文件应如实告知用户；\n"
    "6. 删除目录、删除文件、重命名属于破坏性操作，执行前先确认用户意图明确；\n"
    "7. 用户给出的相对路径，一律相对于当前工作目录解析；\n"
    "8. 拿到工具返回结果后，用自然流畅的语言向用户转述；\n"
    "9. 回复保持简洁，除非用户要求更多细节。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getCurrentDirectory",
            "description": "获取当前工作目录的绝对路径。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDirectory",
            "description": "列出指定目录下的所有文件和子目录，包含类型、大小和修改时间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列出的目录路径，默认当前工作目录",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的文件类型，包括扩展名、MIME 类型以及是文本文件还是二进制文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要检测的文件路径",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readTextFile",
            "description": "通过 Python 代码读取指定文件的文本内容，仅支持纯文本格式文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的文件路径",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "在指定目录下按文件名创建新的文件，目录不存在时会自动逐级创建目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "文件所在目录，例如 D:/zuoye/demo 或 ./output",
                    },
                    "filename": {
                        "type": "string",
                        "description": "文件名，例如 note.txt",
                    },
                    "content": {
                        "type": "string",
                        "description": "初始文本内容，默认空字符串",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "文件已存在时是否覆盖，默认 false",
                    },
                },
                "required": ["directory", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": "通过 Python 代码编辑指定纯文本文件的内容，支持整体覆盖、追加和局部替换三种模式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要编辑的文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的文本；替换模式下为替换后的新文本",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append", "replace"],
                        "description": "overwrite 覆盖全部内容，append 追加到末尾，replace 替换 old_text",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "替换模式下要被替换的原文内容",
                    },
                },
                "required": ["path", "content", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDirectory",
            "description": "创建新目录，支持逐级创建，目录已存在时不会报错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要创建的目录路径",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDirectory",
            "description": "删除指定目录，支持删除非空目录（递归删除）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的目录路径",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除指定文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件路径",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renamePath",
            "description": "重命名文件或目录，也可以通过传入目标路径实现移动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "待重命名的文件或目录路径",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "新的名称或目标路径；只写名称时在同级目录重命名",
                    },
                },
                "required": ["source", "new_name"],
            },
        },
    },
]

MAX_TEXT_BYTES = 1024 * 1024
TEXT_SAMPLE_BYTES = 4096


def resolve_path(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("路径不能为空")
    return os.path.abspath(os.path.expanduser(path.strip()))


def ensure_not_drive_root(path):
    resolved = os.path.abspath(path)
    drive, tail = os.path.splitdrive(resolved)
    if tail in ("", os.sep, "/"):
        raise ValueError(f"出于安全考虑，不允许操作磁盘根目录：{resolved}")
    return resolved


def detect_encoding(raw):
    if b"\x00" in raw[:TEXT_SAMPLE_BYTES]:
        return None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return None


def read_text_with_python(path, max_bytes=MAX_TEXT_BYTES):
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")
    if not file_path.is_file():
        raise IsADirectoryError(f"不是文件：{file_path}")
    size = file_path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"文件过大（{size} 字节），超过 {max_bytes} 字节限制")
    raw = file_path.read_bytes()
    encoding = detect_encoding(raw)
    if encoding is None:
        raise ValueError("不是纯文本文件，无法读取")
    return raw.decode(encoding), encoding


def write_text_with_python(path, content, mode="w", encoding="utf-8"):
    file_path = Path(path)
    with file_path.open(mode, encoding=encoding, newline="") as fh:
        return fh.write(content or "")


def format_size(size):
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def get_current_directory():
    return f"当前工作目录：{os.getcwd()}"


def list_directory(path="."):
    target = resolve_path(path or ".")
    if not os.path.exists(target):
        raise FileNotFoundError(f"目录不存在：{target}")
    if not os.path.isdir(target):
        raise NotADirectoryError(f"不是目录：{target}")

    entries = []
    with os.scandir(target) as it:
        for entry in it:
            try:
                stat = entry.stat()
                modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                if entry.is_dir():
                    entries.append((0, f"[目录] {entry.name}  修改时间：{modified}"))
                else:
                    entries.append(
                        (1, f"[文件] {entry.name}  大小：{format_size(stat.st_size)}  修改时间：{modified}")
                    )
            except OSError as exc:
                entries.append((2, f"[未知] {entry.name}  读取失败：{exc}"))

    entries.sort(key=lambda item: (item[0], item[1]))
    lines = [f"目录：{target}", f"共 {len(entries)} 项"]
    lines.extend(item[1] for item in entries)
    return "\n".join(lines)


def get_file_type(path):
    target = resolve_path(path)
    if not os.path.exists(target):
        raise FileNotFoundError(f"文件不存在：{target}")
    if not os.path.isfile(target):
        raise IsADirectoryError(f"不是文件：{target}")

    suffix = os.path.splitext(target)[1].lower() or "（无扩展名）"
    mime_type, _ = mimetypes.guess_type(target)
    with open(target, "rb") as fh:
        sample = fh.read(TEXT_SAMPLE_BYTES)
    kind = "文本文件" if detect_encoding(sample) is not None else "二进制文件"

    return (
        f"文件：{target}\n"
        f"扩展名：{suffix}\n"
        f"MIME 类型：{mime_type or '未知'}\n"
        f"内容类型：{kind}\n"
        f"大小：{format_size(os.path.getsize(target))}"
    )


def read_text_file(path):
    target = resolve_path(path)
    content, encoding = read_text_with_python(target)
    return f"文件：{target}\n编码：{encoding}\n--- 内容开始 ---\n{content}\n--- 内容结束 ---"


def create_file(directory, filename, content="", overwrite=False):
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("文件名不能为空")
    filename = filename.strip()
    if os.path.isabs(filename):
        raise ValueError("filename 只能是文件名或相对子路径，不能是绝对路径")

    base = resolve_path(directory or ".")
    if not os.path.isdir(base):
        os.makedirs(base, exist_ok=True)

    target = os.path.abspath(os.path.join(base, filename))
    if os.path.isdir(target):
        raise IsADirectoryError(f"目标已存在且是目录：{target}")
    if os.path.exists(target) and not overwrite:
        raise FileExistsError(f"文件已存在：{target}（如需覆盖请设置 overwrite=true）")

    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(content or "")

    return f"已创建文件：{target}\n写入字符数：{len(content or '')}"


def edit_file(path, content, mode="overwrite", old_text=""):
    target = resolve_path(path)
    _, encoding = read_text_with_python(target)
    mode = (mode or "overwrite").lower()

    if mode == "overwrite":
        written = write_text_with_python(target, content, mode="w", encoding=encoding)
        return f"已覆盖文件：{target}\n写入字符数：{written}"

    if mode == "append":
        written = write_text_with_python(target, content, mode="a", encoding=encoding)
        return f"已追加内容到：{target}\n追加字符数：{written}"

    if mode == "replace":
        if not old_text:
            raise ValueError("replace 模式必须提供 old_text")
        original, _ = read_text_with_python(target)
        count = original.count(old_text)
        if count == 0:
            raise ValueError("文件中没有找到 old_text，未做任何修改")
        updated = original.replace(old_text, content or "")
        write_text_with_python(target, updated, mode="w", encoding=encoding)
        return f"已替换文件：{target}\n替换次数：{count}"

    raise ValueError(f"不支持的编辑模式：{mode}")


def create_directory(path):
    target = ensure_not_drive_root(resolve_path(path))
    existed = os.path.isdir(target)
    os.makedirs(target, exist_ok=True)
    return f"目录{'已存在' if existed else '已创建'}：{target}"


def delete_directory(path):
    target = ensure_not_drive_root(resolve_path(path))
    if not os.path.exists(target):
        raise FileNotFoundError(f"目录不存在：{target}")
    if not os.path.isdir(target):
        raise NotADirectoryError(f"不是目录：{target}")
    shutil.rmtree(target)
    return f"已删除目录（含全部内容）：{target}"


def delete_file(path):
    target = resolve_path(path)
    if not os.path.exists(target):
        raise FileNotFoundError(f"文件不存在：{target}")
    if os.path.isdir(target):
        raise IsADirectoryError(f"目标是目录，请使用 deleteDirectory：{target}")
    os.remove(target)
    return f"已删除文件：{target}"


def rename_path(source, new_name):
    src = ensure_not_drive_root(resolve_path(source))
    if not os.path.exists(src):
        raise FileNotFoundError(f"文件或目录不存在：{src}")
    if not isinstance(new_name, str) or not new_name.strip():
        raise ValueError("new_name 不能为空")

    new_name = new_name.strip()
    if os.path.isabs(new_name):
        dst = os.path.abspath(new_name)
    elif os.sep in new_name or (os.altsep and os.altsep in new_name):
        dst = os.path.abspath(os.path.join(os.getcwd(), new_name))
    else:
        dst = os.path.join(os.path.dirname(src), new_name)
    dst = ensure_not_drive_root(dst)

    if os.path.abspath(dst) == os.path.abspath(src):
        raise ValueError("新名称与原名相同")
    if os.path.exists(dst):
        raise FileExistsError(f"目标已存在：{dst}")

    parent = os.path.dirname(dst)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    os.rename(src, dst)
    kind = "目录" if os.path.isdir(dst) else "文件"
    return f"已将{kind}重命名：{src} -> {dst}"


def execute_tool(name, arguments_json):
    try:
        arguments = json.loads(arguments_json) if arguments_json else {}
    except ValueError:
        return "工具参数不是合法的 JSON"
    if not isinstance(arguments, dict):
        return "工具参数必须是 JSON 对象"

    try:
        if name == "getCurrentDirectory":
            return get_current_directory()
        if name == "listDirectory":
            return list_directory(arguments.get("path", "."))
        if name == "getFileType":
            return get_file_type(arguments.get("path", ""))
        if name == "readTextFile":
            return read_text_file(arguments.get("path", ""))
        if name == "createFile":
            if "directory" not in arguments:
                return "缺少参数：directory"
            if "filename" not in arguments:
                return "缺少参数：filename"
            return create_file(
                arguments["directory"],
                arguments["filename"],
                arguments.get("content", ""),
                bool(arguments.get("overwrite", False)),
            )
        if name == "editFile":
            if "path" not in arguments:
                return "缺少参数：path"
            if "content" not in arguments:
                return "缺少参数：content"
            return edit_file(
                arguments["path"],
                arguments["content"],
                arguments.get("mode", "overwrite"),
                arguments.get("old_text", ""),
            )
        if name == "createDirectory":
            return create_directory(arguments.get("path", ""))
        if name == "deleteDirectory":
            return delete_directory(arguments.get("path", ""))
        if name == "deleteFile":
            return delete_file(arguments.get("path", ""))
        if name == "renamePath":
            if "source" not in arguments:
                return "缺少参数：source"
            if "new_name" not in arguments:
                return "缺少参数：new_name"
            return rename_path(arguments["source"], arguments["new_name"])
    except (OSError, ValueError) as exc:
        return f"操作失败：{exc}"

    return f"未知工具：{name}"


config = configparser.ConfigParser()
if not config.read(CONFIG_PATH, encoding="utf-8"):
    print(f"读取配置失败：找不到配置文件 {CONFIG_PATH}")
    sys.exit(1)

try:
    base_url = config["openai"]["base_url"].strip()
    api_key = config["openai"]["api_key"].strip()
    model = config["openai"]["model"].strip()
except KeyError as exc:
    print(f"读取配置失败：config.ini 缺少字段 {exc}")
    sys.exit(1)

if not base_url or not api_key or not model:
    print("读取配置失败：base_url、api_key、model 不能为空，请在 config.ini 中填写")
    sys.exit(1)

if api_key == "your-api-key":
    print("读取配置失败：请把 config.ini 里的 api_key 占位符替换成你真实的 API Key")
    sys.exit(1)

chat_url = f"{base_url.rstrip('/')}/chat/completions"
history = [{"role": "system", "content": SYSTEM_PROMPT}]


def stream_chat(messages):
    response = requests.post(
        chat_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "stream": True,
        },
        stream=True,
        timeout=60,
    )
    if response.status_code >= 400:
        raise requests.HTTPError(
            f"HTTP {response.status_code}: {response.text[:1000]}",
            response=response,
        )

    parts = []
    tool_calls = []

    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            delta = json.loads(data)["choices"][0]["delta"]
        except (ValueError, KeyError, IndexError):
            continue

        content = delta.get("content")
        if content:
            parts.append(content)
            print(content, end="", flush=True)

        for tc in delta.get("tool_calls") or []:
            index = tc.get("index", 0)
            while len(tool_calls) <= index:
                tool_calls.append(
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
            current = tool_calls[index]
            if tc.get("id"):
                current["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                current["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                current["function"]["arguments"] += fn["arguments"]

    print()
    return "".join(parts), tool_calls


print("已进入多轮对话（支持本地文件操作工具调用）。输入 /clear 清空上下文，/exit 退出。")

try:
    while True:
        prompt = input("请输入你的问题：").strip()

        if not prompt:
            continue

        if prompt in ("/exit", "/quit", "exit", "quit"):
            print("已退出")
            break

        if prompt in ("/clear", "clear"):
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("上下文已清空")
            continue

        print("---")

        history.append({"role": "user", "content": prompt})

        try:
            for _ in range(10):
                reply, tool_calls = stream_chat(history)

                if not tool_calls:
                    if reply:
                        history.append({"role": "assistant", "content": reply})
                    break

                history.append(
                    {
                        "role": "assistant",
                        "content": reply if reply else None,
                        "tool_calls": tool_calls,
                    }
                )

                for tc in tool_calls:
                    name = tc["function"]["name"]
                    result = execute_tool(name, tc["function"]["arguments"])
                    print(f"[工具调用 {name} 返回]")
                    print(result)
                    print("---")
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )
        except requests.RequestException as exc:
            history.pop()
            print(f"请求失败：{exc}")
            continue
except (KeyboardInterrupt, EOFError):
    print("\n已退出")
