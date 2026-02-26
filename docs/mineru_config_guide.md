# MinerU API Setup Guide (Token / Remote API)

This project supports **MinerU** as the default document/OCR parsing backend.

MinerU provides high-quality document parsing (PDF → Markdown/JSON, table extraction, formula handling, optional OCR for scanned docs). MinerU’s API uses a **Bearer token** for authentication and exposes REST endpoints under `https://mineru.net/api/v4`.

### 1) Create an account and request API access

1. Sign in on the MinerU website.
2. Go to the token management page and **fill out the short questionnaire / request form**.
3. After submitting the form, MinerU will issue you an **API token (API key)**.

Notes:
- According to the current MinerU console flow, you can apply for **up to 5 API tokens**.
- MinerU offers a **free daily quota** (quota resets daily; limits may vary by policy/plan).

> Token console (log in first):
> `https://mineru.net/apiManage/token`

### 2) Configure environment variables

This project uses a token file to manage MinerU tokens (which allows for easy rotation if you have multiple tokens).

1. Create a text file (e.g., `mineru_tokens.txt`) and paste your token(s) into it, one per line.
2. Set the path to this file in your `.env`:

```env
MINERU_TOKENS_FILE=~/.fro-wang-academic-tools-mcp/mineru_tokens.txt
MINERU_API_BASE=https://mineru.net/api/v4
```

*(Note: The system will automatically read the token from this file and construct the `Authorization: Bearer <token>` header for you).*

### 3) Limits and practical constraints (from MinerU docs)

MinerU documents a few important constraints you should keep in mind:

- **Max file size:** 200 MB per file
- **Max pages:** 600 pages per file
- **Batch URL submissions:** up to 200 URLs per request
- **Daily quota:** Typically around 2000 pages/day for free tiers (subject to change).

The `ocr_paper` tool in this project automatically handles these constraints by checking page counts before submission.

### 4) Security

- Treat your MinerU token like a password.
- **Never commit** your token file or `.env` to GitHub.
- Add `.env` and your token file to `.gitignore`.

---

## Using another OCR provider (e.g., Mistral OCR)

If you prefer, you can modify this repo’s source code to plug in another OCR provider.

For example, **Mistral OCR** provides an OCR endpoint at:
- `POST https://api.mistral.ai/v1/ocr`
- Auth: `Authorization: Bearer <MISTRAL_API_KEY>`

When adapting the code, the typical changes are:
- Replace the MinerU request builder in `src/academic_tools/tools/ocr.py`.
- Normalize the provider response into this project’s internal output format (Markdown).
