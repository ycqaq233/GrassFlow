"""
GrassFlow 工作流存储

支持：
- 工作流保存为 JSON
- 从 JSON 加载工作流
- 列出已保存的工作流
"""

import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from core.models import Workflow


class StorageError(Exception):
    """存储相关错误"""
    pass


class WorkflowStorage:
    """工作流存储"""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        初始化存储

        Args:
            base_dir: 基础目录，默认为 ~/.Grass/workflows
        """
        if base_dir is None:
            # 延迟导入避免循环依赖
            from core.config import config_manager
            base_dir = Path(config_manager.get("workflows_dir", "~/.Grass/workflows")).expanduser()

        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, workflow: Workflow, filename: Optional[str] = None) -> Path:
        """
        保存工作流

        Args:
            workflow: 工作流对象
            filename: 文件名，默认为 {workflow.name}.json

        Returns:
            保存的文件路径
        """
        if filename is None:
            filename = f"{workflow.name}.json"

        filepath = self.base_dir / filename

        # 更新时间戳
        workflow.updated_at = datetime.now()

        # 转换为字典
        data = workflow.model_dump()

        # 保存为 JSON
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        return filepath

    def load(self, filename: str) -> Workflow:
        """
        加载工作流

        Args:
            filename: 文件名

        Returns:
            工作流对象

        Raises:
            StorageError: 文件不存在或格式错误
        """
        filepath = self.base_dir / filename

        if not filepath.exists():
            raise StorageError(f"Workflow file not found: {filepath}")

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            return Workflow(**data)

        except json.JSONDecodeError as e:
            raise StorageError(f"Invalid JSON in {filepath}: {e}")
        except Exception as e:
            raise StorageError(f"Failed to load workflow from {filepath}: {e}")

    def list(self) -> List[str]:
        """
        列出已保存的工作流

        Returns:
            工作流文件名列表
        """
        if not self.base_dir.exists():
            return []

        return [f.name for f in self.base_dir.glob("*.json")]

    def delete(self, filename: str) -> None:
        """
        删除工作流

        Args:
            filename: 文件名

        Raises:
            StorageError: 文件不存在
        """
        filepath = self.base_dir / filename

        if not filepath.exists():
            raise StorageError(f"Workflow file not found: {filepath}")

        filepath.unlink()

    def exists(self, filename: str) -> bool:
        """
        检查工作流是否存在

        Args:
            filename: 文件名

        Returns:
            如果存在返回 True，否则返回 False
        """
        filepath = self.base_dir / filename
        return filepath.exists()


# 全局存储实例
workflow_storage = WorkflowStorage()
