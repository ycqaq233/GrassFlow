"""
GrassFlow 工具系统使用示例

演示如何使用内置工具
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import (
    ToolContext,
    ToolRegistry,
    register_builtin_tools,
    ShellTool,
    ReadTool,
    WriteTool,
    GlobTool,
    GrepTool,
)


async def demo_shell_tool(registry: ToolRegistry, ctx: ToolContext):
    """演示 Shell 工具"""
    print("\n=== Shell 工具演示 ===")

    # 执行简单命令
    result = await registry.execute(
        "shell",
        {"command": "echo Hello from GrassFlow!"},
        ctx
    )
    print(f"命令输出: {result.output}")

    # 查看当前目录
    result = await registry.execute(
        "shell",
        {"command": "Get-Location" if sys.platform == "win32" else "pwd"},
        ctx
    )
    print(f"当前目录: {result.output}")


async def demo_read_tool(registry: ToolRegistry, ctx: ToolContext):
    """演示 Read 工具"""
    print("\n=== Read 工具演示 ===")

    # 读取当前目录
    result = await registry.execute(
        "read",
        {"filePath": ctx.cwd},
        ctx
    )
    print(f"目录内容:\n{result.output[:500]}...")


async def demo_write_tool(registry: ToolRegistry, ctx: ToolContext):
    """演示 Write 工具"""
    print("\n=== Write 工具演示 ===")

    # 写入测试文件
    test_file = str(Path(ctx.cwd) / "test_output.txt")
    result = await registry.execute(
        "write",
        {
            "filePath": test_file,
            "content": "This is a test file created by GrassFlow tools.\nLine 2\nLine 3"
        },
        ctx
    )
    print(f"写入结果: {result.output}")

    # 读取刚写入的文件
    result = await registry.execute(
        "read",
        {"filePath": test_file},
        ctx
    )
    print(f"\n文件内容:\n{result.output}")


async def demo_glob_tool(registry: ToolRegistry, ctx: ToolContext):
    """演示 Glob 工具"""
    print("\n=== Glob 工具演示 ===")

    # 查找所有 Python 文件
    result = await registry.execute(
        "glob",
        {"pattern": "**/*.py"},
        ctx
    )
    print(f"Python 文件:\n{result.output[:500]}...")


async def demo_grep_tool(registry: ToolRegistry, ctx: ToolContext):
    """演示 Grep 工具"""
    print("\n=== Grep 工具演示 ===")

    # 搜索包含 "class" 的行
    result = await registry.execute(
        "grep",
        {"pattern": "class.*Tool", "include": "*.py"},
        ctx
    )
    print(f"搜索结果:\n{result.output[:500]}...")


async def demo_tool_schema(registry: ToolRegistry):
    """演示工具 Schema 导出"""
    print("\n=== 工具 Schema 列表 ===")

    schema_list = registry.to_schema_list()
    for tool in schema_list:
        print(f"\n工具: {tool['id']}")
        print(f"描述: {tool['description'][:100]}...")
        print(f"参数: {list(tool['parameters'].get('properties', {}).keys())}")


async def main():
    """主演示函数"""
    print("GrassFlow 工具系统演示")
    print("=" * 50)

    # 注册所有内置工具
    registry = register_builtin_tools()

    # 创建工具上下文
    ctx = ToolContext(
        cwd=str(Path.cwd()),
        session_id="demo-session",
        agent="demo-agent"
    )

    # 演示工具 Schema
    await demo_tool_schema(registry)

    # 演示各个工具
    await demo_shell_tool(registry, ctx)
    await demo_read_tool(registry, ctx)
    await demo_write_tool(registry, ctx)
    await demo_glob_tool(registry, ctx)
    await demo_grep_tool(registry, ctx)

    print("\n" + "=" * 50)
    print("演示完成!")


if __name__ == "__main__":
    asyncio.run(main())
