# GrassFlow REPL — prompt_toolkit TUI 诊断报告

> 诊断日期: 2026-06-25
> 诊断范围: prompt_toolkit Application 配置、AgentLoop 初始化链路、事件流、键盘处理、输出刷新

---

## 1. prompt_toolkit Application 配置

### 文件: `tui/repl.py` 行 1379-1394 — GrassFlowREPL.run()

**结论：配置正确，没有问题。**

```python
self.app = Application(
    layout=self._build_layout(),
    key_bindings=self.kb,
    style=build_pt_style(self._theme),
    full_screen=True,
    mouse_support=True,
    enable_page_navigation_bindings=True,
)
```

- `full_screen=True` — 正确，全屏 TUI 模式
- `mouse_support=True` — Windows Terminal 支持，没问题
- `enable_page_navigation_bindings=True` — 正确，允许 PageUp/PageDown 翻页
- 异常捕获降级也正确：在 catch 块中调用 `_run_fallback()` 是合理的设计

### 文件: `tui/repl.py` 行 1411-1416 — 事件循环

**轻微问题：Windows 和 Unix 走相同的 `self.app.run()` 路径，`if sys.platform == "win32"` 分支没做任何不同的事情。** 这不是 bug，但逻辑冗余。

---

## 2. Bug #1: `_run_fallback` 中 Process 返回事件类型比较不一致

### 文件: `tui/repl.py` 行 1476-1488

**严重性: 高**

降级模式下比较的事件类型不正确：

```python
async for event in self._agent_loop.process_streaming(stripped):
    if event.type in ("text_delta",):       # LoopEventType: TEXT_DELTA
        ...
    elif event.type == "tool_call":          # ← BUG: 应该是 "tool_call_start"
        ...
    elif event.type == "tool_result":        # ← BUG: 应该是 "tool_result"
        ...
```

`process_streaming()` (agent_loop.py) 产生的事件类型是：
- `"text_delta"` (LoopEventType.TEXT_DELTA.value) — 正确
- `"tool_call_start"` (LoopEventType.TOOL_CALL_START.value) — **降级模式写成 `"tool_call"`**
- `"tool_result"` (LoopEventType.TOOL_RESULT.value) — 这个恰好一致，但没处理 `"tool_call_end"` 和 `"tool_call_args"`

**后果**：降级模式下，工具调用的可视化提示永远不会触发。

### 对比 `_async_agent_loop()` (repl.py 行 846-899)

在全屏 TUI 模式下 (`_async_agent_loop`)，事件处理是从 `agent_loop.process()` (非流式版本) 产生的，类型比较是正确的。

但注意：全屏 TUI 用的是 `agent_loop.process()`，而降级模式用的是 `agent_loop.process_streaming()`。这两个方法产生的事件类型不完全相同！

---

## 3. Bug #2: `_async_agent_loop` 与 `_fallback` 使用的 process 方法不一致

### 文件: `tui/repl.py`

| 模式 | 调用的方法 | 事件来源 |
|------|-----------|---------|
| 全屏 TUI (`_async_agent_loop`, 行 846) | `agent_loop.process()` | 非流式，TEXT_DELTA 是一次性返回整段文本 |
| 降级模式 (`_run_fallback`, 行 1476) | `agent_loop.process_streaming()` | 流式，TEXT_DELTA 是逐个 token 返回 |

**严重性: 中**

全屏 TUI 模式没有使用流式 API (`process_streaming`)，而是用的非流式 `process()`。这意味着在全屏 TUI 模式下：
- 用户看不到逐 token 的流式输出
- 只有在 LLM 完成整个响应后才能看到文本（`TEXT_DELTA` 一次性给出全部内容）
- `TEXT_START` 和 `TEXT_END` 事件之间没有增量数据

这完全违背了 TUI 的流式输出设计目标。

### 建议

全屏 TUI 模式应该使用 `agent_loop.process_streaming()` 而非 `agent_loop.process()`。

---

## 4. Bug #3: `_call_llm_with_retry` 总是设置 `usage=None`

### 文件: `tui/agent_loop.py` 行 878-883

**严重性: 中**

```python
return LLMResponse(
    text=response.content,
    model=response.model,
    usage=None,  # ← 写死为 None!
    finish_reason=response.finish_reason,
)
```

虽然 `_LegacyLLMResponse` (llm_protocol.py 行 1518-1524) 有一个 `usage: Dict[str, int]` 字段，但这里传 `usage=None` 进入 `LLMResponse` 的构造。

然后在 `process()` 行 431-433:
```python
if response.usage:   # None 是 falsy，所以这里安全
    self._state.total_input_tokens += response.usage.prompt_tokens or 0
```

虽然有 None 保护，但后果是：**Token 使用统计永远不会被更新**。`_token_count` 在 REPL 状态栏始终为 0。`LLMResponse` 的 `usage` 默认值是 `field(default_factory=Usage)`（llm_protocol.py 行 111），传 `None` 就覆盖了这个默认值。

### 修复方案

应该从 `_LegacyLLMResponse.usage` 字典中提取 usage 信息：

```python
usage = Usage(
    prompt_tokens=response.usage.get("prompt_tokens", 0) if response.usage else 0,
    completion_tokens=response.usage.get("completion_tokens", 0) if response.usage else 0,
    total_tokens=response.usage.get("total_tokens", 0) if response.usage else 0,
)
return LLMResponse(text=..., usage=usage, ...)
```

---

## 5. Bug #4: `process_streaming` 中 system 消息被丢弃

### 文件: `tui/agent_loop.py` 行 605-633

**严重性: 高**

```python
proto_messages: List[Message] = []
system_msgs: List[Message] = []
for m in messages:
    msg = Message(role=m.get("role", "user"), ...)
    ...
    if msg.role == "system":
        system_msgs.append(msg)  # ← 分离出来了
    else:
        proto_messages.append(msg)

async for event in self._client.stream_chat(
    messages=[{"role": m.role, "content": m.content} for m in proto_messages],
    #        ↑ 只传了 proto_messages，system_messages 没有传入！
    temperature=0.7,
):
```

`system_msgs` 被收集但没有传递给 `stream_chat()`。`stream_chat()` 的第二个参数 `system` 未传入，因此 system 消息被静默丢弃。

### 后果

流式模式下，系统提示词不会被传给 LLM。这与 `ProtocolLLMClient.stream_chat()` (llm_protocol.py 行 1471-1504) 的设计一致（它有 `system` 参数处理流程），但调用方没有传入。

对比 `ProtocolLLMClient.chat()` (llm_protocol.py 行 1413-1469) 正确地将 system 消息传给了 `model.make_request()`。

### 修复方案

```python
async for event in self._client.stream_chat(
    messages=[{"role": m.role, "content": m.content} for m in proto_messages],
    system=[{"role": m.role, "content": m.content} for m in system_msgs],
    temperature=0.7,
):
```

或者更简单地，不要分离 system 消息，直接把所有消息（包括 system）放在一起传给 `stream_chat`。

---

## 6. Bug #5: `process_streaming` 中 system 消息传给 LLM 但 `stream_chat` 把它当普通消息处理

### 文件: `core/llm_protocol.py` 行 1471-1498

**严重性: 中**

```python
async def stream_chat(self, messages, ...):
    proto_messages = []
    system_messages = []
    for m in messages:
        if m["role"] == "system":
            system_messages.append(msg)
        else:
            proto_messages.append(msg)

    # 调用 model.stream_events 时传了 system
    async for event in self._model.stream_events(
        messages=proto_messages,
        system=system_messages,   # ← 这里正确传入了
        options=options,
    ):
        yield event
```

这里 `stream_chat` 本身正确地分离并传递 system 消息。但是：
- 如果调用方 (`process_streaming`) 没有传入 system 消息（即 Bug #4），那就没有 system 消息可传
- 如果调用方把所有消息（含 system）放在 `messages` 参数中传入，`stream_chat` 会正确处理

### 结论

`stream_chat` 的行为是正确的。问题是 Bug #4 中调用方没有正确构建 messages。

---

## 7. 键盘/输入处理分析

### 文件: `tui/repl.py` 行 553-661 — `_setup_keybindings()`

**结论：键盘绑定基本正确。**

逐项检查：

| 绑定 | 行号 | 行为 | 评价 |
|------|------|------|------|
| `enter` | 556 | 提交输入 | 正确。APPROVAL 模式和 busy 状态下忽略 |
| `escape,enter` | 569 | Alt+Enter 换行 | 正确。多行输入支持 |
| `c-c` | 575 | 中断 Agent 或退出 | 正确的 eager 模式 |
| `c-d` | 587 | EOF 退出（空输入时） | 正确 |
| `c-l` | 595 | 清屏 | 正确 |
| `c-x` 系列 | 601-643 | 各种操作快捷键 | 正确。类似 Emacs 风格 |
| `tab` | 643 | 补全 | 代码块是空的，但 pt 的 Buffer 自带补全机制，所以没问题 |

### 潜在问题：行 557-559 审批模式下回车被忽略

```python
if self.mode == REPLMode.APPROVAL:
    return
```

审批模式下回车被忽略没有任何反馈。用户可能困惑为什么按回车没反应。这是设计问题而非 bug。

---

## 8. 输出区域刷新分析

### 文件: `tui/repl.py` 行 687-696 — 输出窗口

```python
output_window = Window(
    content=FormattedTextControl(
        text=self._get_output_text,
        focusable=False,
    ),
    wrap_lines=True,
    always_hide_cursor=True,
    scroll_offsets=ScrollOffsets(top=2, bottom=2),
    right_margins=[ScrollbarMargin()],
)
```

**结论：配置正确。**

- `FormattedTextControl` 使用回调函数 `self._get_output_text`，prompt_toolkit 每次渲染都会重新调用
- `wrap_lines=True` — 正确，长文本自动换行
- `always_hide_cursor=True` — 正确，输出区域不需要光标
- `scroll_offsets` — 正确，滚动时有边距
- `ScrollbarMargin()` — 正确，显示滚动条

### 行 849-900 — 事件处理后的 UI 刷新

```python
# 刷新 UI
if self.app:
    self.app.invalidate()
```

**正确。** 每次事件处理后调用 `app.invalidate()` 触发重绘。

### 行 857-862 — 流式 token 追加

```python
if self.output and self.output[-1].role == "assistant":
    self.output[-1].text += token
else:
    self.add_output(token, role="assistant")
```

**正确。** 增量追加到同一条记录，而不是每条新记录，避免了输出区域被大量单 token 行淹没。

---

## 9. AgentLoop 初始化链路分析

### 调用链

```
GrassFlowREPL._init_agent_loop()          # repl.py:1328
  → create_agent_loop_from_config()       # agent_loop.py:979
    → config_manager.load_config()        # config.py:247
    → provider_config.options.apiKey       # config.py, ProviderOptions
    → create_agent_loop(api_key=...)      # agent_loop.py:931
      → ProtocolLLMClient.from_provider() # llm_protocol.py:1381
        → deepseek_provider(api_key=...)  # llm_protocol.py:1300
          → Provider(api_key=...)         # llm_protocol.py:1234
            → _get_configured_route()     # llm_protocol.py:1253
              → Auth.bearer(Credential.of(api_key))
```

### 检查点 1: Config 加载 — `agent_loop.py` 行 1003-1010

```python
provider_config = config.provider.get(provider_name)
if provider_config:
    opts = getattr(provider_config, "options", None)
    if opts:
        api_key = getattr(opts, "apiKey", None) or getattr(opts, "api_key", None)
        base_url = getattr(opts, "baseURL", None) or getattr(opts, "base_url", None)
```

**已修复（之前是 bug）。** 现在同时检查了 camelCase (`apiKey`) 和 snake_case (`api_key`)。

但是注意：如果 `apiKey` 是 `None`，`getattr(opts, "apiKey", None) or getattr(opts, "api_key", None)` 中的 `or` 会正确短路。
但如果 `apiKey` 是空字符串 `""`，`or` 会跳到 `api_key` 检查。这是正确的行为。

### 检查点 2: Provider 构造 — `llm_protocol.py` 行 1300-1311

```python
def deepseek_provider(api_key=None, default_model="deepseek-chat", **kwargs):
    return Provider(
        provider_id="deepseek",
        route=DEEPSEEK_CHAT_ROUTE,
        api_key=api_key,
        default_model=default_model,
    )
```

**正确。** `api_key` 被传递给 `Provider.__init__`，存储在 `self._api_key`，后续在 `_get_configured_route()` 中使用。

### 检查点 3: Route 配置 — `llm_protocol.py` 行 1253-1265

```python
def _get_configured_route(self) -> Route:
    patches = {}
    if self._base_url:
        patches["endpoint"] = self._endpoint.with_base_url(self._base_url)
    if self._api_key:
        patches["auth"] = Auth.bearer(Credential.of(self._api_key))
    self._configured_route = self._route.with_(**patches) if patches else self._route
    return self._configured_route
```

**正确。** API key 被包装成 `Auth.bearer(Credential.of(key))`，在请求时会生成 `Authorization: Bearer sk-xxx` header。

### 检查点 4: HTTP 请求 — `llm_protocol.py` 行 737-769

```python
async def stream_events(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
    prepared = await self.prepare(request)  # 包含 auth.apply()
    ...
    async with session.post(prepared.url, headers=prepared.headers, data=prepared.body) as response:
```

`prepare()` (行 703-735) 正确调用了 `auth.apply()`，将 `Authorization: Bearer ...` header 添加到请求中。

### 结论

**API key 的传递链路在修复后是正确的。** 从配置文件 → `create_agent_loop_from_config()` → `ProtocolLLMClient.from_provider()` → `Provider._get_configured_route()` → HTTP 请求，API key 在每个环节都正确传递。

---

## 10. 流式事件处理 — 降级模式事件类型不匹配汇总

| `process_streaming()` 产出的事件类型 | 全屏 TUI (`_async_agent_loop`) | 降级模式 (`_run_fallback`) |
|--------------------------------------|-------------------------------|---------------------------|
| `loop_start` | 忽略 | 未处理 (正确 — 不需要显示) |
| `loop_end` | 忽略 | 未处理 (正确) |
| `text_start` | 忽略 | 未处理 |
| `text_delta` | 追加 token | `"text_delta"` — 正确 |
| `text_end` | 忽略 | 未处理 |
| `thinking_start` | 显示 `[thinking]` | 未处理 |
| `thinking_delta` | 追加 thinking token | 未处理 |
| `thinking_end` | 显示 `[/thinking]` | 未处理 |
| `tool_call_start` | 显示 `[tool] Calling...` | **写成 `"tool_call"` — 永远不匹配** |
| `tool_call_args` | 追加 args | 未处理 |
| `tool_call_end` | 忽略 | 未处理 |
| `tool_result` | 显示 `[tool result]` | `"tool_result"` — 正确 |
| `error` | 显示 `[error]` | 未处理 |
| `interrupted` | 显示并 break | 未处理 |
| `usage` | 更新 token 统计 | 未处理 |

**降级模式的事件覆盖严重不足。**

---

## 总结：所有发现的 Bug

| # | 文件 | 行号 | 严重性 | 描述 |
|---|------|------|--------|------|
| 1 | `tui/repl.py` | 1481 | **高** | 降级模式 `"tool_call"` 应为 `"tool_call_start"`，工具调用提示永不触发 |
| 2 | `tui/repl.py` | 846 | **中** | 全屏 TUI 使用非流式 `process()` 而非 `process_streaming()`，用户看不到逐 token 输出 |
| 3 | `tui/agent_loop.py` | 881 | **中** | `_call_llm_with_retry` 将 `usage` 写死为 `None`，Token 统计永远不更新 |
| 4 | `tui/agent_loop.py` | 627-633 | **高** | `process_streaming` 收集了 `system_msgs` 但没有传给 `stream_chat()`，系统提示词被丢弃 |
| 5 | `tui/repl.py` | 1476-1488 | **中** | 降级模式事件处理不完整，缺失 8 种事件类型的处理（thinking, tool_call_end, error 等） |
| 6 | `tui/repl.py` | 1412-1414 | 低 | `if sys.platform == "win32"` 分支与 else 分支完全相同，逻辑冗余 |
