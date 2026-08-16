# NeuroMita v0.011  
A mod where you get to interact with Mitas controlled by neural networks. Built with Python and C# MelonMod.  

Mod Server: https://discord.gg/Tu5MPFxM4P (Get help here!)  

![logomod3](https://github.com/user-attachments/assets/aea3ec44-c203-4d4a-a405-a09191188464)  

## User Wiki

For the current in-app functionality reference, see the [user wiki](./wiki/en/index.md).

# Installation Guide  

### 0) MelonLoader:  
A universal Unity modding tool. May conflict with BepInEx-based mods.  

- Install via: https://melonwiki.xyz/#/?id=requirements (Version 0.6.6)  
- Or directly from: https://github.com/LavaGang/MelonLoader  

If you have **MelonLoader.Installer.exe**, select **Miside** to patch it for Melon-based mods.  
Ensure all dependencies (e.g., .NET 6.0) are installed: https://melonwiki.xyz/#/?id=requirements  

### 1) The Mod  
The mod consists of:  
- **Python files** (place anywhere, but keep them together)  
- **C# files**: `MitaAI.dll` and `assetbundle.test` (place in the `Mods` folder created by MelonLoader).  

Final structure should look like:  

```
Miside  
- Other Miside folders  
- Mods (Create if needed)  
  - MitaAI.dll  
  - assetbundle.test  

Any Separate Folder  
- _internal  
- libs  
- Prompts  
- NeuroMita.exe  
(For local voice generation, also include:)  
- Models  
- features.env  
- include  
- init_triton.bat  
- init.py  
```  

Future versions may include a launcher.  

Download releases here: https://github.com/VinerX/NeuroMita/releases  
Actual release: https://github.com/VinerX/NeuroMita/releases/download/v0.011/NeuroMita.0.011.MitaWorld.7z

**In-game controls:**  
- Press **Tab** to start typing.  
- Press **Enter** to send.  

### 2) Text Generation  
The mod supports multiple text-generation methods (tested options listed below).  

#### Free API Options:  
- **g4f** (No API keys needed)  
- **OpenRouter** (Free keys: https://openrouter.ai/settings/keys – rate-limited)  
- **io.net** (Free keys: https://ai.io.net/ai/api-keys – 500k tokens/day per model)
- **Google AI Studio** (Free keys: https://aistudio.google.com/apikey – 1500 requests/day)  
- **Chutes.ai** (Free keys: https://chutes.ai/app/api unlimited?)

#### Paid API Options:  
- **OpenRouter** (Wide model selection, pay-per-use)  

#### Local Generation:  
- **LM Studio** (https://lmstudio.ai, requires strong hardware, for advanced users only)  

**Note:** Gemini models often handle emotions better, while GPT-4o is more precise but less expressive.  

### Models (as of 05/05/2025)  
*(Subject to rapid change—check Discord for updates!)*  

#### **G4F (No API Keys)**  
Good for testing, but weaker models. Enable the checkbox in the settings. If base model does not work, use button and reload.

![img_1.png](../assets/img_1.png)

Supported models (selectable via version input + restart):  
- `gemini-1.5-flash` (Most stable in 0.4.7.7)  
- `gpt-4o-mini`  
- `gpt-4o`  
- `gemini-2.0-flash`  
- `deepseek-chat`  
Full list: https://github.com/xtekky/gpt4free/blob/main/docs/providers-and-models.md  

#### **OpenRouter (Free/Paid Keys)**  
Get keys here: https://openrouter.ai/settings/keys  

![img_2.png](../assets/img_2.png)

Recommended free models:  
- `google/gemini-2.0-pro-exp-02-05:free`  
- `deepseek/deepseek-chat:free` (Best for "Kind Mita")  
- `deepseek/deepseek-chat-v3-0324:free` (Hardcore mode)  

Semi-paid (requires balance but no usage cost):  
- `google/gemini-2.5-pro-exp-03-25`  

Full list: https://openrouter.ai/models?max_price=0  

#### **Ai.iO (500k tokens/day per model)**  
API: https://api.intelligence.io.solutions/api/v1/  
- `meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8`  
Full list: https://docs.io.net/reference/get-started-with-io-intelligence-api  

### *Google Ai Studio*
First, go to this website: https://aistudio.google.com/. If it says your country is not supported (e.g., Russia), only then will you need Step 1. If you don’t have any regional restrictions, skip straight to Step 2.

To use it, you’ll need a file called "hosts" (find it on the server for now), which must be placed in this directory:
C:\Windows\System32\drivers\etc
Installation steps: Download → Copy → Paste with replacement.

Follow this exact order—do not move the file. THIS IS IMPORTANT, as bugs may occur otherwise.

After completing these steps, go to this website: https://aistudio.google.com/apikey, sign up, and generate an API key.

To use the model directly in the module, insert the gemini-2.0-flash model.

![image](https://github.com/user-attachments/assets/55c90501-b77d-416a-8073-cd97f9f620fb)

The key fields should remain empty because the key is embedded in the URL.
Also, make sure to enable two checkboxes in the module:

"Via Request"

"Gemini for ProxiAPI"

Most importantly, the URL should look like this:

https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=YOUR_GENERATED_KEY_HERE
Check the URL carefully—replace the placeholder text with your actual key.

### *Chutes.ai*
Need checkbutton "via Request", url https://llm.chutes.ai/v1/chat/completions
- model deepseek-ai/DeepSeek-V3-0324

Other models - https://chutes.ai/app

## 3) Voice Generation  
Two options: **Telegram bots** or **local generation**.  

### **Telegram**  
Uses your Telegram account (preferably a secondary one) as a bot. Requires `api_id` and `api_hash` (guide: https://core.telegram.org/api/obtaining_api_id).  

After setup, restart and enter the confirmation code sent to your Telegram account. If you have 2FA, enter it (invisible input).  

Available bots:  
- **@CrazyMitaAIbot** (Free, unstable)  
- **@silero_voice_bot** (Paid, 600 test characters)  

**Note:** Manually message the bots first to ensure connectivity.  

### **Local Voice Generation**  
Requires the `Models` folder and `features.env` (included in releases).  

- Download: https://github.com/VinerX/NeuroMita/releases/download/v0.011/Models.7z
- Mirror: https://drive.google.com/file/d/16S0v7qsVKGwqI1yHU_ScZ94wtZooIZqI/view?usp=drive_link

1. Enable voice generation.  
2. Select **Local** (requires `features.env`).  
3. Choose and configure a model.
*(Initial setup may take time due to downloads.)*

For model installation details, see [here](https://github.com/VinerX/NeuroMita/blob/main/docs/LocalVoiceInstallationEn.md)

![img_5.png](../assets/img_5.png)
---

### **Credits**  
**Developers:**  
- **VinerX**  
- **vlad2830** (C# & Python)  
- **Nelxi (distrane25)** (Voice input integration)  

**Local Voice Generation (Massive Contribution):**  
- **_atm4x**  

**Character Prompts:**  
- **Feanor (feanorqq)** & **Tkost** (Kind Mita)  
- **Josefummi** (Short-Haired Mita)  
- **gad991** (Cap Mita)  
- **depikoov** (Sweet Mita)  

**Animations (WIP):**  
- **JPAV**  

**Pull Requests & CrazyMitaBot Contact:**  
- **スノー (v1nn1ty)**  

**Testers (Brave Bug Hunters):**  
- **GermanPlaygroud**  

**Special Thanks:**  
- **Sutherex** (Introduced OpenRouter, organizational help)  
- **Dr. Couch Science** (Early tester, admin support)  
- **Romancho** (Idea organization, community moderation)  
- **FlyOfFly** (Unity advice, early text input help)  
- **LoLY3_0** (The cat on a watermelon 🍉)  
- **Mr. Sub** (Likely how you found this mod!)  
- **All early testers** (Especially **smarkloker**)  
- **KASTA**  

**Support the author (VinerX):** https://boosty.to/vinerx  

CryptoCurrency:

  - Ethereum (ETH) 0xd1b91ff711f1315053f3C89EB9256eABF3Ee0377
  - USDT (ETH) 0xd1b91ff711f1315053f3C89EB9256eABF3Ee0377
  - USDT (TRON) THi7QcfNyEmnaRzzoCpM6wyhhxvPBb5mJg
  - Tron (TRX) THi7QcfNyEmnaRzzoCpM6wyhhxvPBb5mJg
  - Bitcoin (BTC) bc1q3df4zlv40dhkhuq2asmh4we9jvqlnemey5u4cw

Write me in discord, if need address for other type.
