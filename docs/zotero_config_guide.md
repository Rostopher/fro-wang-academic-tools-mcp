# Zotero Configuration Guide

This guide explains how to configure Zotero for `fro-wang-academic-tools-mcp`. You can use either **Remote Mode** (via Zotero Web API) or **Local Mode** (via local Zotero desktop app).

## Option A: Local Zotero (Recommended for Desktop Users)

If you have the Zotero desktop application running on your machine, you can simply use the local mode.

1. Ensure Zotero is open and running on your computer.
2. Install the [Better BibTeX for Zotero](https://retorque.re/zotero-better-bibtex/) extension if you haven't already (required for some advanced local features).
3. In your `.env` file, set:

```env
ZOTERO_LOCAL=true
```
*(Note: When `ZOTERO_LOCAL=true`, you do not need to configure the API key or Library ID).*

---

## Option B: How to Get Zotero Remote API Credentials (for `.env`)

To use Zotero’s Web API (Remote Mode), you’ll need three values:

* `ZOTERO_LIBRARY_ID`
* `ZOTERO_LIBRARY_TYPE` (`user` or `group`)
* `ZOTERO_API_KEY`

> You must **log in to Zotero on the web first** before you can create or view API keys.

### 1) Sign in to Zotero Web

1. Go to Zotero and sign in with your account:
   * `https://www.zotero.org/`

After you’re logged in, you can generate an API key.

### 2) Create / View Your API Key (`ZOTERO_API_KEY`)

1. Open the Zotero API Keys page:
   * `https://www.zotero.org/settings/keys`
2. If you already have a key, you can reuse it. Otherwise click **Create new key**.
3. Configure permissions (recommended):
   * Prefer **read-only** unless you truly need write access.
   * If you need to access a **Group library**, ensure the key is allowed for that group.
4. Copy the generated key — this is your `ZOTERO_API_KEY`.

✅ **Result:** `ZOTERO_API_KEY=...`

### 3) Decide Which Library You’re Accessing (`ZOTERO_LIBRARY_TYPE`)

Zotero supports two library types:

* Personal library: `ZOTERO_LIBRARY_TYPE=user`
* Group library: `ZOTERO_LIBRARY_TYPE=group`

✅ **Result:** `ZOTERO_LIBRARY_TYPE=user` **or** `ZOTERO_LIBRARY_TYPE=group`

### 4) Find Your Library ID (`ZOTERO_LIBRARY_ID`)

#### A) Personal library (`user`)

Your personal library ID is your **numeric userID** (not your username).

* You can find your **userID** on the API Keys page:
  * `https://www.zotero.org/settings/keys`

Copy that number and set it as `ZOTERO_LIBRARY_ID`.

✅ **Result:** `ZOTERO_LIBRARY_ID=<your_user_id>`

#### B) Group library (`group`)

Your group library ID is the **numeric groupID**.

How to get it:

1. Open your Zotero Group page in the browser.
2. The URL will contain a number like:
   * `https://www.zotero.org/groups/<groupID>/...`

That `<groupID>` number is your `ZOTERO_LIBRARY_ID`.

✅ **Result:** `ZOTERO_LIBRARY_ID=<your_group_id>`

### 5) Example `.env` Configurations

#### Personal library

```env
ZOTERO_LOCAL=false
ZOTERO_LIBRARY_TYPE=user
ZOTERO_LIBRARY_ID=12345678
ZOTERO_API_KEY=your_zotero_api_key
```

#### Group library

```env
ZOTERO_LOCAL=false
ZOTERO_LIBRARY_TYPE=group
ZOTERO_LIBRARY_ID=1451247
ZOTERO_API_KEY=your_zotero_api_key
```

### Security Notes

* Treat `ZOTERO_API_KEY` like a password.
* **Do not commit** your `.env` file to GitHub.
* Add `.env` to `.gitignore`.
* Use **minimum required permissions** (read-only is safest).
