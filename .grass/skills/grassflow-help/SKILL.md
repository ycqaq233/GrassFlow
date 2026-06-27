---
name: grassflow-help
description: Provides help and guidance for using GrassFlow commands and features
version: 1.0.0
platforms: [windows, linux, macos]
metadata:
  tags: [grassflow, help, documentation]
---

# GrassFlow Help Skill

Provides contextual help for GrassFlow CLI commands and workflow features.

## Usage

When the user asks about GrassFlow features, commands, or workflow syntax, use this skill to provide accurate guidance.

## Commands Reference

- `grassflow run <file.af>` - Execute a workflow file
- `grassflow ask "<prompt>"` - Single prompt execution with tools
- `grassflow repl` - Interactive REPL session
- `grassflow list` - List saved workflows
- `grassflow validate <file.af>` - Validate a workflow file
- `grassflow doctor` - System health check
- `grassflow models` - List available AI models
- `grassflow config list` - Show configuration

## DSL Syntax

```
A -> B           # Sequential
(A, B) -> C      # Parallel
A | B            # Immediate execution
route -> [cond] target  # Conditional branch
```
