"""GrassFlow TUI 配置集成层

统一的配置访问入口，包装 core.config.config_manager 并添加：
- 线程安全读写（threading.RLock）
- 基于 mtime/size 的缓存失效
- cfg_get 安全嵌套访问器
- load_config_readonly 快速路径
- 配置损坏备份与警告
- TUI 专用便捷函数

参考 hermes_cli/config.py 的设计模式。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.config import ConfigManager, GrassFlowConfig, config_manager as _base_manager, _NOT_LOADED

logger = logging.getLogger(__name__)

# ─── Thread Safety ────────────────────────────────────────────────────────────

_CONFIG_LOCK = threading.RLock()

# ─── Cache (mtime-based) ─────────────────────────────────────────────────────

# (mtime_ns, size) -> cached GrassFlowConfig
_GLOBAL_CACHE: Optional[Tuple[int, int, GrassFlowConfig]] = None
_PROJECT_CACHE: Optional[Tuple[int, int, GrassFlowConfig]] = None
_MERGED_CACHE: Optional[Tuple[int, int, int, int, GrassFlowConfig]] = None

_CONFIG_PARSE_WARNED: set = set()


# ─── Corruption Recovery ─────────────────────────────────────────────────────

def _backup_corrupt_config(config_path: Path) -> Optional[Path]:
    """备份损坏的配置文件为 .corrupt.<ts>.bak"""
    try:
        if config_path.is_symlink():
            return None
        st = config_path.stat()
        if st.st_size == 0:
            return None
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.corrupt.{ts}.bak")
        if backup_path.exists():
            return None
        shutil.copy2(config_path, backup_path)
        return backup_path
    except Exception:
        return None


def _warn_config_parse_failure(config_path: Path, exc: Exception) -> None:
    """配置解析失败时发出详细警告（每文件仅警告一次）"""
    try:
        st = config_path.stat()
        key = (str(config_path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(config_path), 0, 0)
    if key in _CONFIG_PARSE_WARNED:
        return
    _CONFIG_PARSE_WARNED.add(key)

    backup_path = _backup_corrupt_config(config_path)
    msg = (
        f"配置解析失败: {config_path}: {exc}. "
        f"将使用默认配置 -- 所有用户自定义设置将被忽略。"
    )
    if backup_path is not None:
        msg += f" 损坏文件已备份至 {backup_path}"
    logger.warning(msg)
    try:
        import sys
        sys.stderr.write(f"[WARNING] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


# ─── Safe Accessor ────────────────────────────────────────────────────────────

def cfg_get(cfg: Any, *keys: str, default: Any = None) -> Any:
    """安全遍历嵌套 dict，处理 None/非 dict/缺失键。

    参考 hermes_cli/config.py 的 cfg_get 实现。

    Examples:
        >>> cfg_get({"llm": {"default_model": "gpt-4"}}, "llm", "default_model")
        'gpt-4'
        >>> cfg_get({}, "llm", "default_model", default="deepseek-chat")
        'deepseek-chat'
        >>> cfg_get(None, "anything", default=42)
        42
    """
    if not isinstance(cfg, dict):
        return default
    node: Any = cfg
    for key in keys:
        if not isinstance(node, dict):
            return default
        if key not in node:
            return default
        node = node[key]
    return node


# ─── Cached Config Loading ───────────────────────────────────────────────────

def _file_sig(path: Path) -> Optional[Tuple[int, int]]:
    """获取文件的 (mtime_ns, size) 签名，不存在返回 None"""
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except (FileNotFoundError, OSError):
        return None


def load_config() -> GrassFlowConfig:
    """加载配置（带 mtime 缓存 + deepcopy，可安全变异）。

    优先级：环境变量 > 项目配置 > 全局配置 > 默认值
    """
    global _GLOBAL_CACHE, _PROJECT_CACHE, _MERGED_CACHE
    with _CONFIG_LOCK:
        global_path = _base_manager.global_config_file
        project_path = _base_manager.project_config_file

        g_sig = _file_sig(global_path)
        p_sig = _file_sig(project_path)

        # 检查合并缓存
        if _MERGED_CACHE is not None:
            g_cached, p_cached, merged_cfg = _MERGED_CACHE[0:2], _MERGED_CACHE[2:4], _MERGED_CACHE[4]
            if g_cached == g_sig and p_cached == p_sig:
                return copy.deepcopy(merged_cfg)

        # 缓存未命中，重新加载
        _base_manager._global_config = None
        _base_manager._project_config = None
        _base_manager._merged_config = None

        try:
            result = _base_manager.load_config()
        except Exception as exc:
            _warn_config_parse_failure(global_path, exc)
            result = None

        if result is None:
            result = GrassFlowConfig()

        # 更新缓存
        _MERGED_CACHE = (
            g_sig[0] if g_sig else 0,
            g_sig[1] if g_sig else 0,
            p_sig[0] if p_sig else 0,
            p_sig[1] if p_sig else 0,
            copy.deepcopy(result),
        )
        return result


def load_config_readonly() -> GrassFlowConfig:
    """快速路径：只读配置访问，跳过 deepcopy。

    调用方承诺不修改返回值。用于 agent loop 等热路径。
    参考 hermes_cli/config.py 的 load_config_readonly()。
    """
    global _GLOBAL_CACHE, _PROJECT_CACHE, _MERGED_CACHE
    with _CONFIG_LOCK:
        global_path = _base_manager.global_config_file
        project_path = _base_manager.project_config_file

        g_sig = _file_sig(global_path)
        p_sig = _file_sig(project_path)

        if _MERGED_CACHE is not None:
            g_cached, p_cached, merged_cfg = _MERGED_CACHE[0:2], _MERGED_CACHE[2:4], _MERGED_CACHE[4]
            if g_cached == g_sig and p_cached == p_sig:
                return merged_cfg

        # 缓存未命中，走完整加载
        _base_manager._global_config = _NOT_LOADED
        _base_manager._project_config = _NOT_LOADED
        _base_manager._merged_config = _NOT_LOADED

        try:
            result = _base_manager.load_config()
        except Exception as exc:
            _warn_config_parse_failure(global_path, exc)
            result = None

        if result is None:
            result = GrassFlowConfig()

        cached_copy = copy.deepcopy(result)
        _MERGED_CACHE = (
            g_sig[0] if g_sig else 0,
            g_sig[1] if g_sig else 0,
            p_sig[0] if p_sig else 0,
            p_sig[1] if p_sig else 0,
            cached_copy,
        )
        return cached_copy


def save_config(config: GrassFlowConfig, scope: str = "global") -> None:
    """保存配置（线程安全 + 缓存失效）"""
    global _MERGED_CACHE
    with _CONFIG_LOCK:
        if scope == "global":
            _base_manager.save_global_config(config)
        else:
            _base_manager.save_project_config(config)
        _MERGED_CACHE = None


def invalidate_cache() -> None:
    """手动使所有缓存失效（用于外部配置修改后）"""
    global _GLOBAL_CACHE, _PROJECT_CACHE, _MERGED_CACHE
    with _CONFIG_LOCK:
        _GLOBAL_CACHE = None
        _PROJECT_CACHE = None
        _MERGED_CACHE = None
        _base_manager._global_config = None
        _base_manager._project_config = None
        _base_manager._merged_config = None


# ─── TUI Convenience Functions ───────────────────────────────────────────────

def get(key: str, default: Any = None) -> Any:
    """获取配置值（点号分隔嵌套键）"""
    config = load_config()
    data = config.model_dump()
    return cfg_get(data, *key.split("."), default=default)


def get_readonly(key: str, default: Any = None) -> Any:
    """获取配置值（只读快速路径）"""
    config = load_config_readonly()
    data = config.model_dump()
    return cfg_get(data, *key.split("."), default=default)


def get_theme_name() -> str:
    """获取当前主题名称"""
    return get_readonly("display.theme", "default")


def get_model_config() -> Tuple[str, str]:
    """获取 (provider, model) 元组"""
    config = load_config_readonly()
    return (config.llm.default_provider or "deepseek", config.llm.default_model or "deepseek-chat")


def get_api_key(provider: str) -> Optional[str]:
    """获取指定 provider 的 API Key"""
    return _base_manager.get_api_key(provider)


def get_db_path() -> str:
    """获取数据库路径"""
    return get_readonly("db_path", "~/.Grass/grassflow.db")


def get_mcp_servers() -> Dict[str, Any]:
    """获取 MCP 服务器配置"""
    return get_readonly("mcp_servers", {})


def get_display_config() -> Dict[str, Any]:
    """获取显示配置"""
    config = load_config_readonly()
    return config.display.model_dump()


def get_llm_config() -> Dict[str, Any]:
    """获取 LLM 配置"""
    config = load_config_readonly()
    return config.llm.model_dump()


# Re-export config_manager for backward compatibility (TUI files can import from here)
config_manager = _base_manager
