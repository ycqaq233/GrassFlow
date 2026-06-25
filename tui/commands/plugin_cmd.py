"""
grassflow plugin 命令

参考 opencode 的插件系统，实现插件管理：
- plugin list: 列出已安装插件
- plugin install <name>: 安装插件
- plugin uninstall <name>: 卸载插件
"""

import sys
import json
import shutil
from pathlib import Path
from typing import List, Dict, Optional

import click

from tui.display import display


def _get_plugins_dir() -> Path:
    """获取插件目录"""
    return Path.home() / ".Grass" / "plugins"


def _get_project_plugins_dir() -> Optional[Path]:
    """获取项目插件目录"""
    project_plugins = Path.cwd() / ".grass" / "plugins"
    if project_plugins.exists():
        return project_plugins
    return None


def _get_plugin_manifest(plugin_dir: Path) -> Optional[Dict]:
    """读取插件清单"""
    manifest_file = plugin_dir / "manifest.json"
    if not manifest_file.exists():
        return None
    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _list_plugins(plugins_dir: Path) -> List[Dict]:
    """列出目录中的插件"""
    plugins = []
    if not plugins_dir.exists():
        return plugins

    for item in plugins_dir.iterdir():
        if item.is_dir():
            manifest = _get_plugin_manifest(item)
            if manifest:
                plugins.append({
                    "name": item.name,
                    "path": str(item),
                    "version": manifest.get("version", "unknown"),
                    "description": manifest.get("description", ""),
                    "author": manifest.get("author", ""),
                    "enabled": not (item / ".disabled").exists(),
                    "scope": "project" if ".grass" in str(item) else "global",
                })
            else:
                # 没有 manifest，但仍然是一个有效的插件目录
                plugins.append({
                    "name": item.name,
                    "path": str(item),
                    "version": "unknown",
                    "description": "",
                    "author": "",
                    "enabled": not (item / ".disabled").exists(),
                    "scope": "project" if ".grass" in str(item) else "global",
                })

    return plugins


def plugin_list() -> None:
    """列出已安装插件"""
    try:
        from rich.table import Table
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
    except ImportError:
        console = None

    # 全局插件
    global_dir = _get_plugins_dir()
    global_plugins = _list_plugins(global_dir)

    # 项目插件
    project_dir = _get_project_plugins_dir()
    project_plugins = _list_plugins(project_dir) if project_dir else []

    all_plugins = global_plugins + project_plugins

    if not all_plugins:
        if console:
            console.print(Panel(
                "[dim]No plugins installed.[/dim]\n\n"
                "Install a plugin with:\n"
                "  grassflow plugin install <name>\n\n"
                "Plugin directories:\n"
                f"  Global: {global_dir}\n"
                f"  Project: {Path.cwd() / '.grass' / 'plugins'}",
                title="Plugins",
                border_style="blue"
            ))
        else:
            display.print_info("No plugins installed.")
            display.print_info(f"Global plugins dir: {global_dir}")
        return

    if console:
        table = Table(title="Installed Plugins", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Version", style="green")
        table.add_column("Description", style="white")
        table.add_column("Scope", style="yellow")
        table.add_column("Status", style="blue")
        table.add_column("Path", style="dim")

        for plugin in all_plugins:
            status = "[green]enabled[/green]" if plugin["enabled"] else "[red]disabled[/red]"
            scope = "[blue]project[/blue]" if plugin["scope"] == "project" else "[dim]global[/dim]"
            table.add_row(
                plugin["name"],
                plugin["version"],
                plugin["description"][:50] if plugin["description"] else "-",
                scope,
                status,
                plugin["path"],
            )

        console.print(table)
        console.print()
        console.print(f"[dim]Total: {len(all_plugins)} plugin(s)[/dim]")
        console.print(f"[dim]Global plugins: {global_dir}[/dim]")
        if project_dir:
            console.print(f"[dim]Project plugins: {project_dir}[/dim]")
    else:
        display.print_info("Installed Plugins:")
        display.print_info("-" * 40)
        for plugin in all_plugins:
            status = "enabled" if plugin["enabled"] else "disabled"
            display.print_info(
                f"  {plugin['name']} v{plugin['version']} [{plugin['scope']}] [{status}]"
            )
            if plugin["description"]:
                display.print_info(f"    {plugin['description'][:80]}")
        print()


def plugin_install(name: str, scope: str = "global") -> None:
    """
    安装插件

    参考 opencode plugin 命令：
    - 支持从 PyPI 安装（pip install）
    - 支持从本地路径安装
    - 支持从 GitHub 安装

    Args:
        name: 插件名称、路径或 URL
        scope: 安装范围（global/project）
    """
    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        console = None

    if scope == "project":
        plugins_dir = Path.cwd() / ".grass" / "plugins"
    else:
        plugins_dir = _get_plugins_dir()

    plugins_dir.mkdir(parents=True, exist_ok=True)

    plugin_target_dir = plugins_dir / name

    if plugin_target_dir.exists():
        if console:
            console.print(f"[yellow]Plugin '{name}' is already installed at {plugin_target_dir}[/yellow]")
            console.print("To reinstall, uninstall first: grassflow plugin uninstall <name>")
        else:
            display.print_info(f"Plugin '{name}' already installed at {plugin_target_dir}")
        return

    # 检查是否是 PyPI 包名（grassflow-plugin-* 或直接是 Python 包名）
    try:
        import subprocess

        # 尝试通过 pip 安装
        pip_name = f"grassflow-plugin-{name}"
        if console:
            console.print(f"[dim]Attempting to install {pip_name} via pip...[/dim]")
        else:
            display.print_info(f"Attempting to install {pip_name} via pip...")

        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_name, "--target", str(plugin_target_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            # 创建 manifest
            manifest = {
                "name": name,
                "version": "1.0.0",
                "description": f"Plugin installed from PyPI: {pip_name}",
                "author": "",
                "install_method": "pip",
            }
            manifest_file = plugin_target_dir / "manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            if console:
                console.print(f"[green]✓[/green] Plugin '{name}' installed successfully to {plugin_target_dir}")
            else:
                display.print_success(f"Plugin '{name}' installed to {plugin_target_dir}")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            if console:
                console.print(f"[yellow]Could not install via pip: {error_msg[:200]}[/yellow]")
                console.print("\n[yellow]To install a plugin:[/yellow]")
                console.print("  1. Place plugin files in the plugins directory:")
                console.print(f"     {plugins_dir / name}")
                console.print("  2. Create a manifest.json file")
                console.print("\n[dim]Plugin manifest format:[/dim]")
                console.print('  { "name": "...", "version": "1.0.0", "description": "..." }')
            else:
                display.print_info(f"Could not install via pip: {error_msg[:200]}")
                display.print_info(f"Manually place plugin files in: {plugins_dir / name}")

    except subprocess.TimeoutExpired:
        if console:
            console.print("[red]pip install timed out[/red]")
        else:
            display.print_error("pip install timed out")
    except FileNotFoundError:
        if console:
            console.print("[red]pip not found[/red]")
        else:
            display.print_error("pip not found")
    except Exception as e:
        display.print_error(f"Install failed: {e}")
        sys.exit(1)


def plugin_uninstall(name: str, scope: str = "all", force: bool = False) -> None:
    """
    卸载插件

    Args:
        name: 插件名称
        scope: 卸载范围（global/project/all）
        force: 强制卸载，不提示确认
    """
    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        console = None

    removed = False

    # 检查全局
    if scope in ("global", "all"):
        global_dir = _get_plugins_dir()
        plugin_dir = global_dir / name
        if plugin_dir.exists():
            if not force:
                if console:
                    if not click.confirm(f"Uninstall global plugin '{name}'?"):
                        return
                else:
                    resp = input(f"Uninstall global plugin '{name}'? [y/N] ")
                    if resp.lower() not in ("y", "yes"):
                        return

            shutil.rmtree(plugin_dir)
            if console:
                console.print(f"[green]✓[/green] Removed global plugin: {plugin_dir}")
            else:
                display.print_success(f"Removed global plugin: {plugin_dir}")
            removed = True

    # 检查项目
    if scope in ("project", "all"):
        project_dir = _get_project_plugins_dir()
        if project_dir:
            plugin_dir = project_dir / name
        else:
            plugin_dir = Path.cwd() / ".grass" / "plugins" / name

        if plugin_dir.exists():
            if not force:
                if console:
                    if not click.confirm(f"Uninstall project plugin '{name}'?"):
                        return
                else:
                    resp = input(f"Uninstall project plugin '{name}'? [y/N] ")
                    if resp.lower() not in ("y", "yes"):
                        return

            shutil.rmtree(plugin_dir)
            if console:
                console.print(f"[green]✓[/green] Removed project plugin: {plugin_dir}")
            else:
                display.print_success(f"Removed project plugin: {plugin_dir}")
            removed = True

    if not removed:
        if console:
            console.print(f"[yellow]Plugin '{name}' not found[/yellow]")
        else:
            display.print_info(f"Plugin '{name}' not found")


# Click 命令组包装
@click.group(name="plugin")
def plugin_command():
    """管理 GrassFlow 插件"""
    pass


@plugin_command.command(name="list")
def plugin_list_cmd():
    """列出已安装插件"""
    plugin_list()


@plugin_command.command(name="install")
@click.argument("name")
@click.option("--scope", "-s", type=click.Choice(["global", "project"]), default="global",
              help="安装范围")
def plugin_install_cmd(name: str, scope: str):
    """安装插件"""
    plugin_install(name, scope=scope)


@plugin_command.command(name="uninstall")
@click.argument("name")
@click.option("--scope", "-s", type=click.Choice(["global", "project", "all"]), default="all",
              help="卸载范围")
@click.option("--force", "-f", is_flag=True, help="强制卸载，不提示确认")
def plugin_uninstall_cmd(name: str, scope: str, force: bool):
    """卸载插件"""
    plugin_uninstall(name, scope=scope, force=force)
