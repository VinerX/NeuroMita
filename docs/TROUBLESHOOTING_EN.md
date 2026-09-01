# Troubleshooting

## Before looking for a specific error

1. Restart NeuroMita and, if you use local models, LM Studio, or another local server, restart that service too.
2. Make sure the required API preset is active and that it contains an existing model.
3. Open **Logs** in the app or inspect `NeuroMitaLogs.log` in the NeuroMita folder.

## The app does not start or the first launch is stuck

On the first launch, the launcher installs the main Python dependencies into the bundled runtime. This requires an internet connection, free disk space, and write access to the NeuroMita folder.

- Run `Launcher.exe` from the extracted folder, not from a ZIP archive.
- If the launcher does not open, use `run.bat` from the same folder.
- Do not move or delete `libs`, `Lib`, `Settings`, `run.py`, or `NeuroMita.pyz` during installation.
- Check whether antivirus software blocked an application file. Restore it and add the release folder to exclusions only after verifying the archive source.

If this does not help, attach the beginning of `NeuroMitaLogs.log` and the text from the launcher window.

## Unity does not install or start

On the **Home** page, NeuroMita shows the status of the backend and Unity components separately.

### Should I keep the launcher open while Unity is running?

Yes. Keep the NeuroMita launcher open while playing: it runs the backend and maintains Unity's connection to the AI. You can minimize the window.

- If Unity is missing, select its installation and click the main button.
- If an update is available, select the required component and click **Update**.
- Close an already running Unity game before updating.
- Do not extract a new version over a running program.

Installation verifies the archive and can recover after an interruption. If the operation repeats after a restart, wait for it to finish or attach the log instead of deleting temporary service folders manually.

## The cloud model does not respond

First check whether the preset is active and whether the API key and model fields are filled in correctly for the selected provider template.

| Symptom or text | What it means | What to do |
| --- | --- | --- |
| `401 Unauthorized`, `invalid API key`, `Incorrect API key` | The key is missing, incorrect, revoked, or belongs to another service. | Create or copy a key in the correct provider dashboard and paste it into the active preset. Do not add the key to a URL manually. |
| `403 Forbidden` | The key or account has no access to the model, region, or feature. | Check the account status, selected model, and provider terms. |
| `429 Too Many Requests`, `rate limit` | A request or token limit has been exceeded. | Wait, reduce request frequency, switch models, or check the provider limit/balance. |
| `404`, `model not found`, `not available` | The model name is wrong or outdated, or the model is unavailable to the account. | Choose a model from the provider's current list and save the preset. |
| `402 Payment Required`, `insufficient credits` | A balance or payment method is required. | Check provider billing or choose another available option. |
| Timeout, `ConnectionError`, `ConnectError` | The API is unreachable, the service is unavailable, or the URL is incorrect. | Check the internet connection, template URL, VPN/proxy, and provider status page. |

For OpenRouter, Google AI Studio, Mistral, and LM Studio, use the [model setup guide](MODELS_EN.md).

## LM Studio or another local server does not connect

- Start the server before sending a request from NeuroMita.
- Check the endpoint and port. The LM Studio template uses `127.0.0.1:1234` by default.
- Make sure a model is loaded in LM Studio and that the preset model name matches the name returned by the server.
- Check the firewall or another process using the port.

If the local model works but responds very slowly, this is usually a CPU/GPU, VRAM/RAM, or model-size limitation. Try a smaller model or context and check that LM Studio is using the expected device.

## No voice output or the local voice model will not install

1. Open **Settings → Voice** and make sure voice output is enabled.
2. Open **AI Hub** and check that the selected components and model are installed.
3. Check the compute device: an incorrect CPU/CUDA/DML mode can make initialisation very slow or cause an error.
4. During the first installation, wait for downloading and extraction to finish; do not close the app.

See the [local voice guide](LocalVoiceInstallationEn.md). If the model does not start, include its name, the selected compute device, and the relevant installation log fragment.

## The microphone does not work

- Check the app's microphone permission in Windows settings.
- In **Settings → Microphone**, select the correct device and refresh the device list.
- If the log contains `ASR model is not installed. Install it via AI Hub.`, install a speech-recognition model in **AI Hub**.
- Close other applications that may have exclusive access to the microphone, then restart NeuroMita.

## RAG, memory, or the knowledge graph does not work

- Make sure RAG is enabled in the relevant settings.
- After enabling it, the local embedding model may need to download and load; the first start takes longer.
- Check that the history already contains messages: RAG cannot retrieve anything from an empty conversation.
- If the context is irrelevant, reduce the number of results or raise the similarity threshold.

See the [RAG and knowledge graph guide](RAG_Guide_EN.md).

## How to report a problem

If these suggestions do not help, contact the [NeuroMita Discord](https://discord.gg/Tu5MPFxM4P). A useful report includes:

1. NeuroMita version;
2. Windows version and PC specifications when the issue concerns local components;
3. provider and model;
4. steps that reproduce the issue;
5. an error screenshot;
6. a relevant fragment of `NeuroMitaLogs.log`.
