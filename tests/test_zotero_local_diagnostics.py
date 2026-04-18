from __future__ import annotations

import pytest
import requests

from academic_tools.zotero.bibtex_client import ZoteroBetterBibTexAPI


def test_bbt_connection_error_explains_zotero_must_be_open_and_local_api_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_connection_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", raise_connection_error)

    client = ZoteroBetterBibTexAPI(port="23119")
    with pytest.raises(RuntimeError) as exc_info:
        client._make_request("item.search", ["transformer"])

    message = str(exc_info.value)
    assert "Zotero desktop app is not running" in message
    assert "Enable HTTP server" in message
    assert "Better BibTeX" in message
    assert "127.0.0.1:23119" in message


def test_bbt_probe_reports_port_occupied_by_non_zotero_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        text = "not zotero"

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())

    client = ZoteroBetterBibTexAPI(port="23119")
    diagnosis = client.diagnose_connection()

    assert diagnosis["status"] == "error"
    assert diagnosis["reason"] == "port_occupied"
    assert "127.0.0.1:23119" in diagnosis["message"]
    assert "another process" in diagnosis["message"]


def test_bbt_probe_reports_zotero_without_better_bibtex_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        text = "No endpoint found"

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())

    client = ZoteroBetterBibTexAPI(port="23119")
    diagnosis = client.diagnose_connection()

    assert diagnosis["status"] == "error"
    assert diagnosis["reason"] == "better_bibtex_unavailable"
    assert "Zotero local API responded" in diagnosis["message"]
    assert "Better BibTeX endpoint was not found" in diagnosis["message"]


def test_bbt_probe_reports_zotero_closed_or_local_api_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_connection_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "get", raise_connection_error)

    client = ZoteroBetterBibTexAPI(port="23119")
    diagnosis = client.diagnose_connection()

    assert diagnosis["status"] == "error"
    assert diagnosis["reason"] == "unreachable"
    assert "Open Zotero desktop first" in diagnosis["message"]
    assert "Enable HTTP server" in diagnosis["message"]
