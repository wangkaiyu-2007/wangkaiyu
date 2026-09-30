import configparser
import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

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

prompt = input("请输入你的问题：")

print("---")

response = requests.post(
    f"{base_url.rstrip('/')}/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    },
    stream=True,
    timeout=60,
)

for line in response.iter_lines():
    if not line:
        continue
    line = line.decode("utf-8")
    if not line.startswith("data:"):
        continue
    data = line[len("data:"):].strip()
    if data == "[DONE]":
        break
    delta = json.loads(data)["choices"][0]["delta"]
    if delta.get("content"):
        print(delta["content"], end="", flush=True)

print()
