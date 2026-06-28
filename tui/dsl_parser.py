"""
GrassFlow DSL 解析器入口

兼容旧版 import 路径。实际解析使用 dsl_parser_v2。
"""

from tui.dsl_parser_v2 import DSLv2Parser, DSLError
from core.models import Workflow

# 兼容旧版名称
DSLParser = DSLv2Parser


def parse_file(filepath: str) -> Workflow:
    """
    解析 .gf / .af 文件为 v2 Workflow

    Args:
        filepath: 工作流文件路径

    Returns:
        Workflow 对象

    Raises:
        DSLError: 解析错误
        FileNotFoundError: 文件不存在
    """
    from pathlib import Path

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    parser = DSLv2Parser()
    result = parser.parse(content)

    if result.errors:
        raise DSLError(f"Parse errors: {result.errors}")

    if not result.workflows:
        raise DSLError(f"No workflow found in {filepath}")

    return result.workflows[0]


def parse_dsl(dsl_text: str) -> Workflow:
    """
    解析 DSL 文本为 v2 Workflow

    Args:
        dsl_text: DSL 文本内容

    Returns:
        Workflow 对象
    """
    parser = DSLv2Parser()
    result = parser.parse(dsl_text)

    if result.errors:
        raise DSLError(f"Parse errors: {result.errors}")

    if not result.workflows:
        raise DSLError("No workflow found in DSL text")

    return result.workflows[0]
