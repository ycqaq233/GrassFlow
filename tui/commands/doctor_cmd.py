"""
grassflow doctor 命令

参考 hermes 的检查机制，实现系统健康检查：
- Python 版本检查
- pip 包检查
- 配置文件检查
- API Keys 检查
- 数据库检查
- 工具检查
"""

import sys
import importlib
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Any

import click

from tui.display import display

# 工具映射：检查系统中可用的工具
TOOLS = {
    "shell": "bash" if sys.platform != "win32" else "powershell",
    "read": "内置",
    "write": "内置",
    "glob": "内置",
    "grep": "内置",
    "python": None,
    "git": "git",
    "pip": "pip",
}


def _check_python() -> Tuple[bool, str]:
    """检查 Python 版本"""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    is_ok = (version.major, version.minor) >= (3, 10)
    return is_ok, version_str


def _check_package(package_name: str) -> Tuple[bool, str]:
    """检查 pip 包是否安装"""
    try:
        mod = importlib.import_module(package_name)
        version = getattr(mod, "__version__", "installed")
        return True, version
    except ImportError:
        return False, "not installed"


def _check_command(cmd: str) -> Tuple[bool, str]:
    """检查系统命令是否可用"""
    if cmd is None:
        return True, "N/A"
    path = shutil.which(cmd)
    if path:
        return True, path
    return False, "not found"


def _check_config() -> Tuple[bool, Dict[str, Any]]:
    """检查配置文件"""
    result = {
        "global_exists": False,
        "global_path": str(Path.home() / ".Grass" / "config.json"),
        "project_exists": False,
        "project_path": str(Path.cwd() / ".grass" / "config.json"),
    }

    global_config = Path.home() / ".Grass" / "config.json"
    project_config = Path.cwd() / ".grass" / "config.json"

    result["global_exists"] = global_config.exists()
    result["project_exists"] = project_config.exists()

    return result["global_exists"] or result["project_exists"], result


def _check_api_keys() -> Dict[str, bool]:
    """检查 API Keys 配置"""
    keys_status = {}

    try:
        from core.config import config_manager
        config = config_manager.load_config()

        # 检查 provider 中的 apiKey
        for provider_name, provider_config in config.provider.items():
            has_key = bool(provider_config.options.apiKey)
            keys_status[provider_name] = has_key

        # 如果没有 provider 配置，检查环境变量
        if not keys_status:
            import os
            env_checks = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
            }
            for name, env_var in env_checks.items():
                keys_status[name] = bool(os.environ.get(env_var))

    except Exception:
        # 如果无法加载配置，检查环境变量
        import os
        env_checks = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        for name, env_var in env_checks.items():
            keys_status[name] = bool(os.environ.get(env_var))

    return keys_status


def _check_db() -> Tuple[bool, str]:
    """检查数据库"""
    try:
        from core.db import execution_db
        db_path = execution_db.db_path
        if Path(db_path).exists():
            return True, db_path
        return True, f"{db_path} (will be created on first use)"
    except ImportError:
        db_path = str(Path.home() / ".Grass" / "grassflow.db")
        if Path(db_path).exists():
            return True, db_path
        return False, f"{db_path} (not found)"
    except Exception as e:
        return False, str(e)


def doctor_command() -> None:
    """
    系统健康检查

    参考 hermes 的检查机制，全面检查 GrassFlow 运行环境：
    - Python 版本
    - 核心依赖
    - 配置文件
    - API Keys
    - 数据库
    - 可用工具
    """
    issues: List[str] = []
    warnings: List[str] = []

    try:
        from rich.table import Table
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()
    except ImportError:
        console = None

    # ========== 1. Python 版本 ==========
    py_ok, py_version = _check_python()
    if console:
        console.print(Panel(Text("GrassFlow Doctor - System Health Check", style="bold blue")))
        console.print()

        # Python
        py_icon = "[green]✓[/green]" if py_ok else "[red]✗[/red]"
        console.print(f"  {py_icon} Python {py_version}")
        if not py_ok:
            issues.append(f"Python {py_version} < 3.10")

        # ========== 2. pip 包检查 ==========
        console.print()
        console.print("  [bold]Core Dependencies:[/bold]")

        core_packages = [
            ("click", "click"),
            ("rich", "rich"),
            ("pydantic", "pydantic"),
            ("asyncio", "asyncio"),
        ]

        for display_name, import_name in core_packages:
            ok, ver = _check_package(import_name)
            icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
            ver_text = f" ({ver})" if ok else ""
            console.print(f"    {icon} {display_name}{ver_text}")
            if not ok:
                issues.append(f"Missing package: {display_name}")

        # 可选包
        optional_packages = [
            ("textual", "textual"),
            ("aiohttp", "aiohttp"),
            ("websockets", "websockets"),
            ("prompt_toolkit", "prompt_toolkit"),
        ]

        console.print("  [bold]Optional Dependencies:[/bold]")
        for display_name, import_name in optional_packages:
            ok, ver = _check_package(import_name)
            icon = "[green]✓[/green]" if ok else "[dim]○[/dim]"
            ver_text = f" ({ver})" if ok else " (not installed)"
            console.print(f"    {icon} {display_name}{ver_text}")
            if not ok:
                warnings.append(f"Optional package not installed: {display_name}")

        # ========== 3. 配置文件 ==========
        console.print()
        console.print("  [bold]Configuration:[/bold]")

        config_ok, config_info = _check_config()

        # 全局配置
        g_icon = "[green]✓[/green]" if config_info["global_exists"] else "[dim]○[/dim]"
        console.print(f"    {g_icon} Global config: {config_info['global_path']}")

        # 项目配置
        p_icon = "[green]✓[/green]" if config_info["project_exists"] else "[dim]○[/dim]"
        console.print(f"    {p_icon} Project config: {config_info['project_path']}")

        if not config_ok:
            warnings.append("No config file found. Run 'grassflow init' to create one.")

        # ========== 4. API Keys ==========
        console.print()
        console.print("  [bold]API Keys:[/bold]")

        keys_status = _check_api_keys()
        if keys_status:
            for provider, has_key in keys_status.items():
                icon = "[green]✓[/green]" if has_key else "[yellow]✗[/yellow]"
                status = "configured" if has_key else "not configured"
                console.print(f"    {icon} {provider}: {status}")
                if not has_key:
                    warnings.append(f"API key not configured for {provider}")
        else:
            console.print("    [dim]○ No providers configured[/dim]")
            warnings.append("No API providers configured. Run 'grassflow config api-key <provider> <key>'")

        # ========== 5. 数据库 ==========
        console.print()
        console.print("  [bold]Database:[/bold]")

        db_ok, db_info = _check_db()
        db_icon = "[green]✓[/green]" if db_ok else "[red]✗[/red]"
        console.print(f"    {db_icon} {db_info}")
        if not db_ok:
            issues.append(f"Database issue: {db_info}")

        # ========== 6. 工具检查 ==========
        console.print()
        console.print("  [bold]Tools:[/bold]")

        for tool_name, cmd in TOOLS.items():
            if cmd == "内置":
                console.print(f"    [green]✓[/green] {tool_name}: built-in")
            else:
                ok, path = _check_command(cmd)
                icon = "[green]✓[/green]" if ok else "[yellow]✗[/yellow]"
                path_text = f" ({path})" if ok else f" ({path})"
                console.print(f"    {icon} {tool_name}: {cmd}{path_text}")
                if not ok and tool_name in ("git", "pip"):
                    warnings.append(f"System tool not found: {cmd}")

        # ========== 7. 工作流目录 ==========
        console.print()
        console.print("  [bold]Workspace:[/bold]")

        workflows_dir = Path.home() / ".Grass" / "workflows"
        if workflows_dir.exists():
            wf_count = len(list(workflows_dir.glob("*.json")))
            console.print(f"    [green]✓[/green] Workflows directory: {workflows_dir}")
            console.print(f"    [green]✓[/green] Saved workflows: {wf_count}")
        else:
            console.print(f"    [dim]○ Workflows directory will be created on first use[/dim]")

        # ========== 8. 总结 ==========
        console.print()
        if not issues and not warnings:
            console.print(Panel(
                "[green]All checks passed! GrassFlow is ready to use.[/green]",
                title="Result",
                border_style="green"
            ))
        elif issues:
            console.print(Panel(
                f"[red]{len(issues)} issue(s) found[/red]\n" +
                "\n".join(f"  • {i}" for i in issues) +
                ("\n\n" + "\n".join(f"  • {w}" for w in warnings) if warnings else ""),
                title="Result",
                border_style="red"
            ))
            sys.exit(1)
        else:
            console.print(Panel(
                f"[yellow]{len(warnings)} warning(s)[/yellow]\n" +
                "\n".join(f"  • {w}" for w in warnings),
                title="Result",
                border_style="yellow"
            ))

    except ImportError:
        # 无 Rich 时的降级输出
        print("GrassFlow Doctor - System Health Check")
        print("=" * 50)
        print()

        py_ok, py_version = _check_python()
        print(f"  {'OK' if py_ok else 'FAIL'} Python {py_version}")

        print()
        print("  Core Dependencies:")
        for display_name, import_name in [("click", "click"), ("rich", "rich"), ("pydantic", "pydantic")]:
            ok, ver = _check_package(import_name)
            print(f"    {'OK' if ok else 'FAIL'} {display_name} ({ver})")

        print()
        print("  Configuration:")
        config_ok, config_info = _check_config()
        print(f"    Global: {config_info['global_path']} - {'EXISTS' if config_info['global_exists'] else 'MISSING'}")
        print(f"    Project: {config_info['project_path']} - {'EXISTS' if config_info['project_exists'] else 'MISSING'}")

        print()
        print("  API Keys:")
        keys_status = _check_api_keys()
        for provider, has_key in keys_status.items():
            print(f"    {provider}: {'OK' if has_key else 'MISSING'}")

        if issues:
            print(f"\n{len(issues)} issue(s) found!")
            sys.exit(1)

    except Exception as e:
        display.print_error(f"Doctor check failed: {e}")
        sys.exit(1)
