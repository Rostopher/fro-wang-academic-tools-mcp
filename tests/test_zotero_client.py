from __future__ import annotations

import json

import pytest

from academic_tools.tools import zotero as zotero_tools
from academic_tools.zotero import client as zotero_client


class _CapturingMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _registered_tool(name: str):
    mcp = _CapturingMCP()
    zotero_tools.register(mcp)
    return mcp.tools[name]


def test_get_zotero_client_rejects_non_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(zotero_client.settings, "ZOTERO_LOCAL", False)

    with pytest.raises(ValueError, match="local read-only"):
        zotero_client.get_zotero_client()


def test_get_zotero_client_local_mode_uses_default_local_library_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeZotero:
        def __init__(
            self,
            library_id: str,
            library_type: str,
            api_key: str | None,
            local: bool,
        ) -> None:
            captured.update(
                {
                    "library_id": library_id,
                    "library_type": library_type,
                    "api_key": api_key,
                    "local": local,
                }
            )

    monkeypatch.setattr(zotero_client.settings, "ZOTERO_LOCAL", True)
    monkeypatch.setattr(zotero_client.zotero, "Zotero", FakeZotero)

    zotero_client.get_zotero_client()

    assert captured == {
        "library_id": "0",
        "library_type": "user",
        "api_key": None,
        "local": True,
    }


@pytest.mark.asyncio
async def test_zotero_search_items_returns_structured_error_when_client_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_connection_error():
        raise ConnectionError("Zotero is not reachable")

    monkeypatch.setattr(zotero_tools, "get_zotero_client", raise_connection_error)

    search_items = _registered_tool("zotero_search_items")
    raw = await search_items("transformer", limit=5)
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert "Zotero is not reachable" in payload["error"]


@pytest.mark.asyncio
async def test_zotero_search_items_returns_json_success_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeZotero:
        def items(self, q: str, limit: int):
            assert q == "transformer"
            assert limit == 5
            return []

    monkeypatch.setattr(zotero_tools, "get_zotero_client", lambda: FakeZotero())

    search_items = _registered_tool("zotero_search_items")
    raw = await search_items("transformer", limit=5)
    payload = json.loads(raw)

    assert payload == {"status": "success", "items": []}
