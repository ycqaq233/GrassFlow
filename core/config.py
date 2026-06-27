"""
GrassFlow 配置管理

参考 opencode 的配置形式，支持多级配置：
- 全局配置：~/.Grass/config.json
- 项目配置：.grass/config.json
- 环境变量：GRASSFLOW_*

配置优先级：环境变量 > 项目配置 > 全局配置 > 默认值
"""

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict
import logging

logger = logging.getLogger(__name__)


class APIKeys(BaseModel):
    """API Keys 配置（向后兼容）"""
    model_config = ConfigDict(extra="allow")

    openai: Optional[str] = None
    anthropic: Optional[str] = None
    deepseek: Optional[str] = None
    ollama: Optional[str] = None


class ProviderModelConfig(BaseModel):
    """Provider 模型配置"""
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    limit: Optional[Dict[str, int]] = None
    modalities: Optional[Dict[str, List[str]]] = None
    options: Optional[Dict[str, Any]] = None


class ProviderOptions(BaseModel):
    """Provider 选项"""
    model_config = ConfigDict(extra="allow")

    apiKey: Optional[str] = None
    baseURL: Optional[str] = None


class ProviderConfig(BaseModel):
    """Provider 配置"""
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    npm: Optional[str] = None
    models: Dict[str, ProviderModelConfig] = Field(default_factory=dict)
    options: ProviderOptions = Field(default_factory=ProviderOptions)


class LLMConfig(BaseModel):
    """LLM 配置"""
    default_model: str = "deepseek-v4-flash"
    default_provider: str = "deepseek"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    retry_count: int = 3
    retry_delay: float = 1.0


class WorkflowConfig(BaseModel):
    """工作流配置"""
    auto_save: bool = True
    auto_validate: bool = True
    max_parallel: int = 10
    default_on_fail: str = "stop"
    execution_timeout: int = 300
    max_iterations: int = 30


class DisplayConfig(BaseModel):
    """显示配置"""
    theme: str = "dark"
    show_timestamps: bool = True
    show_agent_names: bool = True
    log_level: str = "INFO"
    compact_mode: bool = False


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "localhost"
    port: int = 8000
    cors_origins: List[str] = ["*"]
    debug: bool = False


class GrassFlowConfig(BaseModel):
    """GrassFlow 全局配置"""
    model_config = ConfigDict(extra="allow")

    version: str = "1.0.0"
    provider: Dict[str, ProviderConfig] = Field(default_factory=dict)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    mcp_servers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    permissions: Dict[str, Any] = Field(default_factory=dict)
    workflows_dir: str = "~/.Grass/workflows"
    db_path: str = "~/.Grass/grassflow.db"
    plugins_dir: str = "~/.Grass/plugins"

    def model_post_init(self, __context: Any) -> None:
        """Post-init: expand paths and warn on unknown fields."""
        self.workflows_dir = os.path.expanduser(self.workflows_dir)
        self.db_path = os.path.expanduser(self.db_path)
        self.plugins_dir = os.path.expanduser(self.plugins_dir)

        # Warn on extra (unknown) fields — likely typos
        known_fields = set(self.model_fields.keys())
        extra_fields = set(self.__pydantic_extra__ or {}) - known_fields
        if extra_fields:
            logger.warning(
                "Unknown config keys (possible typos): %s. "
                "Known fields: %s",
                ", ".join(sorted(extra_fields)),
                ", ".join(sorted(known_fields)),
            )


_NOT_LOADED = object()  # Sentinel: distinguishes 'not yet loaded' from 'loaded as None'


class ConfigManager:
    """配置管理器

    支持多级配置：
    - 全局配置：~/.Grass/config.json
    - 项目配置：.grass/config.json
    - 环境变量：GRASSFLOW_*
    """

    ENV_PREFIX = "GRASSFLOW_"

    def __init__(self, config_dir: Optional[str] = None, project_dir: Optional[str] = None):
        # 全局配置目录
        if config_dir:
            self.global_config_dir = Path(config_dir)
        else:
            self.global_config_dir = Path.home() / ".Grass"

        # 项目配置目录
        if project_dir:
            self.project_config_dir = Path(project_dir) / ".grass"
        else:
            self.project_config_dir = Path.cwd() / ".grass"

        self.global_config_file = self.global_config_dir / "config.json"
        self.project_config_file = self.project_config_dir / "config.json"

        self._global_config = _NOT_LOADED
        self._project_config = _NOT_LOADED
        self._merged_config = _NOT_LOADED

    def ensure_global_dir(self) -> None:
        """确保全局配置目录存在"""
        self.global_config_dir.mkdir(parents=True, exist_ok=True)
        workflows_dir = self.global_config_dir / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        plugins_dir = self.global_config_dir / "plugins"
        plugins_dir.mkdir(exist_ok=True)

    def ensure_project_dir(self) -> None:
        """确保项目配置目录存在"""
        self.project_config_dir.mkdir(parents=True, exist_ok=True)

    def load_global_config(self) -> GrassFlowConfig:
        """加载全局配置"""
        if self._global_config is not _NOT_LOADED:
            return self._global_config

        self.ensure_global_dir()

        if self.global_config_file.exists():
            try:
                with open(self.global_config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._global_config = GrassFlowConfig(**data)
            except Exception as e:
                logger.warning(f"加载全局配置失败: {e}，使用默认配置")
                self._global_config = GrassFlowConfig()
        else:
            self._global_config = GrassFlowConfig()
            self.save_global_config(self._global_config)

        return self._global_config

    def load_project_config(self) -> Optional[GrassFlowConfig]:
        """加载项目配置"""
        if self._project_config is not _NOT_LOADED:
            return self._project_config

        if self.project_config_file.exists():
            try:
                with open(self.project_config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._project_config = GrassFlowConfig(**data)
            except Exception as e:
                logger.warning(f"加载项目配置失败: {e}")
                self._project_config = None
        else:
            self._project_config = None

        return self._project_config

    def _apply_env_vars(self, config: GrassFlowConfig) -> GrassFlowConfig:
        """Apply env var overrides using recursive config-tree walking.

        Env var format: GRASSFLOW_SECTION_FIELD=value
        Underscores in field names are ambiguous with nesting separators,
        so we walk the config tree level by level, trying longest-prefix match.
        """
        data = copy.deepcopy(config.model_dump())

        for key, value in os.environ.items():
            if not key.startswith(self.ENV_PREFIX):
                continue
            config_key = key[len(self.ENV_PREFIX):].lower()  # e.g. 'provider_openai_options_apikey'
            parts = config_key.split('_')
            if not parts:
                continue

            # Try to walk the config tree matching segments
            current = data
            matched_path: list[str] = []
            remaining = list(parts)
            success = True

            while remaining:
                # Try longest prefix first (greedy match for keys like 'default_model')
                found = False
                for length in range(len(remaining), 0, -1):
                    candidate = '_'.join(remaining[:length])
                    if isinstance(current, dict) and candidate in current:
                        matched_path.append(candidate)
                        next_val = current[candidate]
                        if isinstance(next_val, dict) and remaining[length:]:
                            # More segments remain; descend into nested dict
                            current = next_val
                            remaining = remaining[length:]
                            found = True
                            break
                        elif not remaining[length:]:
                            # Leaf node reached; set value
                            try:
                                parsed = json.loads(value)
                            except (json.JSONDecodeError, ValueError):
                                parsed = value
                            current[candidate] = parsed
                            remaining = remaining[length:]  # consume all matched segments
                            found = True
                            break
                if not found:
                    success = False
                    break

            if not success:
                logger.debug(f"Env var {key} did not match any config path, skipped")

        return GrassFlowConfig(**data)

    def _merge_configs(self, base: GrassFlowConfig, override: GrassFlowConfig) -> GrassFlowConfig:
        """Merge configs, override takes precedence."""
        base_data = copy.deepcopy(base.model_dump())
        override_data = copy.deepcopy(override.model_dump())

        def deep_merge(base: dict, override: dict) -> dict:
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        merged_data = deep_merge(base_data, override_data)
        return GrassFlowConfig(**merged_data)

    def load_config(self) -> GrassFlowConfig:
        """加载并合并配置

        优先级：环境变量 > 项目配置 > 全局配置 > 默认值
        """
        if self._merged_config is not _NOT_LOADED:
            return self._merged_config

        # 加载全局配置
        global_config = self.load_global_config()

        # 加载项目配置
        project_config = self.load_project_config()

        # 合并配置
        if project_config:
            merged = self._merge_configs(global_config, project_config)
        else:
            merged = global_config

        # 应用环境变量
        self._merged_config = self._apply_env_vars(merged)

        return self._merged_config

    def save_global_config(self, config: GrassFlowConfig) -> None:
        """保存全局配置"""
        self.ensure_global_dir()
        with open(self.global_config_file, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
        self._global_config = config
        self._merged_config = _NOT_LOADED   # Invalidate merged cache
        self._project_config = _NOT_LOADED  # Also invalidate project cache to force re-read on next merge

    def save_project_config(self, config: GrassFlowConfig) -> None:
        """保存项目配置"""
        self.ensure_project_dir()
        with open(self.project_config_file, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
        self._project_config = config
        self._merged_config = _NOT_LOADED  # Invalidate merged cache
        self._global_config = _NOT_LOADED  # Also invalidate global cache to force re-read on next merge

    def update_global_config(self, **kwargs) -> GrassFlowConfig:
        """更新全局配置"""
        config = self.load_global_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.save_global_config(config)
        return config

    def update_project_config(self, **kwargs) -> GrassFlowConfig:
        """更新项目配置"""
        config = self.load_project_config() or GrassFlowConfig()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.save_project_config(config)
        return config

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值

        支持点号分隔的嵌套键，例如：llm.default_model
        """
        config = self.load_config()
        keys = key.split(".")

        value = config.model_dump()
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any, scope: str = "global") -> None:
        """设置配置值

        Args:
            key: 配置键（支持点号分隔）
            value: 配置值
            scope: 作用域（global 或 project）
        """
        keys = key.split(".")

        if scope == "global":
            config = self.load_global_config()
        else:
            config = self.load_project_config() or GrassFlowConfig()

        # 转换为字典
        data = config.model_dump()

        # 设置值
        current = data
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

        # 保存
        if scope == "global":
            self.save_global_config(GrassFlowConfig(**data))
        else:
            self.save_project_config(GrassFlowConfig(**data))

    def get_api_key(self, provider: str) -> Optional[str]:
        """获取 API Key"""
        config = self.load_config()
        provider_config = config.provider.get(provider)
        if provider_config:
            return provider_config.options.apiKey
        return None

    def set_api_key(self, provider: str, key: str, scope: str = "global") -> None:
        """设置 API Key"""
        if scope == "global":
            config = self.load_global_config()
        else:
            config = self.load_project_config() or GrassFlowConfig()

        # 获取或创建 provider 配置
        if provider not in config.provider:
            config.provider[provider] = ProviderConfig()

        config.provider[provider].options.apiKey = key

        if scope == "global":
            self.save_global_config(config)
        else:
            self.save_project_config(config)

    def list_configs(self) -> Dict[str, Any]:
        """列出所有配置"""
        return {
            "global": {
                "path": str(self.global_config_file),
                "exists": self.global_config_file.exists(),
                "config": self.load_global_config().model_dump()
            },
            "project": {
                "path": str(self.project_config_file),
                "exists": self.project_config_file.exists(),
                "config": (pc.model_dump() if (pc := self.load_project_config()) is not None else None)
            },
            "merged": self.load_config().model_dump()
        }

    def reset(self, scope: str = "all") -> None:
        """重置配置

        Args:
            scope: 重置范围（all, global, project）
        """
        if scope in ("all", "global"):
            self._global_config = _NOT_LOADED
            if self.global_config_file.exists():
                self.global_config_file.unlink()

        if scope in ("all", "project"):
            self._project_config = _NOT_LOADED
            if self.project_config_file.exists():
                self.project_config_file.unlink()

        self._merged_config = _NOT_LOADED

    @property
    def config(self) -> GrassFlowConfig:
        """获取当前配置"""
        return self.load_config()


# 全局配置管理器实例
config_manager = ConfigManager()
