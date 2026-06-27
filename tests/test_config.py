"""
配置管理模块测试
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from core.config import (
    APIKeys,
    LLMConfig,
    WorkflowConfig,
    DisplayConfig,
    ServerConfig,
    GrassFlowConfig,
    ConfigManager,
)


# ==================== Fixtures ====================

@pytest.fixture
def temp_dir():
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def config_manager(temp_dir):
    """创建配置管理器实例"""
    global_dir = temp_dir / "global"
    project_dir = temp_dir / "project"
    return ConfigManager(config_dir=str(global_dir), project_dir=str(project_dir))


# ==================== 模型测试 ====================

class TestAPIKeys:
    """APIKeys 测试"""

    def test_default_values(self):
        """测试默认值"""
        keys = APIKeys()
        assert keys.openai is None
        assert keys.anthropic is None
        assert keys.deepseek is None
        assert keys.ollama is None

    def test_custom_values(self):
        """测试自定义值"""
        keys = APIKeys(openai="sk-xxx", anthropic="sk-yyy")
        assert keys.openai == "sk-xxx"
        assert keys.anthropic == "sk-yyy"

    def test_extra_fields(self):
        """测试额外字段"""
        keys = APIKeys(custom_key="value")
        assert keys.custom_key == "value"


class TestLLMConfig:
    """LLMConfig 测试"""

    def test_default_values(self):
        """测试默认值"""
        config = LLMConfig()
        assert config.default_model == "deepseek-v4-flash"
        assert config.default_provider == "deepseek"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.timeout == 60
        assert config.retry_count == 3
        assert config.retry_delay == 1.0

    def test_custom_values(self):
        """测试自定义值"""
        config = LLMConfig(default_model="gpt-3.5-turbo", temperature=0.5)
        assert config.default_model == "gpt-3.5-turbo"
        assert config.temperature == 0.5


class TestWorkflowConfig:
    """WorkflowConfig 测试"""

    def test_default_values(self):
        """测试默认值"""
        config = WorkflowConfig()
        assert config.auto_save is True
        assert config.auto_validate is True
        assert config.max_parallel == 10
        assert config.default_on_fail == "stop"
        assert config.execution_timeout == 300


class TestDisplayConfig:
    """DisplayConfig 测试"""

    def test_default_values(self):
        """测试默认值"""
        config = DisplayConfig()
        assert config.theme == "dark"
        assert config.show_timestamps is True
        assert config.show_agent_names is True
        assert config.log_level == "INFO"
        assert config.compact_mode is False


class TestServerConfig:
    """ServerConfig 测试"""

    def test_default_values(self):
        """测试默认值"""
        config = ServerConfig()
        assert config.host == "localhost"
        assert config.port == 8000
        assert config.cors_origins == ["*"]
        assert config.debug is False


class TestGrassFlowConfig:
    """GrassFlowConfig 测试"""

    def test_default_values(self):
        """测试默认值"""
        config = GrassFlowConfig()
        assert config.version == "1.0.0"
        assert isinstance(config.provider, dict)
        assert isinstance(config.llm, LLMConfig)
        assert isinstance(config.workflow, WorkflowConfig)
        assert isinstance(config.display, DisplayConfig)
        assert isinstance(config.server, ServerConfig)
        assert config.workflows_dir == os.path.expanduser("~/.Grass/workflows")
        assert config.db_path == os.path.expanduser("~/.Grass/grassflow.db")
        assert config.plugins_dir == os.path.expanduser("~/.Grass/plugins")

    def test_custom_values(self):
        """测试自定义值"""
        config = GrassFlowConfig(
            version="2.0.0",
            llm=LLMConfig(default_model="gpt-3.5-turbo")
        )
        assert config.version == "2.0.0"
        assert config.llm.default_model == "gpt-3.5-turbo"

    def test_model_dump(self):
        """测试导出为字典"""
        config = GrassFlowConfig()
        data = config.model_dump()
        assert isinstance(data, dict)
        assert "version" in data
        assert "provider" in data
        assert "llm" in data


# ==================== ConfigManager 测试 ====================

class TestConfigManager:
    """ConfigManager 测试"""

    def test_init(self, temp_dir):
        """测试初始化"""
        manager = ConfigManager(
            config_dir=str(temp_dir / "global"),
            project_dir=str(temp_dir / "project")
        )
        assert manager.global_config_dir == temp_dir / "global"
        assert manager.project_config_dir == temp_dir / "project" / ".grass"

    def test_default_dirs(self):
        """测试默认目录"""
        manager = ConfigManager()
        assert manager.global_config_dir == Path.home() / ".Grass"

    def test_ensure_global_dir(self, config_manager):
        """测试创建全局目录"""
        config_manager.ensure_global_dir()
        assert config_manager.global_config_dir.exists()
        assert (config_manager.global_config_dir / "workflows").exists()
        assert (config_manager.global_config_dir / "plugins").exists()

    def test_ensure_project_dir(self, config_manager):
        """测试创建项目目录"""
        config_manager.ensure_project_dir()
        assert config_manager.project_config_dir.exists()

    def test_load_global_config_default(self, config_manager):
        """测试加载默认全局配置"""
        config = config_manager.load_global_config()
        assert isinstance(config, GrassFlowConfig)
        assert config.version == "1.0.0"
        assert config_manager.global_config_file.exists()

    def test_save_and_load_global_config(self, config_manager):
        """测试保存和加载全局配置"""
        config = GrassFlowConfig(version="2.0.0")
        config_manager.save_global_config(config)

        loaded = config_manager.load_global_config()
        assert loaded.version == "2.0.0"

    def test_load_project_config_not_exists(self, config_manager):
        """测试加载不存在的项目配置"""
        config = config_manager.load_project_config()
        assert config is None

    def test_save_and_load_project_config(self, config_manager):
        """测试保存和加载项目配置"""
        config = GrassFlowConfig(version="3.0.0")
        config_manager.save_project_config(config)

        loaded = config_manager.load_project_config()
        assert loaded is not None
        assert loaded.version == "3.0.0"

    def test_merge_configs(self, config_manager):
        """测试配置合并"""
        global_config = GrassFlowConfig(
            version="1.0.0",
            llm=LLMConfig(default_model="gpt-4")
        )
        project_config = GrassFlowConfig(
            llm=LLMConfig(default_model="gpt-3.5-turbo")
        )

        merged = config_manager._merge_configs(global_config, project_config)
        assert merged.version == "1.0.0"  # 来自 global
        assert merged.llm.default_model == "gpt-3.5-turbo"  # 来自 project

    def test_env_vars_override(self, config_manager, monkeypatch):
        """测试环境变量覆盖"""
        monkeypatch.setenv("GRASSFLOW_LLM_DEFAULT_MODEL", "gpt-3.5-turbo")

        config = GrassFlowConfig()
        merged = config_manager._apply_env_vars(config)
        assert merged.llm.default_model == "gpt-3.5-turbo"

    def test_load_config_priority(self, config_manager, monkeypatch):
        """测试配置优先级"""
        # 设置全局配置
        global_config = GrassFlowConfig(
            version="1.0.0",
            llm=LLMConfig(default_model="gpt-4")
        )
        config_manager.save_global_config(global_config)

        # 设置项目配置
        project_config = GrassFlowConfig(
            llm=LLMConfig(default_model="gpt-3.5-turbo")
        )
        config_manager.save_project_config(project_config)

        # 设置环境变量
        monkeypatch.setenv("GRASSFLOW_LLM_DEFAULT_MODEL", "claude-3")

        # 加载合并配置
        merged = config_manager.load_config()
        assert merged.version == "1.0.0"  # 来自 global
        assert merged.llm.default_model == "claude-3"  # 来自 env

    def test_get_nested_key(self, config_manager):
        """测试获取嵌套键"""
        config = GrassFlowConfig(llm=LLMConfig(default_model="gpt-4"))
        config_manager.save_global_config(config)

        value = config_manager.get("llm.default_model")
        assert value == "gpt-4"

    def test_get_nonexistent_key(self, config_manager):
        """测试获取不存在的键"""
        value = config_manager.get("nonexistent", default="default")
        assert value == "default"

    def test_set_nested_key(self, config_manager):
        """测试设置嵌套键"""
        config_manager.set("llm.default_model", "gpt-3.5-turbo", scope="global")

        value = config_manager.get("llm.default_model")
        assert value == "gpt-3.5-turbo"

    def test_get_api_key(self, config_manager):
        """测试获取 API Key"""
        from core.config import ProviderConfig, ProviderOptions
        config = GrassFlowConfig(
            provider={
                "openai": ProviderConfig(
                    options=ProviderOptions(apiKey="sk-xxx")
                )
            }
        )
        config_manager.save_global_config(config)

        key = config_manager.get_api_key("openai")
        assert key == "sk-xxx"

    def test_set_api_key(self, config_manager):
        """测试设置 API Key"""
        config_manager.set_api_key("openai", "sk-yyy", scope="global")

        key = config_manager.get_api_key("openai")
        assert key == "sk-yyy"

    def test_list_configs(self, config_manager):
        """测试列出配置"""
        configs = config_manager.list_configs()
        assert "global" in configs
        assert "project" in configs
        assert "merged" in configs

    def test_reset_global(self, config_manager):
        """测试重置全局配置"""
        config = GrassFlowConfig(version="2.0.0")
        config_manager.save_global_config(config)

        config_manager.reset(scope="global")
        assert not config_manager.global_config_file.exists()

    def test_reset_project(self, config_manager):
        """测试重置项目配置"""
        config = GrassFlowConfig(version="2.0.0")
        config_manager.save_project_config(config)

        config_manager.reset(scope="project")
        assert not config_manager.project_config_file.exists()

    def test_reset_all(self, config_manager):
        """测试重置所有配置"""
        config = GrassFlowConfig(version="2.0.0")
        config_manager.save_global_config(config)
        config_manager.save_project_config(config)

        config_manager.reset(scope="all")
        assert not config_manager.global_config_file.exists()
        assert not config_manager.project_config_file.exists()

    def test_config_cache(self, config_manager):
        """测试配置缓存"""
        config1 = config_manager.load_config()
        config2 = config_manager.load_config()
        assert config1 is config2

    def test_config_cache_invalidated(self, config_manager):
        """测试配置缓存失效"""
        config1 = config_manager.load_config()
        config_manager.save_global_config(GrassFlowConfig(version="2.0.0"))
        config2 = config_manager.load_config()
        assert config1 is not config2


# ==================== 集成测试 ====================

class TestConfigIntegration:
    """配置集成测试"""

    def test_full_workflow(self, temp_dir):
        """测试完整工作流"""
        manager = ConfigManager(
            config_dir=str(temp_dir / "global"),
            project_dir=str(temp_dir / "project")
        )

        # 1. 加载默认配置
        config = manager.load_config()
        assert config.version == "1.0.0"

        # 2. 设置全局配置
        manager.set("llm.default_model", "gpt-4", scope="global")
        manager.set_api_key("openai", "sk-xxx", scope="global")

        # 3. 设置项目配置
        manager.set("llm.default_model", "gpt-3.5-turbo", scope="project")

        # 4. 验证合并结果
        merged = manager.load_config()
        assert merged.llm.default_model == "gpt-3.5-turbo"
        assert manager.get_api_key("openai") == "sk-xxx"

        # 5. 列出配置
        configs = manager.list_configs()
        assert configs["global"]["exists"] is True
        assert configs["project"]["exists"] is True

        # 6. 重置配置
        manager.reset(scope="all")
        assert not manager.global_config_file.exists()
        assert not manager.project_config_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
