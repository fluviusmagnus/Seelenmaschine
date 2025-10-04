# MCP (Model Context Protocol) 使用指南

本项目现已支持 MCP 协议，可以通过配置文件连接到任意 MCP 服务器，动态获取和使用工具。

## 什么是 MCP？

MCP (Model Context Protocol) 是一个标准化协议，用于让 LLM 应用连接到外部工具和数据源。通过 MCP，您可以：

- 将工具实现与主应用解耦
- 使用任何语言编写工具服务器
- 在多个项目间共享工具
- 动态添加/删除工具而无需修改代码

## 快速开始

### 1. 启用 MCP

在 `.env` 文件中启用 MCP：

```bash
ENABLE_MCP=true
MCP_CONFIG_PATH=mcp_servers.json
```

### 2. 配置 MCP 服务器

编辑 `mcp_servers.json` 文件，添加您的 MCP 服务器配置：

```json
{
    "mcpServers": {
        "my-tools": {
            "command": "node",
            "args": ["/path/to/your/mcp-server/build/index.js"],
            "env": {
                "API_KEY": "${YOUR_API_KEY}"
            },
            "disabled": false
        }
    }
}
```

### 3. 配置说明

#### Stdio 传输方式（本地服务器）

- **command**: 启动服务器的命令（如 `node`, `python`, `uvx` 等）
- **args**: 命令参数数组
- **env**: 环境变量，支持 `${VAR_NAME}` 占位符，会从系统环境变量中替换
- **disabled**: 设为 `true` 可禁用该服务器

#### HTTP/SSE 传输方式（远程服务器）

- **type**: 传输类型，如 `"STREAMABLE_HTTP"` 或 `"SSE"`
- **url**: 服务器 URL
- **bearerToken**: Bearer Token 认证（会自动转换为 `Authorization: Bearer <token>` header）
- **headers**: 额外的 HTTP headers（可选）
- **disabled**: 设为 `true` 可禁用该服务器

## 工作原理

1. **启动时**: 项目会读取 `mcp_servers.json` 配置
2. **获取工具**: 连接到配置的 MCP 服务器，获取可用工具列表
3. **调用工具**: 当 LLM 需要使用工具时，通过 MCP 协议发送请求到相应服务器
4. **返回结果**: MCP 服务器执行工具并返回结果给 LLM
5. **多轮调用**: LLM 可以基于工具结果决定是否继续调用其他工具，支持链式工具调用

### 多轮工具调用示例

系统完全支持多轮工具调用。例如：

1. **第一轮**: LLM 调用 `search_web` 搜索信息
2. **第二轮**: 基于搜索结果，LLM 可能调用其他工具进一步处理
3. **第三轮**: 继续调用工具，直到 LLM 认为有足够信息回答问题

这个过程是自动的，在 `while True` 循环中实现：
- 每次工具调用后，结果被添加到对话历史
- LLM 可以看到所有之前的工具调用和结果
- 当 LLM 不再需要调用工具时，循环结束并返回最终答案

## 与现有工具的关系

- 如果 `ENABLE_MCP=true`，系统会优先使用 MCP 工具
- 如果 MCP 工具调用失败，会回退到本地工具（如 `search_web`）
- 可以同时使用 MCP 和本地工具

## 创建自己的 MCP 服务器

### 使用 FastMCP (Python)

```python
from fastmcp import FastMCP

mcp = FastMCP("我的工具服务器")

@mcp.tool()
def my_tool(arg: str) -> str:
    """工具描述"""
    return f"处理: {arg}"

if __name__ == "__main__":
    mcp.run()
```

### 使用官方 MCP SDK (TypeScript)

参考 [MCP 官方文档](https://modelcontextprotocol.io) 创建 TypeScript 服务器。

## 示例配置

### 本地 Python 服务器

```json
{
    "mcpServers": {
        "local-tools": {
            "command": "python",
            "args": ["./my_mcp_server.py"]
        }
    }
}
```

### 使用 uvx 运行的服务器

```json
{
    "mcpServers": {
        "github": {
            "command": "uvx",
            "args": ["mcp-server-github"],
            "env": {
                "GITHUB_TOKEN": "${GITHUB_TOKEN}"
            }
        }
    }
}
```

### Node.js TypeScript 服务器

```json
{
    "mcpServers": {
        "weather": {
            "command": "node",
            "args": ["C:/path/to/weather-server/build/index.js"],
            "env": {
                "WEATHER_API_KEY": "${WEATHER_API_KEY}"
            }
        }
    }
}
```

### 远程 HTTP 服务器（带认证）

```json
{
    "mcpServers": {
        "remote-api": {
            "type": "STREAMABLE_HTTP",
            "url": "https://api.example.com/mcp",
            "bearerToken": "your-bearer-token-here",
            "description": "远程 MCP 服务器"
        }
    }
}
```

### 使用自定义 Headers

```json
{
    "mcpServers": {
        "custom-server": {
            "type": "SSE",
            "url": "https://api.example.com/sse",
            "headers": {
                "X-Custom-Header": "value",
                "X-API-Version": "v2"
            }
        }
    }
}
```

## 故障排除

### 工具未显示

1. 检查 `.env` 中 `ENABLE_MCP=true`
2. 检查 `mcp_servers.json` 路径正确
3. 查看日志确认服务器是否启动成功

### 工具调用失败

1. 检查环境变量是否正确设置
2. 确认服务器命令和参数正确
3. 查看日志中的错误信息

### 连接问题

- 确保 MCP 服务器可执行文件存在
- 检查 Node.js/Python 等运行时已安装
- 验证服务器路径使用绝对路径

## 日志

启用调试模式查看 MCP 相关日志：

```bash
DEBUG_MODE=true
```

日志会显示：
- MCP 服务器连接状态
- 获取到的工具列表
- 工具调用和返回结果

## 推荐的 MCP 服务器

- **mcp-server-github**: GitHub 集成
- **mcp-server-filesystem**: 文件系统操作
- **mcp-server-sqlite**: SQLite 数据库
- **mcp-server-fetch**: HTTP 请求

更多服务器参考: https://github.com/modelcontextprotocol/servers

## 参考资源

- [MCP 官方文档](https://modelcontextprotocol.io)
- [FastMCP 文档](https://gofastmcp.com)
- [MCP 服务器列表](https://github.com/modelcontextprotocol/servers)
