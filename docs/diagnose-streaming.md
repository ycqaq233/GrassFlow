# 全屏 TUI 模式流式输出诊断报告

> 诊断时间: 2026-06-25
> 诊断对象: `tui/repl.py` — GrassFlowREPL 全屏模式（prompt_toolkit Application）
> 对比参考: `tui/repl.py` — `_run_fallback` 降级模式（input() + Rich）

---

## 1. 问题描述

非降级模式（prompt_toolkit 全屏 TUI）下，用户输入消息后，Agent Loop 的流式 token **不出现在输出区域**。消息发送成功后，输出区域没有任何增量更新，只有等 Agent Loop 完全结束时才能看到完整文本（或根本没有）。

降级模式（`_run_fallback`）一切正常，流式 token 逐个打印到终端。

---

## 2. 代码路径追踪

### 2.1 完整调用链（全屏模式）

```
用户输入 "你好" + Enter
  → handle_enter (line 559) — key binding
    → buffer.validate_and_handle()
      → _accept_input (line 666) — Buffer.accept_handler
        → buffer.reset()         ← 清空输入 buffer
        → self._process_entry(text) (line 676)
          → _dispatch_message (line 794)
            → self.add_output(text, role="user")    ← 主线程，直接修改 self.output
            → self._process_with_agent_loop(text)   ← 启动后台线程
              → threading.Thread(target=_run).start()
                → loop = asyncio.new_event_loop()
                → loop.run_until_complete(_async_agent_loop(text))
                  → async for event in agent_loop.process_streaming(...)
                    → self._ui_update_queue.put(("text_delta", {"text": token}))
                    → self._ui_update_queue.put(("invalidate", {}))
              线程继续运行...
    → return True  ← 控制权交还 prompt_toolkit

... prompt_toolkit Application 主循环 ...
  → 等待事件（键盘输入 / timeout / signal）
  → 需要重绘时: on_invalidate 触发
    → _process_ui_updates_from_agent() (line 1447)
      → self._process_ui_updates()  ← 从 _ui_update_queue 消费
        → self.output[-1].text += token  ← 主线程
        → self.app.invalidate()          ← 请求下次重绘
  → 渲染: _get_output_text() 读取 self.output 生成 FormattedText
```

### 2.2 降级模式调用链（正常工作的参考）

```
用户输入 "你好" + Enter
  → input(PROMPT) 返回
  → 主线程同步处理:
    → asyncio.run(_consume())
      → async for event in self._agent_loop.process_streaming(stripped)
        → console.print(token, end="", highlight=False)  ← 直接打印到终端！
  → 循环继续，等待下一个 input()
```

---

## 3. 根因分析

### 根因 1（主因）: `on_invalidate` 只在渲染前触发，不会因队列有数据而触发

这是**核心问题**。prompt_toolkit 的 `on_invalidate` 是一个事件钩子，它在 Application 决定需要**重新渲染**之前被调用。但 Application **只在以下情况决定重绘**：

1. 用户按键输入
2. 定时器到期（如果有 `set_timeout` / `set_interval`）
3. 窗口大小变化（SIGWINCH）
4. 显式调用 `app.invalidate()` —— 但这必须从**主线程**调用才安全

在 `_process_with_agent_loop` 中：
- 后台线程向 `_ui_update_queue` put 数据
- 后台线程**不能**安全调用 `app.invalidate()`（prompt_toolkit 不是线程安全的）
- 所以数据进入队列后，**没有任何机制通知主线程来消费它**

结果是：用户输入后，`app.run()` 进入等待键盘输入的状态。后台线程不断向队列 put token，但主线程在 `await` 键盘输入，不会触发 `on_invalidate`，因此 `_process_ui_updates()` 永远不会被调用。

**唯一的例外**：如果用户不断按键（触发渲染），或者 Agent Loop 完成后 `_agent_running = False` 触发某种重绘，token 才会被显示。

### 根因 2: `_accept_input` 返回后缺少 invalidate

在 `_accept_input` (line 666-677) 中：
```python
def _accept_input(self, buffer: Buffer) -> bool:
    text = buffer.text.strip()
    if not text:
        buffer.reset()
        return True
    buffer.reset()
    self._process_entry(text)
    return True  # 返回 True
```

`_process_entry` 调用 `add_output(text, role="user")` 修改了 `self.output` 列表。但返回 `True` 后，prompt_toolkit 会自行处理 buffer 的重置，**不一定会立即触发重绘**。用户消息添加到了 `self.output` 但界面可能还没刷新。

### 根因 3: 后台线程调用 `app.invalidate()` 的竞态条件

即使在 `_process_ui_updates` (line 1320-1321) 中调用了 `self.app.invalidate()`，这个调用**在正确时机才有效**——它是在 `on_invalidate` 回调中被调用的。但问题是 `on_invalidate` 本身需要被触发才能进入这个回调，而触发 `on_invalidate` 的前提又是需要重绘 —— 形成了一个鸡生蛋蛋生鸡的问题。

### 根因 4: 为什么降级模式正常？

降级模式不需要 prompt_toolkit 的渲染循环。它直接用 `input()` 阻塞 + `console.print()` 输出。`asyncio.run(_consume())` 在**主线程**中运行，消耗完整个异步生成器后才返回。每个 token 直接 `console.print(token, end="")` 输出到终端，**没有中间队列**，没有线程切换，没有渲染调度问题。

---

## 4. 修复方案（按推荐顺序）

### 方案 A（推荐）: 使用 prompt_toolkit 的 `run_in_terminal` + 定时器

prompt_toolkit 提供了 `Application.create_background_task()` 或使用 `app.invalidate()` + 定时刷新机制。

**核心思路**: 注册一个高频定时器（例如每 50ms），在定时器回调中消费 `_ui_update_queue`。

```python
# 在 run() 方法中，app.run() 之前：
def _drain_ui_updates():
    """定时器回调 — 从后台线程队列消费 UI 更新"""
    self._process_ui_updates()

# 每 50ms 检查一次队列
self.app.create_background_task(_drain_ui_updates, interval=0.05)
```

或者使用更轻量的方式：
```python
from prompt_toolkit.eventloop import call_soon_threadsafe

# 在后台线程中，put 数据到队列后：
call_soon_threadsafe(self._process_ui_updates)
```

**优点**: 最小改动，实现线程安全
**缺点**: 定时器轮询有空转开销

### 方案 B: 使用 `call_soon_threadsafe` 直接通知主线程

```python
# 在 _push_ui 函数中（repl.py:835-837）
def _push_ui(action: str, **kwargs):
    self._ui_update_queue.put((action, kwargs))
    # 通知主线程消费
    if self.app:
        from prompt_toolkit.eventloop import call_soon_threadsafe
        call_soon_threadsafe(self._process_ui_updates)
```

这样后台线程 put 数据后，立即通过 prompt_toolkit 的线程安全机制通知主线程来消费。

**优点**: 事件驱动，无轮询开销
**缺点**: 依赖 prompt_toolkit 的内部 API

### 方案 C: 直接在主线程的 asyncio 事件循环中运行 Agent Loop

将 `_async_agent_loop` 改为在 prompt_toolkit Application 的同一个事件循环中运行，完全避免线程切换：

```python
# 在 _dispatch_message 中:
if self._agent_loop:
    # 不启动线程，直接在 app 的事件循环中创建任务
    self.app.create_background_task(
        self._async_agent_loop(text)
    )
```

然后在 `_async_agent_loop` 中直接修改 `self.output`（因为已经在主线程了），每次 `text_delta` 后直接调用 `app.invalidate()`。

**优点**: 最简单、最优雅
**缺点**: 需要将 `_async_agent_loop` 改为同步修改 output（不需要队列了）

### 方案 D: 合并队列消费和 on_invalidate + 定时 invalidate

结合方案 A 的定时器 + 保持现有架构：

```python
# 在后台线程 _run() 的 finally 块中:
finally:
    self._agent_running = False
    self._ui_update_queue.put(("agent_done", {}))
    # 使用线程安全方式通知主线程
    if self.app:
        from prompt_toolkit.application.current import get_app
        try:
            app = get_app()
            app.invalidate()  # 不够，因为这不是线程安全的
        except Exception:
            pass
```

但这不能解决问题，因为 `app.invalidate()` 不是线程安全的。

---

## 5. 推荐的最终方案

**方案 C 是最优解**，但它需要较大重构。作为快速修复，**方案 B（call_soon_threadsafe）** 是最务实的：

1. 在 `_push_ui` 中添加 `call_soon_threadsafe(self._process_ui_updates)`
2. 在 `_process_with_agent_loop` 的 finally 块中也添加相同的调用

这样每次后台线程 put 数据后，主线程的事件循环会尽快调度 `_process_ui_updates` 来消费。

---

## 6. 测试验证

当前测试全部通过（1050 passed, 1 warning），但没有覆盖全屏 TUI 模式下的流式输出场景（因为没有 mock prompt_toolkit Application 的完整渲染循环）。

需要添加的测试：
1. `test_repl_streaming_fullscreen` — 模拟后台线程 put 数据后 UI 更新被消费
2. `test_process_ui_updates_text_delta` — 验证 text_delta 正确追加到 output
3. `test_process_ui_updates_thread_safety` — 验证多线程 put/get 正确性

---

## 7. 总结

| 问题 | 严重性 | 类型 |
|------|--------|------|
| `on_invalidate` 只在有渲染需求时触发，队列有数据时不触发 | **严重** | 架构缺陷 |
| `_accept_input` 返回后缺少 invalidate 调用 | 中等 | 逻辑遗漏 |
| `app.invalidate()` 从非 UI 线程调用不安全 | 中等 | 线程安全 |
| 降级模式 vs 全屏模式的架构差异 | 信息 | 设计对比 |

**核心修复**: 让后台线程能够通知主线程消费 `_ui_update_queue`，使用 `call_soon_threadsafe` 是最小改动方案。
