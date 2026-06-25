# GrassFlow REPL — 非降级模式 Bug 诊断 v2

> 诊断日期: 2026-06-25
> 诊断范围: 全屏 TUI (prompt_toolkit Application) 模式输入处理链路
> 前提: 确认 prompt_toolkit 可以正常创建 Application（用户环境: PowerShell + Windows Terminal）

---

## 核心发现

### Bug #1 (ROOT CAUSE): `_periodic_refresh` 从未注册 — 全屏 TUI 输入队列永远无人消费

**文件:** `tui/repl.py` 行 1394-1398
**严重性: 致命**

```python
# 注册定期刷新回调
def _periodic_refresh():           # ← 定义了一个回调函数
    """定期处理队列中的消息"""
    self._process_queue()          # ← 这是读取 input_queue 的唯一地方
    if self._should_exit:
        self.app.exit()
```

但是 `_periodic_refresh` **从未被注册到 prompt_toolkit Application**。它只是被定义，然后从未被调用、从未被传入、从未被注册。

### 输入处理完整链路追踪

```
用户输入 "hello" + Enter
  ↓
handle_enter (line 556) → buffer.validate_and_handle()
  ↓
_accept_input (line 664) → self._input_queue.put(text)  # 放入队列
  ↓
self.app.invalidate()     # 触发重绘（但不会调用 _process_queue）
  ↓
✘ _periodic_refresh 未注册 → _process_queue 永远不会被调用
  ↓
✘ 消息停留在 queue.Queue 中 → 用户看不到任何响应
```

### 对比降级模式 (`_run_fallback`)

降级模式在 `_run_fallback` (line 1417+) 中直接使用 `input()` 获取输入并同步调用 `asyncio.run(_consume())` (line 1500) 处理，**不经过** `_input_queue` / `_process_queue` 机制。所以降级模式可以正常工作。

### 结论

非降级模式（全屏 TUI）下，**输入永远停留在 queue.Queue 中无人消费**。这就是为什么用户说"完全没有修复，问题一模一样"的根因。

---

### Bug #2: `_dispatch_command` 中输入队列消费不完整

**文件:** `tui/repl.py` 行 750-795
**严重性: 高**

`_dispatch_command` 是 `_process_entry` → `_process_queue` 调用的，处理斜杠命令。但是在全屏 TUI 模式下，`_process_queue` 本身永远不会被调用（Bug #1）。即使修复了 Bug #1，这里还有另一个问题：

命令处理是同步的、即时的（不需要 Agent Loop），但用户输入仍需要通过 `_input_queue` 才能到达 `_process_entry`。这意味着即使是 `/help` 这种应该立即响应的命令，也需要等待 `_periodic_refresh` 被触发才能处理。

一个更好的设计是：命令可以不经过队列，直接在 `_accept_input` 中处理。

---

### Bug #3: `_process_with_agent_loop` 中跨线程调用 `self.add_output` 不安全

**文件:** `tui/repl.py` 行 811-830
**严重性: 中**

```python
def _process_with_agent_loop(self, text: str) -> None:
    """使用 AgentLoop 异步处理消息"""
    self._agent_running = True

    def _run():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_agent_loop(text))
            loop.close()
        except Exception as e:
            self.add_output(f"Agent error: {e}", role="error")  # ← 在后台线程中
        finally:
            self._agent_running = False
            if self.app:
                self.app.invalidate()                            # ← 在后台线程中

    t = threading.Thread(target=_run, daemon=True)
    t.start()
```

`_async_agent_loop` 在后台线程中运行。在事件处理循环中 (line 846-899)，每次事件后都会调用 `self.app.invalidate()` (line 892)。**prompt_toolkit 的 Application 不是线程安全的**，从非 UI 线程调用 `invalidate()` 可能导致：
- 竞态条件
- 在 Windows 上可能导致崩溃或死锁
- UI 更新可能漏掉或乱序

正确的做法是使用线程安全的队列将 UI 更新传回主线程，或者通过 prompt_toolkit 的 `create_background_task` 机制。

---

### Bug #4: `_async_agent_loop` 中 `error` 事件处理有误

**文件:** `tui/repl.py` 行 884-885
**严重性: 中**

```python
elif etype == "error":
    self.add_output(f"[error] {edata}", role="error")
```

`edata` 是一个 `Dict[str, Any]`，直接传给 f-string 会变成 `{'message': '...'}` 这样的字典字符串表示。应该取 `edata.get("message", str(edata))`。

对比降级模式 (line 1494-1496) 正确处理了：
```python
elif etype == "error":
    msg = edata.get("message", str(edata))
    console.print(f"\n  [bold red][error] {msg}[/bold red]", highlight=False)
```

---

### Bug #5: `_accept_input` 返回 `True` 但含义模糊

**文件:** `tui/repl.py` 行 664-680
**严重性: 低**

```python
def _accept_input(self, buffer: Buffer) -> bool:
    text = buffer.text.strip()
    if not text:
        buffer.reset()
        return True  # 保持输入?

    self._input_queue.put(text)
    buffer.reset()
    if self.app:
        self.app.invalidate()
    return True  # 返回 True 表示已处理
```

`Buffer.accept_handler` 的返回值含义是：返回 `True` 表示输入已被处理，buffer 应被清空；返回 `False` 表示输入无效，保留 buffer 内容。但这里无论何时都返回 `True`，包括空输入时。虽然功能上正确（空输入时也清空），但语义不明确。

---

### Bug #6: `if sys.platform == "win32"` 分支逻辑冗余

**文件:** `tui/repl.py` 行 1401-1408
**严重性: 低**

```python
if sys.platform == "win32":
    self.app.run()
else:
    # Unix: 注册异步刷新
    self.app.run()   # ← 完全相同的调用
```

两个分支执行完全相同的代码。注释说 "Unix: 注册异步刷新" 但实际上没有做任何注册。

---

### Bug #7: `process_streaming` 未传入 system 消息 (已确认仍在)

**文件:** `tui/agent_loop.py` 行 606-626
**严重性: 中**

```python
proto_messages: List[Message] = []
for m in messages:
    msg = Message(
        role=m.get("role", "user"),
        content=m.get("content", ""),
        name=m.get("name"),
        tool_call_id=m.get("tool_call_id"),
    )
    ...
    proto_messages.append(msg)  # 包含 system 消息，由 stream_chat 自动分离

async for event in self._client.stream_chat(
    messages=[{"role": m.role, "content": m.content} for m in proto_messages],
    temperature=0.7,
):
```

注释写 "由 stream_chat 自动分离" — 这是**正确的**。`stream_chat()` 在 `llm_protocol.py` 行 1484-1491 会自己分离 system 消息并传给 `stream_events()` 的 `system` 参数。所以**这个 Bug 已经在 3b3b41a commit 中修复**（之前的版本有 `system_msgs` 被收集但从未传入的 bug，现在改为不对 system 消息做预处理，全部传给 stream_chat 由其自行分离）。

---

### Bug #8: `_call_llm_with_retry` 将 usage 写死为 None (仍在)

**文件:** `tui/agent_loop.py` 行 868-885
**严重性: 中**

```python
response = await self._client.chat(
    messages=chat_messages,
    temperature=0.7,
)

return LLMResponse(
    text=response.content,
    model=response.model,
    usage=Usage(                                      # ← 修复后正确提取了 usage
        prompt_tokens=raw_usage.get("prompt_tokens", 0),
        completion_tokens=raw_usage.get("completion_tokens", 0),
        total_tokens=raw_usage.get("total_tokens", 0),
    ),
    finish_reason=response.finish_reason,
)
```

但注意：这个修复在 agent_loop.py 行 875-882 — 它确实是在 commit 3b3b41a 中修复的。之前的版本 `usage=None`。

不过 `process_streaming` (line 541-760) 中的 `Usage` 使用的是 LLM 流式事件 `LLMEventType.FINISH` 中的 `usage` 数据，而流式路径中目前**没有提取和使用 usage 信息**。所以流式模式下 token 统计永远为 0。

---

### Bug #9: `_process_with_agent_loop` 没有传递会话历史

**文件:** `tui/repl.py` 行 811-830
**严重性: 中**

```python
def _process_with_agent_loop(self, text: str) -> None:
    self._agent_running = True

    def _run():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_agent_loop(text))
            ...
```

而 `_async_agent_loop` 内部会调用 `_build_history()` (line 840) 和 `_get_system_prompt()` (line 843)。这里要注意：`_build_history()` 遍历 `self.output` 列表构建历史。如果 `_process_queue` 从未被调用（Bug #1），那 `_dispatch_message` 就不会被调用，`self.output` 中就不会有用户输入记录。即使修复了 Bug #1，这里有另一个细微问题：

`_process_entry` (line 1273-1293) 对于普通消息会调用 `_dispatch_message`，而 `_dispatch_message` (line 797-809) 先 `self.add_output(text, role="user")`，然后调用 `_process_with_agent_loop`。Agent Loop 在后台线程运行，调用 `_build_history()` 时，当前用户消息已经在 `self.output` 中了（因为在 `add_output` 之后才启动线程）。所以**历史构建是正确的**。

---

## Bug 优先级汇总

| # | 文件 | 行号 | 严重性 | 描述 | 状态 |
|---|------|------|--------|------|------|
| 1 | `tui/repl.py` | 1394-1398 | **致命** | `_periodic_refresh` 定义但从未注册，输入队列无人消费 | 新发现 |
| 2 | `tui/repl.py` | 750-795 | 高 | 命令也需要经过队列，延迟响应 | 新发现 |
| 3 | `tui/repl.py` | 815-830 | 中 | 跨线程调用 `app.invalidate()` 不安全 | 新发现 |
| 4 | `tui/repl.py` | 884-885 | 中 | error 事件直接 f-string 字典 | 新发现 |
| 5 | `tui/repl.py` | 670 | 低 | `_accept_input` 返回值语义模糊 | 已有 |
| 6 | `tui/repl.py` | 1401-1408 | 低 | win32 分支冗余 | 已有 |
| 7 | `tui/agent_loop.py` | 606-626 | ~~中~~ | system 消息未传入 stream_chat | 已修复 |
| 8 | `tui/agent_loop.py` | 868-885 | ~~中~~ | usage=None | 已修复 (非流式路径) |
| 9 | `tui/agent_loop.py` | 541-760 | 中 | process_streaming 未提取 usage 信息 | 新发现 |

---

## 修复方案建议

### 修复 Bug #1 (根因修复)

方案 A — 使用 prompt_toolkit 的 `on_invalidate` 回调：
```python
self.app.on_invalidate += lambda: self._process_queue()
```

方案 B — 使用 asyncio 事件循环 + `create_background_task`：
```python
async def _queue_watcher():
    while not self._should_exit:
        self._process_queue()
        await asyncio.sleep(0.05)

# 在 Application 运行时注册
self.app.create_background_task(_queue_watcher())
```

方案 C — 直接在 `_accept_input` 中同步处理（推荐用于命令）：
```python
def _accept_input(self, buffer: Buffer) -> bool:
    text = buffer.text.strip()
    if not text:
        buffer.reset()
        return True

    buffer.reset()
    # 命令和简单输入可以同步处理
    self._process_entry(text)
    return True
```

**推荐方案:** 结合 A 和 C — 在 `_accept_input` 中直接调用 `_process_entry(text)` 处理输入，同时保留 `on_invalidate` 用于处理 Agent Loop 线程返回的 UI 更新。

### 修复 Bug #3

使用线程安全队列传递 UI 更新：
```python
self._ui_update_queue = queue.Queue()

# 在 Agent Loop 线程中：放入更新
self._ui_update_queue.put(("add_output", {"text": token, "role": "assistant"}))

# 在主线程中：消费更新
def _process_ui_updates():
    try:
        while True:
            action, args = self._ui_update_queue.get_nowait()
            if action == "add_output":
                self.add_output(**args)
            elif action == "invalidate":
                self.app.invalidate()
    except queue.Empty:
        pass
```

---

## 验证方法

修复后可通过以下方式验证非降级模式：
1. 启动 REPL: `python -m tui.repl`
2. 输入 `/help` —— 应看到帮助信息
3. 输入 `你好，介绍一下自己` —— 应看到 AI 的流式回复
4. 检查 UI 是否实时刷新（逐 token 显示）
