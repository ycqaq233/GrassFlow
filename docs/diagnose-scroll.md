# REPL 输出区域滚动问题诊断报告

## 诊断结论

**布局代码在重构前后结构完全一致，未发现直接导致滚动失效的代码差异。** 但发现一个独立 bug（`mode` 被值捕获）和一个值得关注的疑点（Ctrl+Up/Down 空实现）。

---

## 1. 布局代码对比

### 旧代码（repl.py，重构前，commit HEAD~2）

```python
output_window = Window(
    content=FormattedTextControl(
        text=self._get_output_text,     # 绑定方法
        focusable=False,
    ),
    wrap_lines=True,
    always_hide_cursor=True,
    scroll_offsets=ScrollOffsets(top=2, bottom=2),
    right_margins=[ScrollbarMargin()],
)
```

### 新代码（tui/layout.py，重构后）

```python
output_window = Window(
    content=FormattedTextControl(
        text=output_text_cb,            # 闭包回调
        focusable=False,
    ),
    wrap_lines=True,
    always_hide_cursor=True,
    scroll_offsets=ScrollOffsets(top=2, bottom=2),
    right_margins=[ScrollbarMargin()],
)
```

**对比结果**：参数完全一致。唯一区别是旧代码用绑定方法 `self._get_output_text`，新代码用闭包 `output_text_cb`。两者都是 callable，返回相同的 `List[Tuple[str, str]]` 格式。prompt_toolkit 对两者等价处理。

---

## 2. Application 配置对比

### 旧代码
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

### 新代码
```python
self.app = Application(
    layout=self._build_layout(), key_bindings=self.kb, style=build_pt_style(self._theme),
    full_screen=True, mouse_support=True, enable_page_navigation_bindings=True,
)
```

**对比结果**：完全一致。`full_screen=True`、`mouse_support=True`、`enable_page_navigation_bindings=True` 三项关键配置均相同。

---

## 3. 发现的问题

### 问题 A：Ctrl+Up / Ctrl+Down 滚动处理为空（两版均存在）

**文件**：`tui/layout.py:694-703`

```python
@kb.add("c-up")
def handle_scroll_up(event: KeyPressEvent) -> None:
    """Ctrl+Up：向上滚动输出"""
    # prompt_toolkit layout 会自动处理 scroll
    pass

@kb.add("c-down")
def handle_scroll_down(event: KeyPressEvent) -> None:
    """Ctrl+Down：向下滚动输出"""
    pass
```

这两个快捷键处理器注册了 `c-up` 和 `c-down`，但函数体为 `pass`（空实现）。**注册空 handler 会覆盖 prompt_toolkit 的默认行为**。prompt_toolkit 的 `enable_page_navigation_bindings=True` 启用的是 Page Up/Down 和一些其他绑定，但 Ctrl+Up/Down 可能有自己的默认行为，被空 handler 抢占后失效。

**注意**：旧代码中同样存在此问题，因此这不是重构引入的回归。

### 问题 B：`mode` 参数被值捕获（重构引入的 bug）

**文件**：`tui/layout.py:211-259`

```python
def make_header_text_cb(
    session: Any,
    output: List[OutputEntry],
    mode: REPLMode,          # <-- 值捕获，不是引用
    default_model: str = "deepseek-chat",
) -> Callable[[], List[Tuple[str, str]]]:
    def _get_header_text() -> List[Tuple[str, str]]:
        # ...
        mode_text = {
            REPLMode.NORMAL: "NORMAL",
            REPLMode.BUSY: "BUSY",
            REPLMode.APPROVAL: "APPROVAL",
        }.get(mode, "NORMAL")  # <-- 使用闭包捕获的旧值
```

`mode` 是 Python 枚举字符串（immutable），在 `make_header_text_cb` 调用时被捕获。之后即使 `repl.mode` 变为 `BUSY` 或 `APPROVAL`，header 仍显示旧值。

**对比旧代码**：旧代码中 `_get_header_text` 是实例方法，直接读 `self.mode`，始终获取最新值。

**修复方案**：改为传入 callable 或直接传入 repl 引用。

---

## 4. 输出文本回调对比

### 旧代码
```python
def _get_output_text(self) -> List[Tuple[str, str]]:
    for entry in self.output:
        style = self._get_role_style(entry.role)
        # ...
        result.append((f"class:{style}", f"{prefix}{entry.text}\n"))
```

### 新代码
```python
def make_output_text_cb(output: List[OutputEntry]) -> Callable[...]:
    def _get_output_text() -> List[Tuple[str, str]]:
        for entry in output:
            style = get_role_style(entry.role)
            # ...
            result.append((f"class:{style}", f"{prefix}{entry.text}\n"))
```

**对比结果**：逻辑完全等价。`output` 是 `repl.output` 的引用（mutable list），闭包读取时获取最新内容。`get_role_style` 返回值与旧代码 `_get_role_style` 一致。

---

## 5. 其他检查项

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `scrollable=True` | 未设置（两版均无） | prompt_toolkit 的 Window 没有 `scrollable` 参数，滚动由 `scroll_offsets` 和 `ScrollbarMargin` 驱动 |
| `ScrollbarMargin` | 已挂载 | `right_margins=[ScrollbarMargin()]` 两版均存在 |
| `ScrollOffsets` | 已配置 | `ScrollOffsets(top=2, bottom=2)` 两版均一致 |
| `mouse_support` | 已启用 | `mouse_support=True` 两版均一致 |
| `on_invalidate` | 正常 | 两版均在 `on_invalidate` 中消费 UI 更新队列并调用 `app.invalidate()` |

---

## 6. 建议修复

### 修复 1：Ctrl+Up/Down 空 handler 问题

删除空的 Ctrl+Up/Down handler，或实现真正的滚动逻辑：

```python
@kb.add("c-up")
def handle_scroll_up(event: KeyPressEvent) -> None:
    """Ctrl+Up：向上滚动输出"""
    event.app.layout.current_window.scroll_up()

@kb.add("c-down")
def handle_scroll_down(event: KeyPressEvent) -> None:
    """Ctrl+Down：向下滚动输出"""
    event.app.layout.current_window.scroll_down()
```

### 修复 2：mode 值捕获问题

将 `mode` 改为传入 callable：

```python
def make_header_text_cb(
    session: Any,
    output: List[OutputEntry],
    mode_fn: Callable[[], REPLMode],  # 改为 callable
    default_model: str = "deepseek-chat",
) -> Callable[[], List[Tuple[str, str]]]:
    def _get_header_text() -> List[Tuple[str, str]]:
        # ...
        mode_text = {
            REPLMode.NORMAL: "NORMAL",
            REPLMode.BUSY: "BUSY",
            REPLMode.APPROVAL: "APPROVAL",
        }.get(mode_fn(), "NORMAL")  # 调用 callable 获取最新值
```

对应 `build_layout_from_repl` 中传入 `lambda: repl.mode`。

---

## 7. 排查建议

如果上述修复后滚动仍然不工作，需要进一步排查：

1. **确认终端模拟器**：某些终端（如 Git Bash/mintty）对鼠标事件支持有限
2. **确认 prompt_toolkit 版本**：运行 `pip show prompt_toolkit` 确认版本号
3. **最小化复现**：用一个最简单的 prompt_toolkit 全屏 Application 测试滚动是否工作
4. **检查输出内容格式**：如果所有文本都不含 `\n`，prompt_toolkit 可能不会产生足够行数触发滚动
