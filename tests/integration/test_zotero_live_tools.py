from __future__ import annotations

import json
import os

import pytest

from academic_tools.tools import zotero as zotero_tools
from academic_tools.zotero.bibtex_client import ZoteroBetterBibTexAPI


class _CapturingMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _registered_tools() -> dict[str, object]:
    mcp = _CapturingMCP()
    zotero_tools.register(mcp)
    return mcp.tools


def _require_success(raw: str) -> dict[str, object]:
    payload = json.loads(raw)
    assert payload["status"] == "success", payload
    return payload


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _enabled("ZOTERO_LIVE_TEST"),
        reason="Set ZOTERO_LIVE_TEST=1 to run live Zotero integration tests.",
    ),
]


@pytest.mark.asyncio
async def test_live_zotero_read_only_library_tools() -> None:
    tools = _registered_tools()

    recent = _require_success(await tools["zotero_get_recent"](limit=3, include_abstract=False))
    assert "items" in recent

    collections = _require_success(await tools["zotero_get_collections"](include_items_count=True))
    assert "collections" in collections

    tags = _require_success(await tools["zotero_get_tags"]())
    assert "tags" in tags

    query = os.getenv("ZOTERO_LIVE_SEARCH_QUERY", "").strip()
    if query:
        search = _require_success(
            await tools["zotero_search_items"](query, limit=5, include_abstract=False)
        )
        assert "items" in search


@pytest.mark.asyncio
async def test_live_zotero_item_read_tools() -> None:
    item_key = os.getenv("ZOTERO_LIVE_ITEM_KEY", "").strip()
    if not item_key:
        pytest.skip("Set ZOTERO_LIVE_ITEM_KEY to test item-specific live Zotero tools.")

    tools = _registered_tools()

    metadata = _require_success(await tools["zotero_get_item_metadata"](item_key))
    assert metadata["item_key"] == item_key
    assert metadata["content"]

    fulltext = _require_success(await tools["zotero_get_item_fulltext"](item_key))
    assert "content" in fulltext
    if _enabled("ZOTERO_LIVE_EXPECT_FULLTEXT"):
        assert fulltext["content"]

    annotations = _require_success(await tools["zotero_get_annotations"](item_key))
    assert "annotations" in annotations
    if _enabled("ZOTERO_LIVE_EXPECT_ANNOTATIONS"):
        assert annotations["count"] > 0

    notes = _require_success(await tools["zotero_get_notes"](item_key))
    assert "notes" in notes
    if _enabled("ZOTERO_LIVE_EXPECT_NOTES"):
        assert notes["count"] > 0


@pytest.mark.asyncio
async def test_live_zotero_collection_items_tool() -> None:
    collection_key = os.getenv("ZOTERO_LIVE_COLLECTION_KEY", "").strip()
    if not collection_key:
        pytest.skip("Set ZOTERO_LIVE_COLLECTION_KEY to test collection item lookup.")

    tools = _registered_tools()
    payload = _require_success(
        await tools["zotero_get_collection_items"](
            collection_key,
            limit=5,
            include_abstract=False,
        )
    )
    assert payload["collection_key"] == collection_key
    assert "items" in payload


def test_live_better_bibtex_diagnosis_when_required() -> None:
    if not _enabled("ZOTERO_LIVE_REQUIRE_BBT"):
        pytest.skip("Set ZOTERO_LIVE_REQUIRE_BBT=1 to require Better BibTeX local API.")

    diagnosis = ZoteroBetterBibTexAPI().diagnose_connection()
    assert diagnosis["status"] == "success", diagnosis
