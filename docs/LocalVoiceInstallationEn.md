## 🛠️ Setting up local models for voice synthesis - step-by-step guide

### 0. What you'll need beforehand
| What | Why |
| --- | --- |
| Fresh version of **NeuroMita.exe** | 0.011+ |
| Graphics card (NVIDIA/AMD) | Minimum tested and working - 1060 3gb and RX 580 |
| Stable internet | Models weigh from several hundred MB to several GB (future plans up to 80 GB) |
| 10-30 minutes of free time | Depends on network speed and graphics card. |

Note: if you have an Intel graphics card and want to help test local voice synthesis, please contact us on the Discord server: https://discord.gg/Tu5MPFxM4P

---

### 1. Open the model manager

1. Select source **`Local`** (local voice synthesis).
2. Click **"Manage local models"**.

![Open model manager](https://github.com/user-attachments/assets/31543a7a-37db-4389-99b2-d2a1e5033db1)

---

### 2. Find the needed model

In the window that appears, click on the model you want to install.

![List of available models](https://github.com/user-attachments/assets/547c86d2-6b57-4076-91fd-0bdceb9eb5e8)

#### Models and their requirements

##### Edge-TTS + RVC
| Parameter | Value |
|----------|----------|
| Size | 3 GB |
| Recommended VRAM | 3GB - 4GB |
| Supported languages | Russian, English |
| Devices | CUDA / DML / CPU |
| Min. tested graphics card | GTX 1060 3GB / RX 580 8 GB |
| Recommended graphics card | 16xx Ti/Super |
| Description | Most stable model. Best model for English language for weak/medium graphics cards. Works on principle: Edge TTS -> RVC (Retrieval-Based Voice Conversion) |

##### Silero + RVC
| Parameter | Value |
|----------|----------|
| Size | 3 GB + 50 MB Silero package |
| Recommended VRAM | 3GB - 4GB |
| Devices | CUDA / DML / CPU |
| Min. tested graphics card | GTX 1060 3GB / RX 580 8 GB |
| Recommended graphics card | 16xx Ti/Super |
| Recommended processor (FOR AMD) | Not determined |
| Description | Best model for Russian language for weak/medium graphics cards. Works on principle: Silero tts -> RVC (Retrieval-Based Voice Conversion) |

The models above are downloaded as a package since they depend on the same technology.

##### Fish Speech (regular)
| Parameter | Value |
|----------|----------|
| Size | 5 GB |
| Recommended VRAM | 4GB-6GB |
| Supported languages | Russian, English, Chinese, Japanese, German, French, Spanish, Korean, Arabic, Polish, Portuguese, Italian, Dutch |
| Devices | CUDA / CPU |
| Min. tested graphics card | RTX 4060 |
| Recommended graphics card | RTX 2080 Ti / RTX 4090 |
| Min. tested processor | I5 13600KF - speed slightly slower than RTX 4060 without compilation (`+` postfix). |
| Description | NOT RECOMMENDED FOR USERS WITH RTX 30xx+ GRAPHICS CARDS! USE THE (+) VERSION. Best model in the up to 6GB segment. Clones voice, repeats its style. Occasionally doesn't voice sentences due to architectural feature of the model. |

##### Fish Speech+
| Parameter | Value |
|----------|----------|
| Size | 5 GB + 2 GB compilation components |
| Recommended VRAM | 4GB-6GB |
| Supported languages | Russian, English, Chinese, Japanese, German, French, Spanish, Korean, Arabic, Polish, Portuguese, Italian, Dutch |
| Devices | CUDA / CPU |
| Min. tested graphics card | RTX 3060 |
| Recommended graphics card | RTX 4060+ |
| Min. tested processor | I5 13600KF - speed slightly slower than RTX 4060 without compilation (`+` postfix). |
| Description | Best model in the up to 6GB segment. Clones voice, repeats its style. Occasionally doesn't voice sentences due to architectural feature of the model. |

##### Fish Speech+ + RVC
| Parameter | Value |
|----------|----------|
| Size | 5 GB + 2 GB compilation components |
| Recommended VRAM | 6GB-8GB |
| Supported languages | Russian, English, Chinese, Japanese, German, French, Spanish, Korean, Arabic, Polish, Portuguese, Italian, Dutch |
| Devices | CUDA / CPU |
| Min. tested graphics card | RTX 3060 |
| Recommended graphics card | RTX 4060+ |
| Min. tested processor | I5 13600KF - speed slightly slower than RTX 4060 without compilation (`+` postfix). |
| Description | Currently the best model in the mod: Clones voice, repeats its style, processes it with Revoice (RVC) to reduce artifacts. SOTA for Russian language. |

The `Fish Speech+ + RVC` model also installs `Edge TTS + RVC` and `Silero + RVC` models since it depends on the same architecture.

---

### 3. Click "Install"

A window **"Installing model ..."** will appear - it will show download and extraction status.

---

### 4. Monitor the installation log
Installation will be long and errors are rare.

⚠️ If an error appears during the process - take a screenshot or copy the log text. Without it, it will be difficult to help.

---

### 5. Configure computing device

After successful installation, a settings window will appear:

![Device settings](https://github.com/user-attachments/assets/015fd799-001e-4ef7-a69b-2560ff2e7f40)

Choose what you actually have:

* `CUDA:0` - NVIDIA graphics card
* `DML` - AMD
* `CPU` - if there's no graphics card

Click **"Save"**.

---

### 6. Select and run the model

#### Option 1. Regular models
(Edge-TTS + RVC, Silero + RVC, Fish Speech)

1. In the main dropdown list, select the needed model.
2. A couple of seconds and you can start voice synthesis!

![Select regular model](https://github.com/user-attachments/assets/b4674fc7-0b30-401c-8e68-1c461b4412f0)

---

#### Option 2. Fish Speech+ (with phase correction) or Fish Speech+ + RVC

1. Select the model from the list.
2. Initialization will begin. Almost always on the **first** launch an error appears
   `name 'Config' is not defined` - this is **normal**, don't worry.
3. Completely close **NeuroMita.exe**.
4. Launch the program again and select the same model.
5. Wait for initialization to complete - now everything will work.

---

## If something went wrong

When asking for help, please specify:

1. **At which step** of the guide did the problem occur?
2. **PC specifications**: Windows/Linux/macOS, graphics card model (NVIDIA/AMD/Intel).
3. **Screenshots/logs**:
   * Error at step 4? - attach the log from the "Installing model ..." window.
   * Error `name 'Config' is not defined` with Fish Speech+? - if it disappears after restart, this is normal; if it remains - send a screenshot.

## Known issues:
```
AttributeError: module `torch` has no attribute `cuda`
```
Solution:
Delete the `/Lib/torch` folder and the folder with the same name but with version. Then restart `NeuroMita.exe` and installation will proceed.

---

### Very long initialization:
Solution:
Make sure you set `CUDA/DML` everywhere, otherwise it might work on the processor, hence taking so long.

---
### CalledProcessError: Command...
```
torch._dynamo.exc.BackendCompilerFailed: backend='inductor' raised: CalledProcessError: Command:
```
Solution:
1. Delete folders
   
   1.1) `C:/Users/<your_username>/.triton/cache`
   
   1.2) `C:/Users/<your_username>/AppData/Local/Temp/torchinductor_<your_username>`
3. Open the folder with `NeuroMita.exe` and run `init_triton.bat`
4. Wait for the script to complete
5. Launch `NeuroMita.exe` and select the model you were trying to run.
