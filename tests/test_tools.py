"""
GrassFlow 工具系统测试

测试所有内置工具的功能
"""

import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from tools.tool import Tool, ToolContext, ToolResult, ToolRegistry, register_builtin_tools
from tools.shell import ShellTool
from tools.read import ReadTool
from tools.write import WriteTool
from tools.glob import GlobTool
from tools.grep import GrepTool


# ==================== Fixtures ====================

@pytest.fixture
def temp_dir():
    """创建临时目录"""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def tool_context(temp_dir):
    """创建工具上下文"""
    return ToolContext(cwd=temp_dir)


@pytest.fixture
def sample_files(temp_dir):
    """创建示例文件结构"""
    # 创建目录结构
    os.makedirs(os.path.join(temp_dir, "src", "utils"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "tests"), exist_ok=True)

    # 创建文件
    files = {
        "README.md": "# Test Project\n\nThis is a test.",
        "src/main.py": "def main():\n    print('Hello, World!')\n\nif __name__ == '__main__':\n    main()",
        "src/utils/helper.py": "def helper():\n    return 42\n\nclass Helper:\n    pass",
        "src/utils/__init__.py": "",
        "tests/test_main.py": "import pytest\n\ndef test_main():\n    assert True",
        "config.json": '{"name": "test", "version": "1.0.0"}',
        ".gitignore": "*.pyc\n__pycache__\n.venv",
    }

    for filepath, content in files.items():
        full_path = os.path.join(temp_dir, filepath)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

    return temp_dir


# ==================== ToolContext 测试 ====================

class TestToolContext:
    """测试 ToolContext"""

    def test_get_absolute_path_with_absolute(self, tool_context, temp_dir):
        """测试绝对路径转换"""
        abs_path = os.path.join(temp_dir, "test.txt")
        result = tool_context.get_absolute_path(abs_path)
        assert result == abs_path

    def test_get_absolute_path_with_relative(self, tool_context, temp_dir):
        """测试相对路径转换"""
        result = tool_context.get_absolute_path("test.txt")
        assert result == os.path.join(temp_dir, "test.txt")


# ==================== ToolResult 测试 ====================

class TestToolResult:
    """测试 ToolResult"""

    def test_to_dict(self):
        """测试转换为字典"""
        result = ToolResult(
            output="test output",
            title="test",
            metadata={"key": "value"},
            truncated=False
        )
        d = result.to_dict()
        assert d["output"] == "test output"
        assert d["title"] == "test"
        assert d["metadata"] == {"key": "value"}
        assert d["truncated"] is False

    def test_to_dict_with_attachments(self):
        """测试带附件的转换"""
        result = ToolResult(
            output="test",
            attachments=[{"type": "file", "url": "test.txt"}]
        )
        d = result.to_dict()
        assert "attachments" in d
        assert len(d["attachments"]) == 1


# ==================== ToolRegistry 测试 ====================

class TestToolRegistry:
    """测试 ToolRegistry"""

    def test_register_tool(self):
        """测试注册工具"""
        registry = ToolRegistry()
        tool = ShellTool()
        registry.register(tool)
        assert registry.get("shell") is tool

    def test_list_tools(self):
        """测试列出工具"""
        registry = ToolRegistry()
        registry.register(ShellTool())
        registry.register(ReadTool())
        tools = registry.list_tools()
        assert len(tools) == 2

    def test_list_ids(self):
        """测试列出工具 ID"""
        registry = ToolRegistry()
        registry.register(ShellTool())
        registry.register(ReadTool())
        ids = registry.list_ids()
        assert "shell" in ids
        assert "read" in ids

    def test_to_schema_list(self):
        """测试导出 Schema 列表"""
        registry = ToolRegistry()
        registry.register(ShellTool())
        schema_list = registry.to_schema_list()
        assert len(schema_list) == 1
        assert schema_list[0]["id"] == "shell"
        assert "description" in schema_list[0]
        assert "parameters" in schema_list[0]

    def test_get_nonexistent_tool(self):
        """测试获取不存在的工具"""
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None


# ==================== ShellTool 测试 ====================

class TestShellTool:
    """测试 ShellTool"""

    @pytest.mark.asyncio
    async def test_basic_command(self, tool_context):
        """测试基本命令执行"""
        tool = ShellTool()
        result = await tool.execute(
            {"command": "echo hello"},
            tool_context
        )
        assert "hello" in result.output
        assert result.metadata.get("exit_code") == 0

    @pytest.mark.asyncio
    async def test_command_with_workdir(self, tool_context, temp_dir):
        """测试指定工作目录"""
        tool = ShellTool()
        # Windows 和 Unix 使用不同的命令
        if sys.platform == "win32":
            result = await tool.execute(
                {"command": "Get-Location", "workdir": temp_dir},
                tool_context
            )
        else:
            result = await tool.execute(
                {"command": "pwd", "workdir": temp_dir},
                tool_context
            )
        assert temp_dir in result.output or temp_dir.replace('\\', '/') in result.output

    @pytest.mark.asyncio
    async def test_command_timeout(self, tool_context):
        """测试命令超时"""
        tool = ShellTool()
        # Windows 和 Unix 使用不同的命令
        if sys.platform == "win32":
            result = await tool.execute(
                {"command": "Start-Sleep -Seconds 10", "timeout": 1},
                tool_context
            )
        else:
            result = await tool.execute(
                {"command": "sleep 10", "timeout": 1},
                tool_context
            )
        assert "timed out" in result.output.lower() or result.metadata.get("timeout") is True

    @pytest.mark.asyncio
    async def test_command_error(self, tool_context):
        """测试命令错误"""
        tool = ShellTool()
        result = await tool.execute(
            {"command": "nonexistent_command_12345"},
            tool_context
        )
        # 命令失败应该有非零退出码或错误信息
        assert result.metadata.get("exit_code") != 0 or "error" in result.output.lower()

    def test_parameters_schema(self):
        """测试参数 Schema"""
        tool = ShellTool()
        params = tool.parameters
        assert "command" in params["properties"]
        assert "command" in params["required"]


# ==================== ReadTool 测试 ====================

class TestReadTool:
    """测试 ReadTool"""

    @pytest.mark.asyncio
    async def test_read_file(self, tool_context, sample_files):
        """测试读取文件"""
        tool = ReadTool()
        filepath = os.path.join(sample_files, "src", "main.py")
        result = await tool.execute(
            {"filePath": filepath},
            tool_context
        )
        assert "def main" in result.output
        assert "<content>" in result.output

    @pytest.mark.asyncio
    async def test_read_directory(self, tool_context, sample_files):
        """测试读取目录"""
        tool = ReadTool()
        result = await tool.execute(
            {"filePath": sample_files},
            tool_context
        )
        assert "<type>directory</type>" in result.output
        assert "src/" in result.output

    @pytest.mark.asyncio
    async def test_read_with_offset(self, tool_context, sample_files):
        """测试分页读取"""
        tool = ReadTool()
        filepath = os.path.join(sample_files, "src", "main.py")
        result = await tool.execute(
            {"filePath": filepath, "offset": 2, "limit": 2},
            tool_context
        )
        assert "2:" in result.output

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tool_context):
        """测试读取不存在的文件"""
        tool = ReadTool()
        result = await tool.execute(
            {"filePath": "/nonexistent/file.txt"},
            tool_context
        )
        assert "not found" in result.output.lower()

    @pytest.mark.asyncio
    async def test_read_relative_path(self, tool_context, sample_files):
        """测试相对路径读取"""
        tool = ReadTool()
        # 修改 cwd 为 sample_files
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"filePath": "README.md"},
            ctx
        )
        assert "Test Project" in result.output


# ==================== WriteTool 测试 ====================

class TestWriteTool:
    """测试 WriteTool"""

    @pytest.mark.asyncio
    async def test_write_new_file(self, tool_context, temp_dir):
        """测试写入新文件"""
        tool = WriteTool()
        filepath = os.path.join(temp_dir, "new_file.txt")
        result = await tool.execute(
            {"filePath": filepath, "content": "Hello, World!"},
            tool_context
        )
        assert "successfully" in result.output.lower()
        assert os.path.exists(filepath)
        with open(filepath, 'r') as f:
            assert f.read() == "Hello, World!"

    @pytest.mark.asyncio
    async def test_write_overwrite(self, tool_context, temp_dir):
        """测试覆盖文件"""
        tool = WriteTool()
        filepath = os.path.join(temp_dir, "overwrite.txt")

        # 第一次写入
        await tool.execute(
            {"filePath": filepath, "content": "original"},
            tool_context
        )

        # 第二次写入
        result = await tool.execute(
            {"filePath": filepath, "content": "updated"},
            tool_context
        )
        assert "successfully" in result.output.lower()
        with open(filepath, 'r') as f:
            assert f.read() == "updated"

    @pytest.mark.asyncio
    async def test_write_create_dirs(self, tool_context, temp_dir):
        """测试自动创建目录"""
        tool = WriteTool()
        filepath = os.path.join(temp_dir, "new", "dir", "file.txt")
        result = await tool.execute(
            {"filePath": filepath, "content": "nested"},
            tool_context
        )
        assert "successfully" in result.output.lower()
        assert os.path.exists(filepath)

    @pytest.mark.asyncio
    async def test_write_relative_path(self, temp_dir):
        """测试相对路径写入"""
        tool = WriteTool()
        ctx = ToolContext(cwd=temp_dir)
        result = await tool.execute(
            {"filePath": "relative.txt", "content": "test"},
            ctx
        )
        assert os.path.exists(os.path.join(temp_dir, "relative.txt"))


# ==================== GlobTool 测试 ====================

class TestGlobTool:
    """测试 GlobTool"""

    @pytest.mark.asyncio
    async def test_glob_simple_pattern(self, tool_context, sample_files):
        """测试简单模式匹配"""
        tool = GlobTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "*.md"},
            ctx
        )
        assert "README.md" in result.output

    @pytest.mark.asyncio
    async def test_glob_recursive(self, tool_context, sample_files):
        """测试递归模式匹配"""
        tool = GlobTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "**/*.py"},
            ctx
        )
        assert "main.py" in result.output
        assert "helper.py" in result.output

    @pytest.mark.asyncio
    async def test_glob_with_path(self, tool_context, sample_files):
        """测试指定路径"""
        tool = GlobTool()
        ctx = ToolContext(cwd=sample_files)
        src_path = os.path.join(sample_files, "src")
        result = await tool.execute(
            {"pattern": "*.py", "path": src_path},
            ctx
        )
        assert "main.py" in result.output

    @pytest.mark.asyncio
    async def test_glob_no_results(self, tool_context, sample_files):
        """测试无结果"""
        tool = GlobTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "*.xyz"},
            ctx
        )
        assert "No files found" in result.output

    @pytest.mark.asyncio
    async def test_glob_nonexistent_path(self, tool_context):
        """测试不存在的路径"""
        tool = GlobTool()
        result = await tool.execute(
            {"pattern": "*.py", "path": "/nonexistent"},
            tool_context
        )
        assert "does not exist" in result.output.lower()


# ==================== GrepTool 测试 ====================

class TestGrepTool:
    """测试 GrepTool"""

    @pytest.mark.asyncio
    async def test_grep_basic(self, tool_context, sample_files):
        """测试基本搜索"""
        tool = GrepTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "def main"},
            ctx
        )
        assert "def main" in result.output
        assert "Found" in result.output

    @pytest.mark.asyncio
    async def test_grep_with_include(self, tool_context, sample_files):
        """测试文件类型过滤"""
        tool = GrepTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "def", "include": "*.py"},
            ctx
        )
        assert "main.py" in result.output
        assert "helper.py" in result.output

    @pytest.mark.asyncio
    async def test_grep_regex(self, tool_context, sample_files):
        """测试正则表达式"""
        tool = GrepTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "class.*Helper"},
            ctx
        )
        assert "class Helper" in result.output

    @pytest.mark.asyncio
    async def test_grep_no_results(self, tool_context, sample_files):
        """测试无结果"""
        tool = GrepTool()
        ctx = ToolContext(cwd=sample_files)
        result = await tool.execute(
            {"pattern": "nonexistent_pattern_xyz"},
            ctx
        )
        assert "No files found" in result.output

    @pytest.mark.asyncio
    async def test_grep_invalid_regex(self, tool_context):
        """测试无效正则表达式"""
        tool = GrepTool()
        result = await tool.execute(
            {"pattern": "[invalid"},
            tool_context
        )
        assert "Invalid regex" in result.output

    @pytest.mark.asyncio
    async def test_grep_with_path(self, tool_context, sample_files):
        """测试指定路径"""
        tool = GrepTool()
        ctx = ToolContext(cwd=sample_files)
        src_path = os.path.join(sample_files, "src")
        result = await tool.execute(
            {"pattern": "def", "path": src_path},
            ctx
        )
        assert "def main" in result.output or "def helper" in result.output


# ==================== 集成测试 ====================

class TestIntegration:
    """集成测试"""

    def test_register_builtin_tools(self):
        """测试注册所有内置工具"""
        registry = register_builtin_tools()
        tools = registry.list_ids()
        assert "shell" in tools
        assert "read" in tools
        assert "write" in tools
        assert "glob" in tools
        assert "grep" in tools
        assert "webfetch" in tools
        assert len(tools) == 6

    @pytest.mark.asyncio
    async def test_write_then_read(self, temp_dir):
        """测试写入后读取"""
        registry = register_builtin_tools()
        ctx = ToolContext(cwd=temp_dir)

        # 写入文件
        write_result = await registry.execute(
            "write",
            {"filePath": os.path.join(temp_dir, "test.txt"), "content": "Hello, World!"},
            ctx
        )
        assert "successfully" in write_result.output.lower()

        # 读取文件
        read_result = await registry.execute(
            "read",
            {"filePath": os.path.join(temp_dir, "test.txt")},
            ctx
        )
        assert "Hello, World!" in read_result.output

    @pytest.mark.asyncio
    async def test_glob_then_grep(self, sample_files):
        """测试 glob 后 grep"""
        registry = register_builtin_tools()
        ctx = ToolContext(cwd=sample_files)

        # 先 glob 查找文件
        glob_result = await registry.execute(
            "glob",
            {"pattern": "**/*.py"},
            ctx
        )
        assert "main.py" in glob_result.output

        # 再 grep 搜索内容
        grep_result = await registry.execute(
            "grep",
            {"pattern": "def", "include": "*.py"},
            ctx
        )
        assert "def main" in grep_result.output

    @pytest.mark.asyncio
    async def test_shell_command(self, temp_dir):
        """测试 shell 命令"""
        registry = register_builtin_tools()
        ctx = ToolContext(cwd=temp_dir)

        result = await registry.execute(
            "shell",
            {"command": "echo test_output"},
            ctx
        )
        assert "test_output" in result.output


# ==================== 运行测试 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
