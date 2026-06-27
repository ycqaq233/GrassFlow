---
name: hello-skill
description: A minimal example skill that demonstrates the SKILL.md format and skills discovery pipeline.
slash: true
tags: [example, demo]
version: "1.0.0"
platforms: [windows, linux, macos]
---

# Hello Skill

This is an example skill used to validate the GrassFlow skills discovery and loading pipeline.

## What it does

When invoked, this skill prints a greeting message confirming that the skills system is working correctly.

## Usage

Use this skill to verify:
1. Skills directory scanning (`skills/**/SKILL.md`)
2. YAML frontmatter parsing (name, description, tags, version)
3. Platform filtering (windows, linux, macos)
4. Skills prompt injection into the system prompt

## Instructions

To verify the skills system is working, run:

```
grassflow repl
/skills
```

You should see `hello-skill` listed in the available skills output.
