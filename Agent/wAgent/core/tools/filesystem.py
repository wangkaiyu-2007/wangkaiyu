from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import shutil
import time
from typing import Any

from ..config import ToolConfig
from .base import Tool

MAX_TEXT_BYTES = 1024 * 1024
TEXT_SAMPLE_BYTES = 4096


def resolve_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("路径不能为空")
    return os.path.abspath(os.path.expanduser(path.strip()))


def ensure_not_drive_root(path: str) -> str:
    resolved = os.path.abspath(path)
    _, tail = os.path.splitdrive(resolved)
    if tail in ("", os.sep, "/"):
        raise ValueError(f"出于安全考虑，不允许操作磁盘根目录：{resolved}")
    return resolved


def detect_encoding(raw: bytes, sample_bytes: int = TEXT_SAMPLE_BYTES) -> str | None:
    if b"\x00" in raw[:sample_bytes]:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gbk")
        return "gbk"
    except UnicodeDecodeError:
        return None


def format_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


class FileSystemTools:
    MAX_TEXT_BYTES = MAX_TEXT_BYTES
    TEXT_SAMPLE_BYTES = TEXT_SAMPLE_BYTES

    def __init__(self, config: ToolConfig | None = None) -> None:
        config = config or ToolConfig()
        self._max_text_bytes = config.fs_max_text_bytes
        self._text_sample_bytes = config.fs_text_sample_bytes

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="getCurrentDirectory",
                description="获取当前工作目录的绝对路径。",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=self.get_current_directory,
            ),
            Tool(
                name="listDirectory",
                description="列出指定目录下的所有文件和子目录，包含类型、大小和修改时间。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要列出的目录路径，默认当前工作目录",
                        }
                    },
                    "required": [],
                },
                handler=self.list_directory,
            ),
            Tool(
                name="getFileType",
                description="获取指定文件的文件类型，包括扩展名、MIME 类型以及是文本文件还是二进制文件。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要检测的文件路径"}
                    },
                    "required": ["path"],
                },
                handler=self.get_file_type,
            ),
            Tool(
                name="readTextFile",
                description="通过 Python 代码读取指定文件的文本内容，仅支持纯文本格式文件。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要读取的文件路径"}
                    },
                    "required": ["path"],
                },
                handler=self.read_text_file,
            ),
            Tool(
                name="createFile",
                description="在指定目录下按文件名创建新的文件，目录不存在时会自动逐级创建目录。",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "文件所在目录，例如 D:/zuoye/demo 或 ./output",
                        },
                        "filename": {"type": "string", "description": "文件名，例如 note.txt"},
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
                handler=self.create_file,
            ),
            Tool(
                name="editFile",
                description="通过 Python 代码编辑指定纯文本文件的内容，支持整体覆盖、追加和局部替换三种模式。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要编辑的文件路径"},
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
                handler=self.edit_file,
            ),
            Tool(
                name="createDirectory",
                description="创建新目录，支持逐级创建，目录已存在时不会报错。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要创建的目录路径"}
                    },
                    "required": ["path"],
                },
                handler=self.create_directory,
            ),
            Tool(
                name="deleteDirectory",
                description="删除指定目录，支持删除非空目录（递归删除）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要删除的目录路径"}
                    },
                    "required": ["path"],
                },
                handler=self.delete_directory,
            ),
            Tool(
                name="deleteFile",
                description="删除指定文件。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要删除的文件路径"}
                    },
                    "required": ["path"],
                },
                handler=self.delete_file,
            ),
            Tool(
                name="renamePath",
                description="重命名文件或目录，也可以通过传入目标路径实现移动。",
                parameters={
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
                handler=self.rename_path,
            ),
        )

    def read_text_with_python(self, path: str, max_bytes: int | None = None) -> tuple[str, str]:
        limit = max_bytes or self._max_text_bytes
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在：{file_path}")
        if not file_path.is_file():
            raise IsADirectoryError(f"不是文件：{file_path}")
        size = file_path.stat().st_size
        if size > limit:
            raise ValueError(f"文件过大（{size} 字节），超过 {limit} 字节限制")
        raw = file_path.read_bytes()
        encoding = detect_encoding(raw)
        if encoding is None:
            raise ValueError("不是纯文本文件，无法读取")
        return raw.decode(encoding), encoding

    def write_text_with_python(
        self, path: str, content: str, mode: str = "w", encoding: str = "utf-8"
    ) -> int:
        with Path(path).open(mode, encoding=encoding, newline="") as handle:
            return handle.write(content or "")

    def get_current_directory(self) -> str:
        return f"当前工作目录：{os.getcwd()}"

    def list_directory(self, path: str = ".") -> str:
        target = resolve_path(path or ".")
        if not os.path.exists(target):
            raise FileNotFoundError(f"目录不存在：{target}")
        if not os.path.isdir(target):
            raise NotADirectoryError(f"不是目录：{target}")

        entries: list[tuple[int, str]] = []
        with os.scandir(target) as iterator:
            for entry in iterator:
                try:
                    stat = entry.stat()
                    modified = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                    )
                    if entry.is_dir():
                        entries.append((0, f"[目录] {entry.name}  修改时间：{modified}"))
                    else:
                        entries.append(
                            (
                                1,
                                f"[文件] {entry.name}  大小：{format_size(stat.st_size)}"
                                f"  修改时间：{modified}",
                            )
                        )
                except OSError as exc:
                    entries.append((2, f"[未知] {entry.name}  读取失败：{exc}"))

        entries.sort(key=lambda item: (item[0], item[1]))
        lines = [f"目录：{target}", f"共 {len(entries)} 项"]
        lines.extend(item[1] for item in entries)
        return "\n".join(lines)

    def get_file_type(self, path: str) -> str:
        target = resolve_path(path)
        if not os.path.exists(target):
            raise FileNotFoundError(f"文件不存在：{target}")
        if not os.path.isfile(target):
            raise IsADirectoryError(f"不是文件：{target}")

        suffix = os.path.splitext(target)[1].lower() or "（无扩展名）"
        mime_type, _ = mimetypes.guess_type(target)
        with open(target, "rb") as handle:
            sample = handle.read(self._text_sample_bytes)
        kind = "文本文件" if detect_encoding(sample) is not None else "二进制文件"

        return (
            f"文件：{target}\n"
            f"扩展名：{suffix}\n"
            f"MIME 类型：{mime_type or '未知'}\n"
            f"内容类型：{kind}\n"
            f"大小：{format_size(os.path.getsize(target))}"
        )

    def read_text_file(self, path: str) -> str:
        target = resolve_path(path)
        content, encoding = self.read_text_with_python(target)
        return (
            f"文件：{target}\n编码：{encoding}\n"
            f"--- 内容开始 ---\n{content}\n--- 内容结束 ---"
        )

    def create_file(
        self, directory: str, filename: str, content: str = "", overwrite: bool = False
    ) -> str:
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

        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(content or "")

        return f"已创建文件：{target}\n写入字符数：{len(content or '')}"

    def edit_file(
        self, path: str, content: str, mode: str = "overwrite", old_text: str = ""
    ) -> str:
        target = resolve_path(path)
        _, encoding = self.read_text_with_python(target)
        mode = (mode or "overwrite").lower()

        if mode == "overwrite":
            written = self.write_text_with_python(target, content, mode="w", encoding=encoding)
            return f"已覆盖文件：{target}\n写入字符数：{written}"

        if mode == "append":
            written = self.write_text_with_python(target, content, mode="a", encoding=encoding)
            return f"已追加内容到：{target}\n追加字符数：{written}"

        if mode == "replace":
            if not old_text:
                raise ValueError("replace 模式必须提供 old_text")
            original, _ = self.read_text_with_python(target)
            count = original.count(old_text)
            if count == 0:
                raise ValueError("文件中没有找到 old_text，未做任何修改")
            updated = original.replace(old_text, content or "")
            self.write_text_with_python(target, updated, mode="w", encoding=encoding)
            return f"已替换文件：{target}\n替换次数：{count}"

        raise ValueError(f"不支持的编辑模式：{mode}")

    def create_directory(self, path: str) -> str:
        target = ensure_not_drive_root(resolve_path(path))
        existed = os.path.isdir(target)
        os.makedirs(target, exist_ok=True)
        return f"目录{'已存在' if existed else '已创建'}：{target}"

    def delete_directory(self, path: str) -> str:
        target = ensure_not_drive_root(resolve_path(path))
        if not os.path.exists(target):
            raise FileNotFoundError(f"目录不存在：{target}")
        if not os.path.isdir(target):
            raise NotADirectoryError(f"不是目录：{target}")
        shutil.rmtree(target)
        return f"已删除目录（含全部内容）：{target}"

    def delete_file(self, path: str) -> str:
        target = resolve_path(path)
        if not os.path.exists(target):
            raise FileNotFoundError(f"文件不存在：{target}")
        if os.path.isdir(target):
            raise IsADirectoryError(f"目标是目录，请使用 deleteDirectory：{target}")
        os.remove(target)
        return f"已删除文件：{target}"

    def rename_path(self, source: str, new_name: str) -> str:
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
