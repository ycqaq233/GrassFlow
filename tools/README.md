# GrassFlow 内置工具系统

## 概述

GrassFlow 内置工具系统参考 opencode 的工具实现，提供了统一的工具接口和 5 个内置工具。

## 工具列表

| 工具 | ID | 描述 |
|------|-----|------|
| Shell | `shell` | 执行 shell 命令 |
| Read | `read` | 读取文件或目录 |
| Write | `write` | 写入文件 |
| Glob | `glob` | 文件模式匹配 |
| Grep | `grep` | 内容搜索 |

## 快速开始

```python
from tools import ToolContext, register_builtin_tools

# 注册所有内置工具
registry = register_builtin_tools()

# 创建工具上下文
ctx = ToolContext(cwd="/path/to/workdir")

# 执行工具
result = await registry.execute(
    "shell",
    {"command": "echo Hello, World!"},
    ctx
)
print(result.output)
```

## 工具详情

### Shell 工具

执行 shell 命令并返回输出。

```python
result = await registry.execute(
    "shell",
    {
        "command": "ls -la",
        "workdir": "/path/to/dir",  # 可选
        "timeout": 60,               # 可选，秒
        "env": {"KEY": "value"}      # 可选，环境变量
    },
    ctx
)
```

### Read 工具

读取文件内容或目录列表。

```python
# 读取文件
result = await registry.execute(
    "read",
    {
        "filePath": "/path/to/file.py",
        "offset": 1,    # 可选，起始行号
        "limit": 100     # 可选，最大行数
    },
    ctx
)

# 读取目录
result = await registry.execute(
    "read",
    {"filePath": "/path/to/dir"},
    ctx
)
```

### Write 工具

写入文件内容。

```python
result = await registry.execute(
    "write",
    {
        "filePath": "/path/to/file.txt",
        "content": "Hello, World!"
    },
    ctx
)
```

### Glob 工具

查找匹配模式的文件。

```python
# 查找所有 Python 文件
result = await registry.execute(
    "glob",
    {
        "pattern": "**/*.py",
        "path": "/path/to/search"  # 可选
    },
    ctx
)
```

### Grep 工具

在文件内容中搜索正则表达式。

```python
result = await registry.execute(
    "grep",
    {
        "pattern": "def.*function",
        "path": "/path/to/search",  # 可选
        "include": "*.py"            # 可选，文件类型过滤
    },
    ctx
)
```

## 工具 Schema 导出

导出工具 Schema 供 LLM 使用：

```python
schema_list = registry.to_schema_list()
# 返回格式:
# [
#     {
#         "id": "shell",
#         "description": "...",
#         "parameters": { "type": "object", "properties": {...} }
#     },
#     ...
# ]
```

## 自定义工具

继承 `Tool` 基类创建自定义工具：

```python
from tools import Tool, ToolContext, ToolResult

class MyTool(Tool):
    @property
    def id(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "My custom tool"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input value"}
            },
            "required": ["input"]
        }

    async def execute(self, params: dict, ctx: ToolContext) -> ToolResult:
        # 实现工具逻辑
        return ToolResult(
            output=f"Processed: {params['input']}",
            title="My Tool"
        )

# 注册自定义工具
registry.register(MyTool())
```

## 测试

运行测试：

```bash
pytest tests/test_tools.py -v
```

## 文件结构

```
tools/
├── __init__.py      # 包初始化和导出
├── tool.py          # 统一工具接口
├── shell.py         # Shell 工具
├── read.py          # Read 工具
├── write.py         # Write 工具
├── glob.py          # Glob 工具
├── grep.py          # Grep 工具
└── README.md        # 本文件
```
