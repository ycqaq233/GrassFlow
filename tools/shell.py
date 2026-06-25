"""
GrassFlow Shell 工具

执行 shell 命令，参考 opencode 的 ShellTool 实现
"""

import asyncio
import os
import sys
import subprocess
from typing import Any, Dict, Optional
from .tool import Tool, ToolContext, ToolResult


class ShellTool(Tool):
    """
    Shell 工具 - 执行 shell 命令

    支持:
    - 执行任意 shell 命令
    - 设置超时
    - 设置工作目录
    - 捕获 stdout 和 stderr
    """

    @property
    def id(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return """Execute a shell command and return its output.

Use this tool to run system commands, scripts, or any shell operations.
The command will be executed in the specified working directory (or current directory if not specified).

Important:
- Commands are executed with the user's default shell
- Use appropriate timeouts for long-running commands
- Be cautious with destructive commands (rm, mv, etc.)
- On Windows, use PowerShell or cmd commands as appropriate"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for command execution (optional, defaults to current directory)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (optional, defaults to 60)",
                    "default": 60
                },
                "env": {
                    "type": "object",
                    "description": "Additional environment variables (optional)",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["command"]
        }

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行 shell 命令"""
        command = params["command"]
        workdir = params.get("workdir", ctx.cwd)
        timeout = params.get("timeout", ctx.timeout)
        env_overrides = params.get("env", {})

        # 解析工作目录
        if not os.path.isabs(workdir):
            workdir = os.path.join(ctx.cwd, workdir)
        workdir = os.path.abspath(workdir)

        # 检查工作目录是否存在
        if not os.path.isdir(workdir):
            return ToolResult(
                output=f"Error: Working directory does not exist: {workdir}",
                title=command,
                metadata={"error": "invalid_workdir", "workdir": workdir}
            )

        # 准备环境变量
        env = os.environ.copy()
        env.update(env_overrides)

        # 根据平台选择 shell
        if sys.platform == "win32":
            # Windows: 使用 PowerShell
            shell_cmd = ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            # Unix: 使用 /bin/sh
            shell_cmd = ["/bin/sh", "-c", command]

        try:
            # 执行命令
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                # 超时，杀死进程
                process.kill()
                await process.wait()
                return ToolResult(
                    output=f"Command timed out after {timeout} seconds",
                    title=command,
                    metadata={
                        "timeout": True,
                        "timeout_seconds": timeout
                    }
                )

            # 解码输出
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            # 构建输出
            output_parts = []
            if stdout_str:
                output_parts.append(stdout_str)
            if stderr_str:
                output_parts.append(f"<stderr>\n{stderr_str}\n</stderr>")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            # 检查是否被截断
            max_output_length = 30000
            truncated = len(output) > max_output_length
            if truncated:
                output = "...\n\n" + output[-max_output_length:]

            return ToolResult(
                output=output,
                title=command,
                metadata={
                    "exit_code": process.returncode,
                    "stdout_length": len(stdout_str),
                    "stderr_length": len(stderr_str),
                    "truncated": truncated,
                    "workdir": workdir,
                },
                truncated=truncated
            )

        except Exception as e:
            return ToolResult(
                output=f"Error executing command: {str(e)}",
                title=command,
                metadata={"error": str(e), "workdir": workdir}
            )
