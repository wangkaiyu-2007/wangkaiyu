import configparser
import json
import os
import subprocess
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

SYSTEM_PROMPT = (
    "你是一个具备完整上下文记忆、并支持工具调用的对话助手，严格遵守以下规则：\n"
    "1. 基于全部历史上下文理解用户当前输入，禁止脱离对话语境单独作答；\n"
    "2. 用户在历史中已经提供过的信息，不得重复询问；\n"
    "3. 当用户使用指代性表述时，准确对应历史内容，保持话题连贯；\n"
    "4. 当用户询问当前日期、今天几号、现在几点、当前时间等问题时，"
    "必须调用 getDate 工具获取，禁止凭记忆或自行编造；\n"
    "5. 拿到工具返回结果后，用自然流畅的语言向用户转述；\n"
    "6. 回复保持简洁，除非用户要求更多细节。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间。通过调用系统 date/time 命令实现，而不是用代码计算。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]


def decode_cmd_output(raw):
    for encoding in ("gbk", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def get_date():
    """调用系统 date / time 命令获取当前日期和时间"""
    date_proc = subprocess.run(["cmd", "/c", "date /t"], capture_output=True, timeout=10)
    time_proc = subprocess.run(["cmd", "/c", "time /t"], capture_output=True, timeout=10)

    date_str = decode_cmd_output(date_proc.stdout).strip()
    time_str = decode_cmd_output(time_proc.stdout).strip()

    return f"当前日期：{date_str}\n当前时间：{time_str}"


def execute_tool(name, arguments_json):
    if name == "getDate":
        return get_date()
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
    """流式请求大模型，返回 (文本内容, tool_calls 列表)"""
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
    response.raise_for_status()

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

        # 工具调用的增量：按 index 拼接 id、函数名、参数片段
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


print("已进入多轮对话（支持 getDate 工具调用）。输入 /clear 清空上下文，/exit 退出。")

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
            # 最多连续处理 5 轮工具调用，防止模型反复调用
            for _ in range(5):
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
