"""Prompt loading and response parsing utilities."""

from __future__ import annotations

import importlib.resources
import re
from pathlib import Path


def load_prompt(name: str) -> str:
    """
    Load a prompt template from the ``prompts/`` package directory.

    Args:
        name: filename within prompts/, e.g. ``"metadata_extraction.md"``

    Returns:
        Raw prompt string.
    """
    prompts_dir = Path(__file__).parent.parent / "prompts"
    path = prompts_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def fill_prompt(template: str, **kwargs: str) -> str:
    """
    Replace ``{{key}}`` placeholders in a template string.

    Example::

        fill_prompt(template, document=text, title=paper_title)
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def extract_json_from_response(response: str) -> str:
    """
    Extract JSON string from an LLM response that may contain markdown fences
    or other surrounding text.

    Priority:
    1. ```json ... ``` or ``` ... ``` blocks
    2. Bare JSON starting with ``{`` or ``[``
    3. First ``{...}`` block found anywhere
    4. First ``[...]`` block found anywhere
    5. Return raw stripped text as fallback
    """
    # 1. Markdown code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if fence_match:
        return fence_match.group(1).strip()

    stripped = response.strip()

    # 2. Bare JSON
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped

    # 3. First object block
    obj_match = re.search(r"(\{[\s\S]*\})", response)
    if obj_match:
        return obj_match.group(1).strip()

    # 4. First array block
    arr_match = re.search(r"(\[[\s\S]*\])", response)
    if arr_match:
        return arr_match.group(1).strip()

    # 5. Fallback
    return stripped
