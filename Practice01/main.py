import configparser
import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

SYSTEM_PROMPT = (
    "你是一个具备完整上下文记忆的对话助手，严格遵守以下规则：\n"
    "1. 基于全部历史上下文理解用户当前输入，禁止脱离对话语境单独作答；\n"
    "2. 用户在历史中已经提供过的信息，不得重复询问；\n"
    "3. 当用户使用指代性表述（如“它”“这个”“刚才说的”）时，准确对应历史内容，保持话题连贯；\n"
    "4. 回复风格自然流畅，符合日常对话逻辑；\n"
    "5. 回复保持简洁，除非用户要求更多细节。"
)

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
            "stream": True,
        },
        stream=True,
        timeout=60,
    )
    response.raise_for_status()

    parts = []
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

    print()
    return "".join(parts)


print("已进入多轮对话（完整上下文记忆）。输入 /clear 清空上下文，/exit 退出。")

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
            reply = stream_chat(history)
        except requests.RequestException as exc:
            history.pop()
            print(f"请求失败：{exc}")
            continue

        if reply:
            history.append({"role": "assistant", "content": reply})
except (KeyboardInterrupt, EOFError):
    print("\n已退出")
