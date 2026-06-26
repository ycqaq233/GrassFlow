# GrassFlow CLI 当前实现调查报告

## 概述

调查 `tui/layout.py`、`tui/repl.py`、`tui/fallback.py` 三个文件中所有与 prompt_toolkit 相关的代码。

---

## 1. tui/layout.py — 布局、样式、快捷键

### 1.1 prompt_toolkit 依赖

```python
# 行 21-36
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    Float, FloatContainer, HSplit, Layout, ScrollOffsets, VSplit, Window, WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.styles import Style
```

**注意**: `Float`, `FloatContainer`, `VSplit`, `WindowAlign` 被导入但未使用。

### 1.2 build_layout 函数 (行 420-504)

```python
def build_layout(
    input_buffer: Buffer,
    header_text_cb, output_text_cb, status_text_cb,
) -> Tuple[Layout, Window]:
    # 输出区域 Window
    output_window = Window(
        content=FormattedTextControl(text=output_text_cb, focusable=False),
        wrap_lines=True,
        always_hide_cursor=True,
        scroll_offsets=ScrollOffsets(top=2, bottom=2),
        right_margins=[ScrollbarMargin()],
    )

    # HSplit 布局
    root_container = HSplit([
        Window(content=FormattedTextControl(text=header_text_cb), height=1, style="class:header"),
        Window(height=1, char="-", style="class:header-dim"),       # 分隔线
        output_window,                                                # 输出区域
        Window(height=1, char="-", style="class:header-dim"),       # 分隔线
        Window(content=FormattedTextControl(text=status_text_cb), height=1, style="class:status-bar"),
        Window(                                                       # 输入区域
            content=BufferControl(buffer=input_buffer, input_processors=[]),
            height=3, style="class:input-area", wrap_lines=True,
            get_line_prefix=get_input_prefix,
        ),
    ])
    return Layout(root_container), output_window
```

**关键观察:**
- 输出区域使用 `FormattedTextControl`，`focusable=False` — 不能接收焦点/键盘事件
- 使用 `ScrollbarMargin()` 添加滚动条
- `ScrollOffsets(top=2, bottom=2)` — 滚动时保留上下 2 行边距
- 输入区域固定 `height=3`
- 没有使用 `Float`/`FloatContainer`（补全菜单浮层等）

### 1.3 handle_enter 函数 (行 604-619)

```python
@kb.add("enter")
def handle_enter(event: KeyPressEvent) -> None:
    if callbacks.mode() == REPLMode.APPROVAL:
        return  # 审批模式下回车=确认
    if callbacks.agent_running():
        return  # Agent 运行中不处理
    buffer = event.app.current_buffer
    buffer.validate_and_handle()
    # validate_and_handle 返回后再调用 app.exit() 避免冲突
    if callbacks.should_exit():
        event.app.exit()
```

**问题:**
- `validate_and_handle()` 内部会调用 `accept_handler`（即 `_accept_input`），如果 accept_handler 返回 False 或抛异常，后续的 `should_exit()` 检查可能不会执行
- 没有检查 `validate_and_handle()` 的返回值

### 1.4 鼠标滚轮绑定

**当前实现中没有鼠标滚轮绑定。** 虽然 `repl.py` 中 Application 创建时设置了 `mouse_support=True`，但 layout.py 的 `build_keybindings` 中没有注册任何鼠标事件处理器。

滚动仅通过 Ctrl+Up/Ctrl+Down 实现 (行 703-719):

```python
@kb.add("c-up")
def handle_scroll_up(event):
    win = callbacks.get_output_window()
    if win:
        win.vertical_scroll = max(0, win.vertical_scroll - 3)
        event.app.invalidate()

@kb.add("c-down")
def handle_scroll_down(event):
    win = callbacks.get_output_window()
    if win:
        win.vertical_scroll += 3
        event.app.invalidate()
```

**问题:**
- 直接修改 `vertical_scroll` 属性是 hack 方式，不是 prompt_toolkit 推荐的滚动方式
- 缺少 `c-up` / `c-down` 的 `eager=True` 标记，可能被其他处理器消费
- 没有鼠标滚轮支持（prompt_toolkit 支持通过 `handler.mouse_scroll` 或注册 mouse 绑定实现）

### 1.5 输出区域自动滚动 (repl.py 行 113-114)

```python
def add_output(self, text, role="system", metadata=None):
    entry = OutputEntry(text=text, role=role, metadata=metadata)
    self.output.append(entry)
    if len(self.output) > MAX_OUTPUT_LINES:
        self.output = self.output[len(self.output) - MAX_OUTPUT_LINES:]
    # 自动滚动到底部
    if self._output_window:
        self._output_window.vertical_scroll = 10**6
```

**问题:**
- `vertical_scroll = 10**6` 是一个 hack — 试图设置一个足够大的值让窗口滚动到底部
- prompt_toolkit 的 `Window` 有 `scroll_to_bottom()` 方法可以正确实现此功能
- 每次 add_output 都触发滚动，用户无法在阅读历史输出时保持滚动位置

---

## 2. tui/repl.py — Application 生命周期

### 2.1 Application 创建 (行 372-375)

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

**观察:**
- `full_screen=True` — 全屏模式（替代整个终端内容）
- `mouse_support=True` — 启用鼠标支持，但没有注册鼠标事件处理器
- `enable_page_navigation_bindings=True` — 启用 Page Up/Down 等导航键
- 没有设置 `paste_mode`、`editing_mode` 等

### 2.2 run vs run_async

同步版 (行 387):
```python
self.app.run()
```

异步版 (行 426):
```python
await self.app.run_async()
```

两者都有 try/except 包裹，异常时调用 `add_output` 记录错误。

### 2.3 on_invalidate 钩子 (行 383-386)

```python
def _on_invalidate(_sender=None):
    self._process_ui_updates()
self.app.on_invalidate += _on_invalidate
```

**问题:**
- `on_invalidate` 在每次 UI 重绘时触发，调用 `_process_ui_updates()` 消费 Agent 后台线程的事件队列
- 这是一种轮询模式 — 每次 invalidate 都检查队列，即使没有新事件
- prompt_toolkit 推荐使用 `app.loop.call_soon_threadsafe()` 从后台线程直接调度 UI 更新

### 2.4 _accept_input 方法 (行 168-175)

```python
def _accept_input(self, buffer: Buffer) -> bool:
    text = buffer.text.strip()
    if not text:
        buffer.reset()
        return True
    buffer.reset()
    self._process_user_input(text)
    return True
```

**观察:**
- 作为 Buffer 的 `accept_handler` 被调用
- 始终返回 True
- 在处理前先 `buffer.reset()` 清空输入

### 2.5 补全器

```python
self._completer = SlashCommandCompleter()
self.input_buffer = Buffer(
    multiline=True, completer=self._completer, complete_while_typing=True,
    accept_handler=self._accept_input,
)
```

使用自定义的 `SlashCommandCompleter`，支持 `/` 命令补全。`complete_while_typing=True` 表示打字时自动显示补全菜单。

---

## 3. tui/fallback.py — 降级模式

### 3.1 概述

当 prompt_toolkit Application 无法创建时（如 Windows Git Bash / mintty / 非全屏终端），使用 `input()` + Rich Console 实现简单 REPL。

### 3.2 实现方式

```python
console = RichConsole(highlight=False)
while running:
    try:
        user_input = input(PROMPT)
    except (EOFError, KeyboardInterrupt):
        break
    # 处理命令或调用 Agent
    if agent_integration:
        asyncio.run(_consume_agent_stream(agent_integration, stripped, console))
```

**特点:**
- 使用标准 `input()` 获取输入（不支持历史记录、补全、多行编辑）
- 使用 Rich Console 渲染输出（支持 Markdown、颜色、Panel 等）
- `asyncio.run()` 同步运行异步 Agent 流
- 支持 `/help`, `/clear`, `/exit` 三个命令
- 无会话持久化、无 undo/redo

---

## 4. 问题总结

### 4.1 与 prompt_toolkit 最佳实践的差距

| 问题 | 当前实现 | 最佳实践 |
|------|---------|---------|
| **滚动到底部** | `vertical_scroll = 10**6` hack | 使用 `Window.scroll_to_bottom()` 或 `BufferControl` 的 scroll 功能 |
| **鼠标滚轮** | 未实现（仅 Ctrl+Up/Down） | 注册 `scroll-up` / `scroll-down` 鼠标事件，或使用 `Window` 的内置鼠标滚动 |
| **自动滚动与用户阅读冲突** | 每次 add_output 强制滚到底 | 检查是否已在底部，只有在底部时才自动跟随 |
| **UI 更新机制** | on_invalidate 轮询队列 | 使用 `call_soon_threadsafe` 从后台线程直接调度 |
| **Float/FloatContainer 未使用** | 导入但未使用 | 应用于补全菜单浮层、弹窗等 |
| **输入区域高度固定** | `height=3` | 应根据内容动态调整，或支持用户拉伸 |
| **handle_enter 异常处理** | 不检查 validate_and_handle 返回值 | 应检查返回值并处理异常情况 |
| **eager 键绑定** | Ctrl+Up/Down 缺少 eager=True | 用于确保键不被其他处理器消费 |

### 4.2 代码质量观察

- `tui/layout.py` 有良好的模块化设计，回调通过工厂函数创建
- `KeybindingCallbacks` 类将 REPL 方法封装为回调，解耦了 layout 和 repl
- fallback.py 实现简洁，但功能有限
- 未使用的导入 (`Float`, `FloatContainer`, `VSplit`, `WindowAlign`) 应清理

### 4.3 架构观察

```
repl.py
  ├── GrassFlowREPL (主类)
  │   ├── _build_layout() → 委托给 layout.py
  │   ├── _setup_keybindings() → 委托给 layout.py
  │   ├── add_output() → 管理 self.output + 滚动
  │   ├── _accept_input() → Buffer accept_handler
  │   ├── _process_user_input() → 分发到命令/Agent
  │   └── run() → 创建 Application 并运行
  ├── AsyncGrassFlowREPL (异步变体)
  └── fallback.py (降级模式)
```

layout.py 只负责 UI 层（布局、样式、快捷键绑定），repl.py 负责业务逻辑和 Application 生命周期。这是一个合理的分层设计。
