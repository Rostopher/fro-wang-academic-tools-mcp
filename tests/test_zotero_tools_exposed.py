from __future__ import annotations

import json

import pytest

from academic_tools.tools import zotero as zotero_tools


class _CapturingMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _registered_tools() -> dict[str, object]:
    mcp = _CapturingMCP()
    zotero_tools.register(mcp)
    return mcp.tools


def _paper_item(key: str = "ITEM123") -> dict[str, object]:
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "journalArticle",
            "title": "Attention Is All You Need",
            "date": "2017",
            "creators": [
                {
                    "creatorType": "author",
                    "firstName": "Ashish",
                    "lastName": "Vaswani",
                }
            ],
            "publicationTitle": "NeurIPS",
            "abstractNote": "Transformer architecture.",
            "DOI": "10.5555/example",
            "tags": [{"tag": "transformer"}],
        },
        "meta": {"numChildren": 3},
    }


class _FakeZotero:
    def __init__(self) -> None:
        pass

    def items(self, **kwargs):
        assert kwargs["limit"] >= 1
        return [_paper_item("ITEM123")]

    def item(self, item_key: str):
        assert item_key == "ITEM123"
        return _paper_item(item_key)

    def fulltext_item(self, item_key: str):
        assert item_key == "ITEM123"
        return {"content": "Indexed full text from Zotero."}

    def collections(self):
        return [
            {
                "key": "COLL1",
                "data": {
                    "key": "COLL1",
                    "name": "Papers",
                    "parentCollection": "",
                    "numItems": 1,
                },
            }
        ]

    def collection_items(self, collection_key: str, limit: int):
        assert collection_key == "COLL1"
        assert limit == 5
        return [_paper_item("ITEM123")]

    def tags(self):
        return [{"tag": "transformer"}, "zotero"]

    def children(self, item_key: str):
        assert item_key == "ITEM123"
        return [
            {
                "key": "ANN1",
                "data": {
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Scaled dot-product attention.",
                    "annotationComment": "Important mechanism.",
                    "annotationPageLabel": "3",
                    "annotationColor": "#ffd400",
                },
            },
            {
                "key": "NOTE1",
                "data": {
                    "itemType": "note",
                    "note": "<p>Read again before writing.</p>",
                },
            },
        ]

class _FakeBetterBibTexUnavailable:
    def is_zotero_running(self) -> bool:
        return False


def test_zotero_register_exposes_all_agent_tools() -> None:
    tools = _registered_tools()

    assert set(tools) == {
        "zotero_search_items",
        "zotero_get_item_metadata",
        "zotero_get_item_fulltext",
        "zotero_get_collections",
        "zotero_get_collection_items",
        "zotero_get_tags",
        "zotero_get_recent",
        "zotero_get_annotations",
        "zotero_get_notes",
    }


@pytest.mark.asyncio
async def test_zotero_agent_tools_are_callable_on_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_zotero = _FakeZotero()
    monkeypatch.setattr(zotero_tools, "get_zotero_client", lambda: fake_zotero)
    monkeypatch.setattr(
        zotero_tools,
        "ZoteroBetterBibTexAPI",
        lambda: _FakeBetterBibTexUnavailable(),
    )

    tools = _registered_tools()

    search = json.loads(
        await tools["zotero_search_items"]("attention", limit=5, include_abstract=True)
    )
    assert search["status"] == "success"
    assert search["count"] == 1
    assert "Attention Is All You Need" in search["content"]
    assert "Transformer architecture." in search["content"]

    metadata = json.loads(await tools["zotero_get_item_metadata"]("ITEM123"))
    assert metadata["status"] == "success"
    assert metadata["item_key"] == "ITEM123"
    assert "Attention Is All You Need" in metadata["content"]
    assert "**Item Key:** ITEM123" in metadata["content"]

    fulltext = json.loads(await tools["zotero_get_item_fulltext"]("ITEM123"))
    assert fulltext["status"] == "success"
    assert fulltext["content"] == "Indexed full text from Zotero."

    collections = json.loads(await tools["zotero_get_collections"](include_items_count=True))
    assert collections["status"] == "success"
    assert collections["count"] == 1
    assert "- **Papers** (`COLL1`)  [1 items]" in collections["content"]

    collection_items = json.loads(
        await tools["zotero_get_collection_items"](
            "COLL1",
            limit=5,
            include_abstract=False,
        )
    )
    assert collection_items["status"] == "success"
    assert "Attention Is All You Need" in collection_items["content"]
    assert "## Abstract" not in collection_items["content"]

    tags = json.loads(await tools["zotero_get_tags"]("trans"))
    assert tags["status"] == "success"
    assert tags["content"] == "- transformer"

    recent = json.loads(await tools["zotero_get_recent"](limit=5, include_abstract=False))
    assert recent["status"] == "success"
    assert "Attention Is All You Need" in recent["content"]

    annotations = json.loads(await tools["zotero_get_annotations"]("ITEM123"))
    assert annotations["status"] == "success"
    assert annotations["count"] == 1
    assert "## Annotations (1 total)" in annotations["content"]
    assert "Scaled dot-product attention." in annotations["content"]

    notes = json.loads(await tools["zotero_get_notes"]("ITEM123"))
    assert notes["status"] == "success"
    assert notes["notes"] == ["<p>Read again before writing.</p>"]
    assert notes["content"] == "<p>Read again before writing.</p>"
