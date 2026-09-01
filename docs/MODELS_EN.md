# Model setup for NeuroMita

> **Checked: September 1, 2026.** Models, prices, free quotas, and regional availability change frequently. Always check the provider page and the model list inside NeuroMita before choosing a service.

**LLM (Large Language Model)** is a neural network that reads your text and generates a response. In NeuroMita, you connect an LLM through a provider or a local server.

## If you do not want to compare providers

Choose **one** of these paths — they do not need to be configured in sequence:

1. **Google AI Studio** — the recommended first option: direct access to Gemini models when the service is available for your country and account. Gemini 3.1 Flash-Lite and Gemini 3.5 Flash-Lite are good free starting choices.
2. **OpenRouter** — one key and a catalogue of many model families, including [free text models](https://openrouter.ai/models?max_price=0&output_modalities=text/).
3. **Mistral** — direct Mistral API with a separate key.
4. **LM Studio** — a fully local option: no key is required, but the model must be downloaded and running on your PC.

All options use the same flow in the app: **Settings → API presets → +** → choose a template → enter the key and model → save → make the preset active. Then send a short message in chat. A successful response is the best connection check.

Do not paste a key into a message, screenshot, public log, or repository. If a key is exposed, revoke it with the provider and create a new one.

## Russia: access through a VPN

Some foreign AI services may be unavailable from Russia or for Russian accounts. In that case, a VPN may be required to access the service. Follow the service rules and the applicable requirements in your country.

## Paid options

Paid APIs usually provide more stable access than free quotas. Always monitor the price of the selected model and your remaining balance: the cost depends on the model, response length, and context size.

Choose the service that fits you and create only that provider preset:

- **OpenRouter** — one key and a large model catalogue. For paid models, add funds in the [OpenRouter dashboard](https://openrouter.ai/credits). The service officially accepts bank cards, Alipay, and USDC; if direct payment is unavailable, some users use a third-party payment service. Check the intermediary's reputation, fee, and refund policy first: NeuroMita does not guarantee any particular intermediary.
- **ProxyAPI** — a paid Russian API preset in NeuroMita. The old project documentation mentioned the one-time 25% promo code `NeuroMita26`; before paying, check in the [ProxyAPI dashboard](https://console.proxyapi.ru/) whether the offer is still valid.
- **KodikRouter** — a Russian OpenAI-compatible gateway with rouble payments and one API key. The app includes a **KodikRouter** template; check current [models](https://kodikrouter.ru/models) and [prices](https://kodikrouter.ru/pricing) on the service website.

## Google AI Studio

This path uses the Gemini API directly.

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and create an API key.
2. In NeuroMita, create a **Google AI Studio** preset.
3. Paste the key into the API key field and choose a model from the preset list or the [official Gemini model list](https://ai.google.dev/gemini-api/docs/models).
4. Save the settings and test the connection in chat.

For a free start, we recommend:

- `gemini-3.1-flash-lite` — Gemini 3.1 Flash-Lite;
- `gemini-3.5-flash-lite` — Gemini 3.5 Flash-Lite.

The free tier currently allows up to 500 requests per day for each of these models. Quotas apply to the project, reset at midnight Pacific time, and can differ by account or region, so check them in [Google AI Studio](https://aistudio.google.com/) and the [official rate-limit documentation](https://ai.google.dev/gemini-api/docs/rate-limits).

New Google AI Studio keys may have current limits and authorisation requirements. Do not use old instructions that edit the system `hosts` file; that is not part of the current NeuroMita setup. See the [official API key documentation](https://ai.google.dev/gemini-api/docs/api-key).

## OpenRouter

OpenRouter combines many models and providers behind one OpenAI-compatible API. NeuroMita includes a dedicated template with routing settings.

1. Register at [OpenRouter](https://openrouter.ai/).
2. Create a key on the [Keys page](https://openrouter.ai/keys). The key is shown only when it is created, so store it safely.
3. In NeuroMita, create an API preset from the **OpenRouter** template.
4. Paste the key and choose a model from the [free text-model catalogue](https://openrouter.ai/models?max_price=0&output_modalities=text/), or use the model name suggested by the template.
5. Save the preset and send a test message.

Some models have free access, but the list and limits change. Prices, availability, and restrictions are shown in the OpenRouter catalogue and account. See the [official Quickstart](https://openrouter.ai/docs/quickstart) and [limits FAQ](https://openrouter.ai/docs/faq).

## Mistral

1. Create an account in [Mistral Studio](https://console.mistral.ai/api-keys/).
2. Create an API key. The provider shows the key value once.
3. In NeuroMita, choose the **Mistral AI** template, paste the key, and specify a model.
4. Check the current models in the [Mistral documentation](https://docs.mistral.ai/models/).

Access may require activating Studio or adding a payment method, depending on the account and region. See the [Mistral API Quickstart](https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request).

## LM Studio: local model

LM Studio runs a local model and provides an OpenAI-compatible server. Text does not go to a cloud LLM provider, but speed, memory use, and quality depend on the model and your computer.

1. Install [LM Studio](https://lmstudio.ai/) and download a suitable model.
2. Load the model in LM Studio and start the local server. The NeuroMita template expects `http://127.0.0.1:1234/v1/chat/completions` by default.
3. In NeuroMita, create an **LM Studio** preset.
4. Enter the model name exactly as it is returned by the local server. A local server usually does not need an API key; if LM Studio is configured differently, fill the field according to its settings.
5. Make sure LM Studio is running, then send a message from NeuroMita.

If the connection fails, check that the server is running, the port matches, and the firewall is not blocking it. See the official [LM Studio OpenAI compatibility documentation](https://lmstudio.ai/docs/developer/openai-compat).

## Other application templates

The current interface also includes presets for Ai.iO, ProxyAPI, Groq, Together AI, Chutes, KodikRouter, and Ollama, as well as a generic OpenAI-compatible template. They are intended for users who already know their endpoint and model.

For any such provider, use the key and URL from its official documentation. If the service returns HTTP 401, 403, or 429, see [troubleshooting](TROUBLESHOOTING_EN.md#the-cloud-model-does-not-respond).

## How to choose a model

There is no single best model for every character and scenario. Start with an available stable option and evaluate a few short conversations:

- naturalness and character consistency;
- response speed;
- quality of the language you use;
- cost and limits;
- support for required features, such as images or tools.

Save a good choice as a separate API preset so you can switch quickly without overwriting keys and parameters.
