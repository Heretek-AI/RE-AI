"""Skill loader — reads ``skills/*.md`` files and returns ``SkillDef`` instances.

Each skill file is a Markdown document with YAML frontmatter:

.. code-block:: markdown

    ---
    name: shell
    description: How to use the shell tool effectively
    tool_id: shell
    command_hint: Use this when you need to run commands
    ---

    ## Best Practices

    - Always set ``cwd`` explicitly
    ...

The frontmatter **must** contain ``name`` and ``description``.
``tool_id`` and ``command_hint`` are optional.
"""

from __future__ import annotations

import glob
import logging
import os
from typing import Optional

import frontmatter

from backend.registry.models import SkillDef

logger = logging.getLogger(__name__)

# Default directory where skill markdown files are stored.
# Relative to the project root (where the agent runs its ``cwd``).
DEFAULT_SKILLS_DIR: str = "skills"


def _discover_skill_paths(skills_dir: str) -> list[str]:
    """Return all ``*.md`` files under *skills_dir* (non-recursive).

    Returns an empty list if the directory does not exist.
    """
    if not os.path.isdir(skills_dir):
        logger.debug("Skills directory '%s' does not exist — no skills loaded.", skills_dir)
        return []
    pattern = os.path.join(skills_dir, "*.md")
    return sorted(glob.glob(pattern))


def _parse_skill_file(filepath: str) -> Optional[SkillDef]:
    """Parse a single skill markdown file into a ``SkillDef``.

    Returns ``None`` if the file lacks required frontmatter fields
    (``name``, ``description``).
    """
    try:
        with open(filepath, encoding="utf-8") as fh:
            post = frontmatter.load(fh)
    except Exception as exc:
        logger.warning("Failed to parse skill file '%s': %s", filepath, exc)
        return None

    name = post.get("name")
    description = post.get("description")

    if not name or not description:
        logger.warning(
            "Skill file '%s' missing required frontmatter (name, description), skipping.",
            filepath,
        )
        return None

    return SkillDef(
        name=str(name),
        description=str(description),
        tool_id=str(post.get("tool_id")) if post.get("tool_id") else None,
        command_hint=str(post.get("command_hint")) if post.get("command_hint") else None,
        content=post.content,
    )


def load_skills(skills_dir: str = DEFAULT_SKILLS_DIR) -> list[SkillDef]:
    """Discover and parse all skill files under *skills_dir*.

    Parameters
    ----------
    skills_dir:
        Directory path containing ``*.md`` skill files.
        Defaults to ``"skills"`` (project root).

    Returns
    -------
    list[SkillDef]
        Parsed skill definitions.  Files with missing or invalid
        frontmatter are skipped with a warning.
    """
    paths = _discover_skill_paths(skills_dir)
    skills: list[SkillDef] = []

    for path in paths:
        skill = _parse_skill_file(path)
        if skill is not None:
            skills.append(skill)
            logger.debug("Loaded skill '%s' from %s", skill.name, path)

    logger.info("Loaded %d skill(s) from %s", len(skills), skills_dir)
    return skills
