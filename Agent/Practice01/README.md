# Python 简易大模型调用（流式输出教学）

一个极简的教学案例：用 `requests` 调用 OpenAI 兼容接口，**逐段实时打印**大模型的返回内容。

只做一件事——把提示词发给大模型，然后把回答像打字机一样打印出来。适合刚接触大模型 API、想理解流式（SSE）返回长什么样的同学。

## 运行效果

```text
请输入你的问题：---
我是 DeepSeek，一个由深度求索公司打造的 AI 助手，随时准备用热情和智慧为你解答问题、提供帮助！
```

回答是一段一段蹦出来的，不是等全部生成完才一次性显示。

## 文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主程序，全部逻辑都在这一个文件里 |
| `config.example.ini` | 配置模板，把 `api_key` 换成你自己的 |
| `config.ini` | 你的真实配置（已被 `.gitignore` 忽略，不要提交） |

## 快速开始

### 1. 安装依赖

```bash
pip install requests
```

### 2. 配置

复制一份配置文件：

```bash
copy config.example.ini config.ini
```

然后编辑 `config.ini`，填入自己的 `base_url`、`api_key`、`model`：

```ini
[openai]
base_url = https://api.deepseek.com/v1
api_key = your-api-key
model = deepseek-chat
```

三个参数全部从配置文件读取，代码里不硬编码任何密钥。读取失败（文件不存在、缺字段、值为空、还是占位符）时程序会打印提示并退出。

### 3. 运行

```bash
python main.py
```

## 流式输出是怎么实现的

三个关键点，缺一个就退化成一次性输出：

```python
# 1. 请求体里告诉服务端要流式返回
json={"model": model, "messages": [...], "stream": True},

# 2. requests 侧也必须开启流式，否则会先把整个响应体下载完
stream=True,

# 3. 逐行读取 SSE，每收到一段就立刻打印并刷屏
for line in response.iter_lines():
    ...
    print(delta["content"], end="", flush=True)
```

服务端返回的是一串 SSE 行，长这样：

```text
data: {"choices":[{"delta":{"content":"我"}}]}
data: {"choices":[{"delta":{"content":"是"}}]}
data: [DONE]
```

- `delta.content` 是这一小段增量文本（不是完整回答），所以要用 `end=""` 接着打印，末尾不能换行。
- `flush=True` 强制立刻输出到终端，否则可能被缓冲区攒着，看起来还是一次性出现。
- 收到 `data: [DONE]` 表示结束。首包可能只有 `delta.role` 没有 `content`，所以要用 `.get("content")` 取值。

## 常见问题

| 现象 | 原因与处理 |
|------|-----------|
| `UnicodeEncodeError: 'gbk' codec ...` | Windows 控制台默认 GBK，代码里已用 `sys.stdout.reconfigure(encoding="utf-8")` 处理；若仍报错，把终端编码改成 UTF-8 |
| 401 / 鉴权失败 | `api_key` 没填对，或还在用占位符 `your-api-key` |
| 404 Not Found | `base_url` 少了或多了路径（一般以 `/v1` 结尾），或 `model` 名不支持 |
| 连接超时 | 网络不通或需要代理。国内直连 `api.openai.com` 通常不通，换成国内可访问的服务即可 |
| 还是一次性输出 | 少了 `stream=True`，或输出被重定向到文件（此时看不到实时效果） |

## 说明

这是一个教学示例，为了突出流式本身的原理，故意保持极简：不做多轮对话、不做重试、不写日志、不做复杂异常捕获、不用类封装。想在此基础上扩展，建议先把这三点吃透：**`stream: True` → `stream=True` → `iter_lines()` 逐段消费**。

> ⚠️ 别把填了真实 `api_key` 的 `config.ini` 提交到 Git。仓库里的 `config.example.ini` 只放占位符，`config.ini` 已加入 `.gitignore`。
