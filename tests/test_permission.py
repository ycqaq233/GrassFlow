"""
GrassFlow 权限控制系统测试
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from core.permission import (
    PermissionAction,
    PermissionRuleDeniedError,
    PermissionRequestNotFoundError,
    PermissionUserRejectedError,
    PermissionRequest,
    PermissionRule,
    PermissionService,
    Permissions,
    ReplyAction,
    Ruleset,
    create_permission_service,
    evaluate,
    from_config,
    wildcard_match,
)


class TestWildcardMatch:
    """通配符匹配测试"""

    def test_exact_match(self):
        assert wildcard_match("hello", "hello") is True
        assert wildcard_match("hello", "world") is False

    def test_wildcard_star(self):
        assert wildcard_match("hello", "*") is True
        assert wildcard_match("hello", "h*") is True
        assert wildcard_match("hello", "*o") is True
        assert wildcard_match("hello", "h*o") is True
        assert wildcard_match("hello", "w*") is False

    def test_wildcard_question(self):
        assert wildcard_match("hello", "h?llo") is True
        assert wildcard_match("hello", "?ello") is True
        assert wildcard_match("hello", "hell?") is True
        assert wildcard_match("hello", "h?l?o") is True
        assert wildcard_match("hello", "?????") is True
        assert wildcard_match("hello", "????") is False

    def test_wildcard_brackets(self):
        assert wildcard_match("apple", "[aeiou]*") is True
        assert wildcard_match("world", "[aeiou]*") is False
        assert wildcard_match("hello", "h[aeiou]llo") is True
        assert wildcard_match("hello", "h[xyz]llo") is False

    def test_wildcard_negation(self):
        assert wildcard_match("hello", "h[!xyz]llo") is True
        assert wildcard_match("hello", "h[!aeiou]llo") is False

    def test_path_patterns(self):
        assert wildcard_match("/home/user/file.txt", "/home/user/*") is True
        assert wildcard_match("/home/user/file.txt", "/home/*") is True
        assert wildcard_match("/home/user/file.txt", "/*") is True
        assert wildcard_match("/home/user/file.txt", "/home/other/*") is False


class TestEvaluate:
    """权限评估测试"""

    def test_empty_ruleset(self):
        rule = evaluate("read_file", "/path/to/file")
        assert rule.action == PermissionAction.ASK
        assert rule.permission == "read_file"

    def test_simple_match(self):
        ruleset: Ruleset = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]
        rule = evaluate("read_file", "/path/to/file", ruleset)
        assert rule.action == PermissionAction.ALLOW

    def test_specific_pattern(self):
        ruleset: Ruleset = [
            PermissionRule(permission="read_file", pattern="*.txt", action=PermissionAction.ALLOW),
            PermissionRule(permission="read_file", pattern="*.py", action=PermissionAction.DENY),
        ]
        # 匹配 *.txt 模式
        rule = evaluate("read_file", "file.txt", ruleset)
        assert rule.action == PermissionAction.ALLOW

        # 匹配 *.py 模式
        rule = evaluate("read_file", "file.py", ruleset)
        assert rule.action == PermissionAction.DENY

        # 不匹配任何特定模式，默认返回 ask
        rule = evaluate("read_file", "file.md", ruleset)
        assert rule.action == PermissionAction.ASK

    def test_last_match_wins(self):
        ruleset: Ruleset = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.DENY),
        ]
        rule = evaluate("read_file", "/path/to/file", ruleset)
        assert rule.action == PermissionAction.DENY

    def test_multiple_rulesets(self):
        ruleset1: Ruleset = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]
        ruleset2: Ruleset = [
            PermissionRule(permission="read_file", pattern="/etc/*", action=PermissionAction.DENY),
        ]

        # 匹配第一个规则集
        rule = evaluate("read_file", "/home/user/file.txt", ruleset1, ruleset2)
        assert rule.action == PermissionAction.ALLOW

        # 匹配第二个规则集（优先级更高）
        rule = evaluate("read_file", "/etc/passwd", ruleset1, ruleset2)
        assert rule.action == PermissionAction.DENY

    def test_different_permission(self):
        ruleset: Ruleset = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]
        rule = evaluate("write_file", "/path/to/file", ruleset)
        assert rule.action == PermissionAction.ASK


class TestFromConfig:
    """从配置创建规则集测试"""

    def test_simple_config(self):
        config = {
            "read_file": "allow",
            "write_file": "ask",
            "delete_file": "deny",
        }
        ruleset = from_config(config)
        assert len(ruleset) == 3

        # 检查规则
        read_rule = next(r for r in ruleset if r.permission == "read_file")
        assert read_rule.pattern == "*"
        assert read_rule.action == PermissionAction.ALLOW

        write_rule = next(r for r in ruleset if r.permission == "write_file")
        assert write_rule.pattern == "*"
        assert write_rule.action == PermissionAction.ASK

        delete_rule = next(r for r in ruleset if r.permission == "delete_file")
        assert delete_rule.pattern == "*"
        assert delete_rule.action == PermissionAction.DENY

    def test_detailed_config(self):
        config = {
            "read_file": {
                "/home/*": "allow",
                "/etc/*": "deny",
            },
            "write_file": {
                "/tmp/*": "allow",
            },
        }
        ruleset = from_config(config)
        assert len(ruleset) == 3

        # 检查规则
        home_rule = next(
            r for r in ruleset
            if r.permission == "read_file" and r.pattern == "/home/*"
        )
        assert home_rule.action == PermissionAction.ALLOW

        etc_rule = next(
            r for r in ruleset
            if r.permission == "read_file" and r.pattern == "/etc/*"
        )
        assert etc_rule.action == PermissionAction.DENY

        tmp_rule = next(
            r for r in ruleset
            if r.permission == "write_file" and r.pattern == "/tmp/*"
        )
        assert tmp_rule.action == PermissionAction.ALLOW

    def test_mixed_config(self):
        config = {
            "read_file": "allow",
            "write_file": {
                "/tmp/*": "allow",
                "*": "ask",
            },
        }
        ruleset = from_config(config)
        assert len(ruleset) == 3


class TestPermissionService:
    """权限服务测试"""

    def test_init(self):
        service = PermissionService()
        assert len(service._pending) == 0
        assert len(service._approved) == 0

    def test_evaluate(self):
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]
        rule = service.evaluate("read_file", "/path/to/file")
        assert rule.action == PermissionAction.ALLOW

    @pytest.mark.asyncio
    async def test_ask_allowed(self):
        """测试无需询问的情况（所有 pattern 都是 allow）"""
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]

        # 不应该抛出异常，因为所有 pattern 都是 allow
        await service.ask("read_file", ["/path/to/file"])
        assert len(service._pending) == 0

    @pytest.mark.asyncio
    async def test_ask_denied(self):
        """测试权限被拒绝的情况"""
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.DENY),
        ]

        with pytest.raises(PermissionRuleDeniedError) as exc_info:
            await service.ask("read_file", ["/path/to/file"])

        assert exc_info.value.permission == "read_file"
        assert exc_info.value.pattern == "/path/to/file"

    @pytest.mark.asyncio
    async def test_ask_user_once(self):
        """测试用户回复 once 的情况"""
        service = PermissionService()

        # 设置回调，在被调用时自动回复
        async def auto_reply(request: PermissionRequest):
            await service.reply(request.id, ReplyAction.ONCE)

        service._on_ask = lambda req: asyncio.ensure_future(auto_reply(req))

        # 应该成功，因为用户回复了 once
        await service.ask("read_file", ["/path/to/file"])
        assert len(service._pending) == 0
        assert len(service._approved) == 0  # once 不会添加到 approved

    @pytest.mark.asyncio
    async def test_ask_user_always(self):
        """测试用户回复 always 的情况"""
        service = PermissionService()

        # 设置回调，在被调用时自动回复
        async def auto_reply(request: PermissionRequest):
            await service.reply(request.id, ReplyAction.ALWAYS)

        service._on_ask = lambda req: asyncio.ensure_future(auto_reply(req))

        # 应该成功，因为用户回复了 always
        await service.ask("read_file", ["/path/to/file"])
        assert len(service._pending) == 0
        assert len(service._approved) == 1  # always 会添加到 approved

        # 验证规则已添加
        rule = service._approved[0]
        assert rule.permission == "read_file"
        assert rule.pattern == "/path/to/file"
        assert rule.action == PermissionAction.ALLOW

    @pytest.mark.asyncio
    async def test_ask_user_reject(self):
        """测试用户拒绝的情况"""
        service = PermissionService()

        # 设置回调，在被调用时自动回复
        async def auto_reply(request: PermissionRequest):
            await service.reply(request.id, ReplyAction.REJECT)

        service._on_ask = lambda req: asyncio.ensure_future(auto_reply(req))

        with pytest.raises(PermissionUserRejectedError):
            await service.ask("read_file", ["/path/to/file"])

        assert len(service._pending) == 0

    @pytest.mark.asyncio
    async def test_reply_not_found(self):
        """测试回复不存在的请求"""
        service = PermissionService()

        with pytest.raises(PermissionRequestNotFoundError):
            await service.reply("non-existent-id", ReplyAction.ONCE)

    @pytest.mark.asyncio
    async def test_list_pending(self):
        """测试列出待处理请求"""
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ASK),
        ]

        # 模拟一个 pending 请求
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        request = PermissionRequest(
            id="test-id",
            permission="read_file",
            patterns=["/path/to/file"],
        )
        from core.permission import PendingEntry
        service._pending["test-id"] = PendingEntry(request=request, future=future)

        pending = service.list_pending()
        assert len(pending) == 1
        assert pending[0].id == "test-id"

        # 清理
        future.set_result(None)

    @pytest.mark.asyncio
    async def test_auto_approve_pending(self):
        """测试自动批准匹配的 pending 请求"""
        service = PermissionService()

        # 创建两个 pending 请求
        loop = asyncio.get_event_loop()
        future1 = loop.create_future()
        future2 = loop.create_future()

        request1 = PermissionRequest(
            id="test-id-1",
            permission="read_file",
            patterns=["*"],  # 使用通配符模式
        )
        request2 = PermissionRequest(
            id="test-id-2",
            permission="read_file",
            patterns=["*"],  # 使用通配符模式
        )

        from core.permission import PendingEntry
        service._pending["test-id-1"] = PendingEntry(request=request1, future=future1)
        service._pending["test-id-2"] = PendingEntry(request=request2, future=future2)

        # 设置回调，在被调用时自动回复 always
        async def auto_reply(request: PermissionRequest):
            await service.reply(request.id, ReplyAction.ALWAYS)

        service._on_ask = lambda req: asyncio.ensure_future(auto_reply(req))

        # 批准第一个请求
        await service.reply("test-id-1", ReplyAction.ALWAYS)

        # 第一个请求应该被批准
        assert future1.done()
        assert not future1.cancelled()

        # 第二个请求也应该被自动批准（因为 read_file 的 pattern 是 *，会匹配所有）
        assert future2.done()
        assert not future2.cancelled()

    def test_get_approved_rules(self):
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]

        rules = service.get_approved_rules()
        assert len(rules) == 1
        assert rules[0].permission == "read_file"

        # 修改返回的列表不应该影响内部状态
        rules.clear()
        assert len(service._approved) == 1

    def test_clear_approved(self):
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
        ]

        service.clear_approved()
        assert len(service._approved) == 0

    def test_add_approved_rule(self):
        service = PermissionService()
        rule = PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW)

        service.add_approved_rule(rule)
        assert len(service._approved) == 1
        assert service._approved[0] == rule

    def test_from_config(self):
        service = PermissionService()
        config = {
            "read_file": "allow",
            "write_file": {
                "/tmp/*": "allow",
            },
        }

        service.from_config(config)
        assert len(service._approved) == 2

    def test_to_config(self):
        service = PermissionService()
        service._approved = [
            PermissionRule(permission="read_file", pattern="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="write_file", pattern="/tmp/*", action=PermissionAction.ALLOW),
        ]

        config = service.to_config()
        assert config == {
            "read_file": {"*": "allow"},
            "write_file": {"/tmp/*": "allow"},
        }


class TestCreatePermissionService:
    """创建权限服务测试"""

    def test_default_service(self):
        service = create_permission_service()
        assert len(service._approved) > 0  # 应该有默认规则

    def test_no_defaults(self):
        service = create_permission_service(use_defaults=False)
        assert len(service._approved) == 0

    def test_with_config(self):
        config = {
            "read_file": "deny",
        }
        service = create_permission_service(config=config, use_defaults=False)
        assert len(service._approved) == 1
        assert service._approved[0].action == PermissionAction.DENY

    def test_with_on_ask(self):
        on_ask = MagicMock()
        service = create_permission_service(on_ask=on_ask)
        assert service._on_ask == on_ask


class TestPermissions:
    """权限常量测试"""

    def test_file_permissions(self):
        assert Permissions.READ_FILE == "read_file"
        assert Permissions.WRITE_FILE == "write_file"
        assert Permissions.EDIT_FILE == "edit_file"
        assert Permissions.DELETE_FILE == "delete_file"

    def test_command_permissions(self):
        assert Permissions.EXECUTE_COMMAND == "execute_command"

    def test_agent_permissions(self):
        assert Permissions.CALL_LLM == "call_llm"
        assert Permissions.CALL_TOOL == "call_tool"
        assert Permissions.ACCESS_MCP == "access_mcp"

    def test_workflow_permissions(self):
        assert Permissions.CREATE_WORKFLOW == "create_workflow"
        assert Permissions.RUN_WORKFLOW == "run_workflow"
        assert Permissions.DELETE_WORKFLOW == "delete_workflow"


class TestPermissionRule:
    """权限规则测试"""

    def test_to_dict(self):
        rule = PermissionRule(
            permission="read_file",
            pattern="/home/*",
            action=PermissionAction.ALLOW,
        )
        expected = {
            "permission": "read_file",
            "pattern": "/home/*",
            "action": "allow",
        }
        assert rule.to_dict() == expected

    def test_from_dict(self):
        data = {
            "permission": "read_file",
            "pattern": "/home/*",
            "action": "allow",
        }
        rule = PermissionRule.from_dict(data)
        assert rule.permission == "read_file"
        assert rule.pattern == "/home/*"
        assert rule.action == PermissionAction.ALLOW

    def test_default_values(self):
        rule = PermissionRule(permission="read_file")
        assert rule.pattern == "*"
        assert rule.action == PermissionAction.ASK


class TestPermissionRequest:
    """权限请求测试"""

    def test_to_dict(self):
        request = PermissionRequest(
            id="test-id",
            permission="read_file",
            patterns=["/path/to/file"],
            metadata={"key": "value"},
            tool="test_tool",
        )
        expected = {
            "id": "test-id",
            "permission": "read_file",
            "patterns": ["/path/to/file"],
            "metadata": {"key": "value"},
            "tool": "test_tool",
        }
        assert request.to_dict() == expected

    def test_default_values(self):
        request = PermissionRequest(
            id="test-id",
            permission="read_file",
            patterns=["/path/to/file"],
        )
        assert request.metadata == {}
        assert request.tool is None


class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """测试完整的权限工作流"""
        # 创建服务
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
        await service.ask("read_file", ["/any/path"])
        assert len(service._pending) == 0

        # 测试 write_file /tmp/*（应该是 allow）
        await service.ask("write_file", ["/tmp/test.txt"])
        assert len(service._pending) == 0

        # 测试 write_file /home/*（应该是 ask）
        replies = []

        async def on_ask(request: PermissionRequest):
            replies.append(request.id)
            await service.reply(request.id, ReplyAction.ALWAYS)

        service._on_ask = lambda req: asyncio.ensure_future(on_ask(req))

        await service.ask("write_file", ["/home/user/test.txt"])
        assert len(replies) == 1
        assert len(service._approved) == 3  # 原来 2 个 + 新增 1 个

    @pytest.mark.asyncio
    async def test_multiple_patterns(self):
        """测试多个 pattern 的权限请求"""
        service = create_permission_service(use_defaults=False)

        # 设置回调
        replies = []

        async def on_ask(request: PermissionRequest):
            replies.append(request.id)
            await service.reply(request.id, ReplyAction.ONCE)

        service._on_ask = lambda req: asyncio.ensure_future(on_ask(req))

        # 请求多个 pattern
        await service.ask("read_file", ["/path1", "/path2", "/path3"])
        assert len(replies) == 1  # 应该只询问一次

    @pytest.mark.asyncio
    async def test_mixed_permissions(self):
        """测试混合权限（部分 allow，部分 ask）"""
        service = create_permission_service(
            config={
                "read_file": {
                    "/home/*": "allow",
                },
            },
            use_defaults=False,
        )

        replies = []

        async def on_ask(request: PermissionRequest):
            replies.append(request.id)
            await service.reply(request.id, ReplyAction.ONCE)

        service._on_ask = lambda req: asyncio.ensure_future(on_ask(req))

        # 请求匹配 /home/* 的 pattern（应该是 allow）
        await service.ask("read_file", ["/home/user/file.txt"])
        assert len(replies) == 0

        # 请求不匹配的 pattern（应该是 ask）
        await service.ask("read_file", ["/etc/passwd"])
        assert len(replies) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
