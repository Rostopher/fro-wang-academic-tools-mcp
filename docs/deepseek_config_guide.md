# DeepSeek API Configuration Guide

This project uses Large Language Models (LLMs) for metadata extraction, section parsing, translation, and summary generation. By default, it is configured to use **DeepSeek**, which provides excellent performance for academic text processing at a very low cost.

Here is how to configure your `.env` file to use DeepSeek.

## 1) Get Your DeepSeek API Key

1. Go to the DeepSeek API Platform:
   * `https://platform.deepseek.com/`
2. Sign in or create an account.
3. Navigate to the **API Keys** section in the left sidebar.
4. Click **Create new API key**.
5. Copy the generated key. This will be your `LLM_API_KEY`.

## 2) Configure `.env`

Open your `.env` file and set the following variables:

```env
# The API key you just generated
LLM_API_KEY=sk-your_deepseek_api_key_here

# DeepSeek's OpenAI-compatible base URL
LLM_BASE_URL=https://api.deepseek.com

# The model to use (deepseek-chat is recommended for general tasks)
LLM_MODEL=deepseek-chat
```

### Available DeepSeek Models

* `deepseek-chat` (DeepSeek-V3): Fast, highly capable, and extremely cost-effective. **Recommended** for metadata extraction, translation, and summarization.
* `deepseek-reasoner` (DeepSeek-R1): Includes advanced reasoning capabilities. Useful if you need deeper logical analysis of the paper content, though it may be slower and slightly more expensive.

## 3) Using Other OpenAI-Compatible Providers (Optional)

Because this project uses the standard OpenAI client under the hood, you can easily swap DeepSeek for any other OpenAI-compatible API (like OpenAI, Anthropic via proxy, OpenRouter, or local models via Ollama/vLLM).

**Example for OpenAI (ChatGPT):**
```env
LLM_API_KEY=sk-proj-your_openai_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

**Example for Local Ollama:**
```env
LLM_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3
```

## Security Notes

* **Never share your API key** or commit it to version control.
* Ensure your `.env` file is listed in `.gitignore`.
