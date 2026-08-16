# NeuroMita 0.1 Alpha

<p align="center">
  🌐 <a href="README.md">Русский</a> · <b>English</b>
</p>

NeuroMita is a fan-made mod project where you can talk to Mitas controlled by language models and see their reactions in a Unity scene. The current version is a standalone Unity build: MiSide does not need to be installed, and the release includes everything required to run it.

<p align="center">
  <a href="https://github.com/VinerX/NeuroMita/releases"><img src="https://img.shields.io/badge/Download-0.1%20Alpha-6f42c1?style=for-the-badge&logo=github&logoColor=white" alt="Download NeuroMita"></a>
  <a href="https://discord.gg/Tu5MPFxM4P"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="docs/MODELS_EN.md"><img src="https://img.shields.io/badge/Set%20up%20a%20model-2563eb?style=for-the-badge&logo=readthedocs&logoColor=white" alt="Set up a model"></a>
  <a href="docs/TROUBLESHOOTING_EN.md"><img src="https://img.shields.io/badge/Troubleshooting-d97706?style=for-the-badge&logo=discourse&logoColor=white" alt="Troubleshooting"></a>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/4d134e73-3d3f-41b7-a4c0-09a4c5590439" alt="NeuroMita" width="820">
</p>

> [!IMPORTANT]
> NeuroMita is in Alpha: the interface, mechanics, and data formats may change. Before a major update, save the `Settings` and `Histories` folders.

## Quick start

| Step | What to do |
| --- | --- |
| **1. Download** | Download the latest ZIP from the [releases page](https://github.com/VinerX/NeuroMita/releases) and extract it to a separate folder. |
| **2. Launch** | Open `Launcher.exe`; if the launcher does not start, use `run.bat`. |
| **3. Connect an LLM** | Create an API preset in **Settings → API presets** and make it active. |
| **4. Start a chat** | Choose a character in **Settings → Characters**, then return to Chat / Sandbox. |

> [!TIP]
> Start with one LLM provider. Voice output, local models, RAG, and other optional features can be added later.

### Installation and updates

On the first launch, NeuroMita checks and deploys its bundled Python dependencies. Do not close the window until this step is complete.

On the home page, install the Unity part if the interface offers it, then click **Play**.

Updates are installed from the home page: select the required components and click **Update**. Do not extract a new ZIP over a running NeuroMita folder.

### Setting up the first chat

1. Open **Settings → API presets**.
2. Click **+** or the “Click to create a preset” row.
3. Select a provider template, enter the API key and model.
4. Save the preset and make it active.
5. Open **Settings → Characters**, then choose a character and prompt set.
6. Return to Chat / Sandbox and send your first message.

Choose **one** provider to start with instead of configuring them all. **OpenRouter** is usually the simplest first choice; Google AI Studio, Mistral, and LM Studio are alternatives. See the [model setup guide](docs/MODELS_EN.md) for details, including options for users in Russia.

Users in Russia may need a VPN to access some foreign AI services. Availability depends on the provider and region.

If there is no response, check the active preset, model name, and provider balance/limits, then open the [troubleshooting guide](docs/TROUBLESHOOTING_EN.md).

## What NeuroMita can do

- Talk to Mitas through language models (LLMs — neural networks that generate text responses).
- Use history, memory, RAG, and a knowledge graph to keep track of previous conversations.
- Connect model responses to actions and character state in the Unity scene.
- Provide voice output and microphone input; local components are managed through AI Hub.
- Use images, screen content, or a camera as additional context when supported by the model.
- Store API presets, models, dialogue settings, and prompts in the application settings.

Some features require additional downloads or more powerful hardware. Start with a regular text chat — one connected LLM provider is enough.

## System requirements

| Component | Requirement |
| --- | --- |
| OS | Windows 10 or Windows 11 |
| Internet | First launch, updates, and cloud language models |
| Cloud LLM | API key from the selected service |
| Local LLM | LM Studio and sufficient computer resources |
| Voice output and ASR | Additional models and dependencies; a compatible GPU is often useful for acceleration |

Specific local voice requirements depend on the selected model. See the [local voice guide](docs/LocalVoiceInstallationEn.md).

> [!NOTE]
> Do not install Python, .NET, or MelonLoader separately: the current release includes the bundled Python runtime and the main runtime required by the application.

## Additional features

### Voice output and speech recognition

Use **Settings → Voice** to enable voice output and **Settings → Microphone** to select an input device and speech recognition. Local voice models, ASR, and related dependencies are installed through **AI Hub**. See the [step-by-step local voice guide](docs/LocalVoiceInstallationEn.md).

### Images, screen, and camera

When needed, NeuroMita can use an image, screen content, or camera input as additional context for a response. Availability depends on the selected model and its settings.

### AI Hub

**AI Hub** is the built-in area for installing and updating local components, including voice models, ASR, and related dependencies. A regular text chat does not require local components.

### Conversation memory

NeuroMita stores conversation history and can retain important context during long chats. When a conversation becomes too long for the model context window, the system compresses older messages into a short summary in the background while keeping recent messages available.

RAG can find relevant fragments from history and memories, while the knowledge graph connects entities and relationships. This is optional fine-tuning: a regular chat works with the default memory system. See the [RAG and knowledge graph guide](docs/RAG_Guide_EN.md).

## Getting help

- Read [TROUBLESHOOTING_EN.md](docs/TROUBLESHOOTING_EN.md) for common symptoms, HTTP errors, and local component checks.
- Open the **Logs** section in the application or inspect `NeuroMitaLogs.log` in the NeuroMita folder.
- If the issue remains, contact the [NeuroMita Discord](https://discord.gg/Tu5MPFxM4P). Include the NeuroMita version, provider and model, reproduction steps, a screenshot, and the relevant log fragment. **Never publish API keys.**

## Team and acknowledgements

### Current team

- **VinerX** — project author.
- **[Atm4x](https://github.com/Atm4x)** (`_atm4x`) — lead developer and chief architect of the new version of the mod.
- **[mactep_kot_](https://github.com/Macter-Kot)** — focused Python and Unity fixes, prompting, and testing.

<details>
<summary>Contributors to earlier stages</summary>

- **[ejichek](https://github.com/Ejichek0)** — major contribution to the Unity build, including the death screen.
- **[vlad2830](https://github.com/vlad2830)** — C# MelonLoader mod and Python parts.
- **Nelxi** (`distrane25`) — Python voice input integration.
- **Feanor** (`feanorqq`) — Kind Mita house setup.

</details>

<details>
<summary>Animations and characters</summary>

- **JPAV** — Mita prefab setup.
- **MaxDel** (`max.del`) — Mita animations.
- **Feanor** (`feanorqq`) and **Tkost** — Kind Mita prompts.
- **Josefummi** — Short-Haired Mita.
- **gad991** — Cap Mita.
- **depikoov** — Sweet Mita.
- **DemoNicanT** (`demonicant`) — Ghost Mita.

Thank you to **smarkloker**, author of New Story Mod, for cooperation and sharing experience. We wish him success with the upcoming alpha. Thanks to **GermanPlaygroud** and all testers who help find bugs and anomalies.

</details>

<details>
<summary>Special thanks</summary>

- **Sutherex** — introduced OpenRouter, helps with organisation and neural-network topics, and created the logo.
- **Dr. Couch Science** — one of the earliest testers of the chatbot; helped with many ideas, advice, and administration.
- **Romancho** — helps structure many ideas, moderates the community, and answers questions.
- **FlyOfFly** — useful Unity advice and early text-input work.
- **LoLY3_0** — the cat on a watermelon.
- **Mr. Sub** — his video helped many people discover the project.
- All early testers after the video release, especially **smarkloker**.
- **スノー** (`v1nn1ty`) and the **CrazyMitaBot** project — pull requests, bot communication, and contributions that improved voice availability in 2025.
- **KASTA**.

</details>

**Special thanks to Fluttershy-2013** for the largest contribution in the available support statistics.

<details>
<summary><strong>Top supporters</strong></summary>

This ranking is based on the total subscription amount in the available support statistics; the order may change over time.

1. **Fluttershy-2013**
2. **shr3der4**
3. **Rob Plushie**
4. **Hitakoto**
5. **Just Lucky**
6. **Neo**
7. **Sans**
8. **Артём Шестаков**
9. **ForumCore**
10. **Василий Бобраков**

</details>

### Support the project

[Boosty VinerX](https://boosty.to/vinerx)

<details>
<summary>Cryptocurrency addresses</summary>

- Ethereum (ETH), USDT (ETH): `0xd1b91ff711f1315053f3C89EB9256eABF3Ee0377`
- USDT (TRON), Tron (TRX): `THi7QcfNyEmnaRzzoCpM6wyhhxvPBb5mJg`
- Bitcoin (BTC): `bc1q3df4zlv40dhkhuq2asmh4we9jvqlnemey5u4cw`

</details>

If you would like to support the project with another cryptocurrency, message VinerX privately on Discord.

## Important rights information

NeuroMita is an independent fan project. The licence in this repository applies only to the code and documentation for which the NeuroMita team has rights. It does not grant rights to MiSide, its characters, models, textures, music, trademarks, or other third-party materials.

Unity source files are not published because they contain or depend on MiSide materials that the NeuroMita team is not entitled to distribute. See the full terms in [Licence.md](Licence.md).
