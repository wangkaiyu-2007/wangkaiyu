# AnythingLLM MCP Server

通过 MCP 协议将本地 AnythingLLM 工作区暴露给 LLM 客户端（如 Claude Desktop）。

## 快速开始

### 1. 安装依赖

```bash
cd anythingllm-mcp-server
pip install -e .
```

### 2. 配置

复制 `.env.example` 为 `.env`，填入你的 AnythingLLM 配置：

```
ANYTHINGLLM_API_KEY=your-api-key-here
ANYTHINGLLM_BASE_URL=http://localhost:3001/api
ANYTHINGLLM_WORKSPACE_SLUG=your-workspace-slug
```

`workspace-slug` 可在 AnythingLLM 界面的工作区 URL 中找到，或启动服务后通过 `list_workspaces` 工具查看。

### 3. 开发调试

```bash
uv run mcp dev server.py
```

### 4. 在 Claude Desktop 中使用

编辑 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "anythingllm": {
      "command": "python",
      "args": ["D:\\zuoye\\anythingllm-mcp-server\\server.py"]
    }
  }
}
```

## 提供的工具

| 工具 | 说明 |
|------|------|
| `ask_workspace` | 向 AnythingLLM 工作区提问，返回基于文档的回答 |
