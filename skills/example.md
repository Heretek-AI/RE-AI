---
name: example
description: Template showcasing the skill file format — copy this to create new skills
---

## Skill Template

This file demonstrates the skill file format. Copy it to create new skills for different tools.

### Frontmatter Fields

- **name** (required): Unique skill name. Must match the tool's name if `tool_id` is set.
- **description** (required): One-sentence summary of what the skill covers.
- **tool_id** (optional): The `ToolDef.name` this skill enriches. When set, the skill content is appended to that tool's description in the system prompt.
- **command_hint** (optional): Example command invocation the agent can reference.

### Body (Markdown)

The body contains the actual guidance — usage patterns, best practices, error handling, and platform notes. Format as standard Markdown with headings, lists, and code blocks.

### Creating a New Skill

1. Copy this file: `cp skills/example.md skills/<name>.md`
2. Update the YAML frontmatter between `---` markers.
3. Replace the body with tool-specific guidance.
4. The skill loader automatically discovers new files on next agent restart.

### Linking to ToolRegistry

Skills with a `tool_id` that matches an existing `ToolDef.name` will have their content appended to that tool's description. This means the agent sees the enrichment in its system prompt automatically.
