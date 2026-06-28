"""
GrassFlow 工作流存储

支持：
- 工作流保存为 JSON
- 从 JSON 加载工作流
- 列出已保存的工作流

使用 v2 类型: Workflow (dataclass)
"""

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, List, Optional

from core.models import (
    Workflow, AgentInstance, Connection, Port,
    ModelConfig, MCPConfig, PermissionConfig,
)


class StorageError(Exception):
    """存储相关错误"""
    pass


def _dataclass_to_dict(obj: Any) -> Any:
    """递归将 dataclass 转换为字典"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    elif isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


def _dict_to_workflow(data: dict) -> Workflow:
    """从字典重建 Workflow dataclass"""
    agents = []
    for a in data.get("agents", []):
        agents.append(AgentInstance(
            name=a["name"],
            component=a.get("component"),
            overrides=a.get("overrides", {}),
            inline_ports=[Port(**p) for p in a.get("inline_ports", [])],
            inline_system_prompt=a.get("inline_system_prompt"),
        ))

    connections = []
    for c in data.get("connections", []):
        connections.append(Connection(
            source_agent=c["source_agent"],
            source_port=c.get("source_port"),
            target_agents=c.get("target_agents", []),
            target_ports=c.get("target_ports", []),
            routing_rules=c.get("routing_rules", {}),
        ))

    ports = [Port(**p) for p in data.get("ports", [])]

    return Workflow(
        name=data["name"],
        ports=ports,
        agents=agents,
        connections=connections,
        output_mappings=data.get("output_mappings", {}),
    )


class WorkflowStorage:
    """工作流存储"""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            try:
                from core.config import config_manager
                base_dir = Path(config_manager.get("workflows_dir", "~/.Grass/workflows")).expanduser()
            except Exception:
                base_dir = Path("~/.Grass/workflows").expanduser()

        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, workflow: Workflow, filename: Optional[str] = None) -> Path:
        """
        保存工作流

        Args:
            workflow: 工作流对象 (v2 dataclass)
            filename: 文件名，默认为 {workflow.name}.json

        Returns:
            保存的文件路径
        """
        if filename is None:
            filename = f"{workflow.name}.json"

        filepath = self.base_dir / filename

        data = _dataclass_to_dict(workflow)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        return filepath

    def load(self, filename: str) -> Workflow:
        """
        加载工作流

        Args:
            filename: 文件名

        Returns:
            工作流对象 (v2)

        Raises:
            StorageError: 文件不存在或格式错误
        """
        filepath = self.base_dir / filename

        if not filepath.exists():
            raise StorageError(f"Workflow file not found: {filepath}")

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            return _dict_to_workflow(data)

        except json.JSONDecodeError as e:
            raise StorageError(f"Invalid JSON in {filepath}: {e}")
        except Exception as e:
            raise StorageError(f"Failed to load workflow from {filepath}: {e}")

    def list(self) -> List[str]:
        """列出已保存的工作流"""
        if not self.base_dir.exists():
            return []

        return [f.name for f in self.base_dir.glob("*.json")]

    def delete(self, filename: str) -> None:
        """删除工作流"""
        filepath = self.base_dir / filename

        if not filepath.exists():
            raise StorageError(f"Workflow file not found: {filepath}")

        filepath.unlink()

    def exists(self, filename: str) -> bool:
        """检查工作流是否存在"""
        filepath = self.base_dir / filename
        return filepath.exists()


# 全局存储实例
workflow_storage = WorkflowStorage()
