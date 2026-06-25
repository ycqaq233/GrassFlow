"""
GrassFlow 配置管理

管理全局配置和 API Key
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class APIKeys(BaseModel):
    """API Keys 配置"""
    openai: Optional[str] = None
    anthropic: Optional[str] = None


class GrassFlowConfig(BaseModel):
    """GrassFlow 全局配置"""
    default_model: str = "gpt-4"
    api_keys: APIKeys = Field(default_factory=APIKeys)
    workflows_dir: str = "~/.grassflow/workflows"
    db_path: str = "~/.grassflow/grassflow.db"


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".grassflow"
        self.config_file = self.config_dir / "config.json"
        self._config: Optional[GrassFlowConfig] = None

    def ensure_config_dir(self) -> None:
        """确保配置目录存在"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        workflows_dir = self.config_dir / "workflows"
        workflows_dir.mkdir(exist_ok=True)

    def load_config(self) -> GrassFlowConfig:
        """加载配置"""
        if self._config:
            return self._config

        self.ensure_config_dir()

        if self.config_file.exists():
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._config = GrassFlowConfig(**data)
        else:
            self._config = GrassFlowConfig()
            self.save_config(self._config)

        return self._config

    def save_config(self, config: GrassFlowConfig) -> None:
        """保存配置"""
        self.ensure_config_dir()
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config.dict(), f, indent=2, ensure_ascii=False)
        self._config = config

    def update_config(self, **kwargs) -> GrassFlowConfig:
        """更新配置"""
        config = self.load_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.save_config(config)
        return config

    def get_api_key(self, provider: str) -> Optional[str]:
        """获取 API Key"""
        config = self.load_config()
        return getattr(config.api_keys, provider, None)

    def set_api_key(self, provider: str, key: str) -> None:
        """设置 API Key"""
        config = self.load_config()
        setattr(config.api_keys, provider, key)
        self.save_config(config)

    @property
    def config(self) -> GrassFlowConfig:
        """获取当前配置"""
        return self.load_config()


# 全局配置管理器实例
config_manager = ConfigManager()
