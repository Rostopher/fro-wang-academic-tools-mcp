# Zotero Local Read-Only Configuration Guide

This MCP provides a lightweight **local read-only** Zotero integration.

It uses Zotero Desktop's local HTTP API to read your library. It does not write to Zotero, does not create notes, and does not require a custom Zotero plugin.

## Scope

Supported:

- Search Zotero items
- Read item metadata
- Read indexed full text or local attachment text
- List collections
- List collection items
- List tags
- List recently modified items
- Read annotations
- Read notes

Not supported:

- Creating notes
- Editing items
- Deleting items
- Uploading attachments
- Any other write operation

## Configure Local Zotero

1. Open Zotero Desktop.
2. Enable Zotero's local HTTP server / local API access in Zotero settings.
3. In this project's `.env`, set:

```env
ZOTERO_LOCAL=true
```

When `ZOTERO_LOCAL=true`, you do not need a Zotero web API key for the supported read-only tools.

## Better BibTeX

Better BibTeX is optional.

The project can read annotations through Zotero's local API fallback. Some Better BibTeX-specific paths are diagnosed separately. If diagnostics report `better_bibtex_unavailable`, Zotero's local API is running, but the Better BibTeX endpoint is not available.

## Why Read-Only?

Zotero Desktop's local HTTP API is suitable for lightweight read access. Local write support usually requires a Zotero plugin or another write-capable local backend. This project intentionally avoids that complexity for now.

If write support is needed later, it should be added as a separate design decision, not hidden behind the current read-only tools.
