---
name: save-progress
description: 保存当前项目进度到 项目制作计划.md，在 compact 前调用以防止进度丢失
---

# 保存项目进度

将当前项目进展写入 `项目制作计划.md`，确保 compact 后上下文不会丢失重要信息。

## 执行步骤

### 1. 收集当前状态

通过 git 和文件系统收集信息：

```bash
# 获取最近提交
git log --oneline -10

# 获取文件统计
find . -name "*.py" -path "*/core/*" -o -name "*.py" -path "*/tui/*" -o -name "*.py" -path "*/tools/*" | wc -l
find tests/ -name "*.py" | wc -l

# 获取测试数量
python -m pytest tests/ --collect-only -q 2>&1 | tail -1
```

### 2. 收集已完成功能

- 读取 `PROJECT_STATUS.md` 了解上次记录的已完成内容
- 对比 git log 找出上次记录以来的新提交
- 汇总新增的文件和模块

### 3. 收集待办事项

- 检查 `docs/` 目录中的诊断报告，提取未解决的 bug
- 检查 CLAUDE.md 中的计划目标，确认哪些已完成哪些未完成
- 列出高/中/低优先级待办

### 4. 写入 项目制作计划.md

按以下格式写入：

```markdown
# GrassFlow 项目制作计划

> 最后更新：YYYY-MM-DD HH:MM

## 当前进度

### 已完成
- [x] 功能 A
- [x] 功能 B

### 进行中
- [ ] 功能 C (当前阶段)

### 待开始
- [ ] 功能 D
- [ ] 功能 E

## 技术状态

- 文件数：XX 个 Python 文件
- 测试数：XXX passed
- 最近提交：[hash] message

## 已知问题

- Bug #1: 描述 (位置: file.py:123)
- Bug #2: 描述

## 下一步计划

1. 优先级高：...
2. 优先级中：...
3. 优先级低：...
```

## 注意

- 汇总信息要简洁，compact 后的新会话需要能快速理解当前状态
- 记录所有进行中的工作，避免 compact 后丢失上下文
- 记录尚未提交的修改（如果有）
- 不要推测或编造信息，只记录已知事实
