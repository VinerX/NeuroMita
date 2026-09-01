# Local voice output

Local voice output runs on your computer. It does not require a separate cloud API key, but models and dependencies may take additional disk space, and speed depends on your CPU and GPU.

## Before you start

- Use the current NeuroMita release on Windows.
- Make sure you have a stable internet connection for the first component download.
- Do not assume a fixed VRAM requirement: requirements depend on the selected voice model and are shown in AI Hub.
- Do not close the app or move its folder during installation.

## Installation

1. Open **Settings → Voice**.
2. Select a local voice source/model.
3. Open **AI Hub** or the local model manager from the voice settings.
4. Select a voice model, read its requirements, and click **Install**.
5. Wait for downloading, extraction, and initialisation to finish.
6. Select the installed model in voice settings and save the changes.

During the first initialisation, some models prepare an additional runtime or cache. This can take a while; later launches are usually faster.

## Choosing a compute device

If the setup offers a device choice, select one that is actually available:

- `CUDA` — NVIDIA GPU;
- `DML` — a supported DirectML option, often used with AMD;
- `CPU` — the most universal option, but usually the slowest.

Do not select CUDA just because it appears faster: without a suitable NVIDIA driver the model will not start. If you are unsure, start with the option that AI Hub marks as compatible.

## If something goes wrong

- Open **Logs** in the app or inspect `NeuroMitaLogs.log` in the NeuroMita folder.
- Include the voice model name, selected device, and the installation step where the error appeared.
- Check free disk space and the internet connection.
- For CUDA/DML/Torch-like errors, do not delete `Lib` folders or caches at random. First attach the exact log fragment in Discord.

For general recommendations and report format, see [TROUBLESHOOTING_EN.md](TROUBLESHOOTING_EN.md).
