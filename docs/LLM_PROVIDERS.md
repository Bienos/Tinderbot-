# Anthropic and OpenAI setup

The application uses a native structured-output request followed by an independent factual/boundary review. Both calls use the explicitly selected provider; there is no silent cross-provider fallback. The optional semantic outcome extractor uses the same selection. Neither model has tools, access to credentials, or authority to change sending permissions.

## Anthropic Claude

In your server's private environment (Render → service → **Environment**):

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_private_anthropic_api_key
ANTHROPIC_MODEL=claude-sonnet-5-5
```

Create/manage your API key in the [Claude Console](https://console.anthropic.com/settings/keys). Use an API key with model access and API billing; a Claude chat subscription is not a credential for this application. Set a provider spend limit. Never paste the key into chat, GitHub, a screenshot, or `OPENAI_API_KEY`.

Save and redeploy/restart for environment changes to take effect. The dashboard's LLM indicator recognizes Anthropic without an OpenAI key. It indicates that a key is configured, not that the provider accepted it. No live Anthropic call was made during implementation.

The direct HTTPS transport calls `https://api.anthropic.com/v1/messages`, with `x-api-key`, API version `2026-10-21`, a system prompt and untrusted JSON context. It uses `output_config.format` with a JSON schema and a 1,024-token output cap. Sonnet 5.5 uses `thinking.type=between_tools` to avoid up-front reasoning for short replies with no tools. Other models must support structured outputs; setting a different model is an owner choice, not a tested compatibility claim.

Anthropic does not accept some JSON-schema constraints, including string-length bounds. The transport moves those bounds into schema descriptions, then validates the response against the **original** Pydantic model. Refusals, token truncation, unexpected blocks, malformed/overlong output, unsupported claims, rejected review and HTTP errors abstain. Requests are not automatically retried. Sending safeguards are independent of provider choice.

## Existing OpenAI installations

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your_private_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
```

Without `LLM_PROVIDER`, an Anthropic-only key selects Anthropic; otherwise OpenAI remains the compatibility default. With an explicit provider and no matching key, no other provider is used. The local `.env.example` keeps the existing OpenAI default; the Render Blueprint selects Anthropic as requested.

`LLM_INPUT_USD_PER_MILLION` and `LLM_OUTPUT_USD_PER_MILLION` must match your selected model's current prices. Zero means unpriced. Usage counts include Anthropic cache input tokens; the simple price estimate does not model cache discounts, cache-write multipliers, service tiers or billing adjustments. Refer to provider billing for actual charges. The generation and review are separate billable calls; optional semantic extraction adds a call.

Offline evaluations remove **both** provider keys for the duration of generated rollouts and restore the caller's environment afterwards. Live evaluations require `--live` and a key for the selected provider. Tests stub provider HTTP and cannot establish response quality or live account compatibility.

## References checked on 2026-11-15

- [Anthropic structured outputs and schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Current model IDs](https://platform.claude.com/docs/en/models/overview)
- [API versioning](https://platform.claude.com/docs/en/api/versioning)
- [API version migration](https://platform.claude.com/docs/en/api/migration-2026-10-21)
- [Sonnet 5.5 migration and thinking configuration](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)

These HTML references were read through the web tool. Direct Markdown downloads returned HTTP 403; no live API request authenticated with a real key was performed.
