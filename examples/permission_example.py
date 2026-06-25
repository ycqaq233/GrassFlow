"""
GrassFlow 权限控制系统使用示例

演示如何使用权限控制系统来管理 Agent 的权限。
"""

import asyncio
from core.permission import (
    PermissionAction,
    PermissionRule,
    PermissionRequest,
    PermissionService,
    Permissions,
    ReplyAction,
    create_permission_service,
)


async def example_basic_usage():
    """基本使用示例"""
    print("=== 基本使用示例 ===")

    # 创建权限服务
    service = create_permission_service(
        config={
            "read_file": "allow",
            "write_file": {
                "/tmp/*": "allow",
            },
        },
        use_defaults=False,
    )

    # 测试 read_file（应该是 allow）
    print("\n1. 测试 read_file（allow）:")
    await service.ask("read_file", ["/any/path/file.txt"])
    print("   ✓ 允许读取文件")

    # 测试 write_file /tmp/*（应该是 allow）
    print("\n2. 测试 write_file /tmp/*（allow）:")
    await service.ask("write_file", ["/tmp/test.txt"])
    print("   ✓ 允许写入 /tmp 目录")

    # 测试 write_file /home/*（应该是 ask）
    print("\n3. 测试 write_file /home/*（ask）:")
    print("   需要用户确认...")


async def example_user_interaction():
    """用户交互示例"""
    print("\n=== 用户交互示例 ===")

    service = create_permission_service(use_defaults=False)

    # 设置用户交互回调
    async def on_ask(request: PermissionRequest):
        print(f"\n   权限请求: {request.permission}")
        print(f"   模式: {request.patterns}")
        print(f"   工具: {request.tool}")

        # 模拟用户选择
        user_choice = "once"  # 可以是 "once", "always", "reject"

        if user_choice == "once":
            print("   用户选择: 仅本次允许")
            await service.reply(request.id, ReplyAction.ONCE)
        elif user_choice == "always":
            print("   用户选择: 总是允许")
            await service.reply(request.id, ReplyAction.ALWAYS)
        else:
            print("   用户选择: 拒绝")
            await service.reply(request.id, ReplyAction.REJECT)

    service._on_ask = lambda req: asyncio.ensure_future(on_ask(req))

    # 测试需要用户确认的权限
    print("\n1. 测试 execute_command（需要用户确认）:")
    try:
        await service.ask("execute_command", ["ls -la"])
        print("   ✓ 命令执行已授权")
    except Exception as e:
        print(f"   ✗ 权限被拒绝: {e}")


async def example_permission_evaluation():
    """权限评估示例"""
    print("\n=== 权限评估示例 ===")

    # 创建自定义规则集
    ruleset = [
        PermissionRule(permission="read_file", pattern="*.txt", action=PermissionAction.ALLOW),
        PermissionRule(permission="read_file", pattern="*.py", action=PermissionAction.ALLOW),
        PermissionRule(permission="read_file", pattern="*.env", action=PermissionAction.DENY),
        PermissionRule(permission="write_file", pattern="*", action=PermissionAction.ASK),
    ]

    service = create_permission_service(use_defaults=False)
    service._approved = ruleset

    # 测试不同的权限请求
    test_cases = [
        ("read_file", "file.txt", "读取文本文件"),
        ("read_file", "script.py", "读取 Python 文件"),
        ("read_file", ".env", "读取环境变量文件"),
        ("write_file", "output.txt", "写入文件"),
    ]

    for permission, pattern, description in test_cases:
        rule = service.evaluate(permission, pattern)
        print(f"\n{description}:")
        print(f"  权限: {permission}")
        print(f"  模式: {pattern}")
        print(f"  结果: {rule.action.value}")


async def example_config_loading():
    """配置加载示例"""
    print("\n=== 配置加载示例 ===")

    # 从配置创建服务
    config = {
        "read_file": "allow",
        "write_file": {
            "/tmp/*": "allow",
            "/home/*": "ask",
        },
        "execute_command": "deny",
        "delete_file": "ask",
    }

    service = create_permission_service(config=config, use_defaults=False)

    print("已加载配置:")
    for rule in service._approved:
        print(f"  - {rule.permission} ({rule.pattern}): {rule.action.value}")

    # 导出配置
    exported_config = service.to_config()
    print("\n导出的配置:")
    print(exported_config)


async def main():
    """主函数"""
    print("GrassFlow 权限控制系统示例")
    print("=" * 50)

    await example_basic_usage()
    await example_user_interaction()
    await example_permission_evaluation()
    await example_config_loading()

    print("\n" + "=" * 50)
    print("示例完成")


if __name__ == "__main__":
    asyncio.run(main())
