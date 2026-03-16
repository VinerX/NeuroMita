using Il2Cpp;
using MelonLoader;
using MitaAI.Mita;
using MitaAI.PlayerControls;
using System;
using System.Collections;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine.UI;
using UnityEngine;
using System.Text.RegularExpressions;


namespace MitaAI
{
    static class DialogueControl
    {
        public static float voiceTimout = 30;
        
        const int simbolsPerSecond = 15;
        const float minDialoguePartLen = 0.50f;
        const float maxDialoguePartLen = 8f;
        const float delayModifier = 1.05f;

        public static GameObject CustomDialog;
        public static GameObject CustomDialogPlayer;
        public static bool dialogActive = false;

        public static EmotionType currentEmotion = EmotionType.none;

        public static IEnumerator DisplayResponseAndEmotionCoroutine(int id, characterType characterToSend, string response, AudioSource audioSource = null, bool voice = true)
        {
            while (dialogActive) { yield return null; }
            dialogActive = true;

            MelonLogger.Msg("DisplayResponseAndEmotionCoroutine");


            // Пример кода, который будет выполняться на главном потоке
            yield return null; // Это нужно для того, чтобы выполнение произошло после завершения текущего кадра

            string patch_to_sound = "";

            if (voice)
            {

                float elapsedTime = 0f; // Счетчик времени

                float waitingTimer = 0.75f;
                float lastCallTime = 0f; // Время последнего вызова

                // Ждем, пока patch_to_sound_file перестанет быть пустым или не истечет время ожидания
                while (string.IsNullOrEmpty(patch_to_sound) && elapsedTime < voiceTimout && NetworkController.connectedToSilero) //&& waitForSounds=="1")
                {
                    //MelonLogger.Msg("DisplayResponseAndEmotionCicle");
                    if (DataChange.sound_files.ContainsKey(id))
                    {
                        patch_to_sound = DataChange.sound_files[id];
                        DataChange.sound_files[id] = null;
                        break;
                    }


                    if (elapsedTime - lastCallTime >= waitingTimer)
                    {
                        //MelonLogger.Msg($"!responseTask.IsCompleted{elapsedTime}/{timeout}");
                        List<String> parts = new List<String> { "***" };
                        MelonCoroutines.Start(ShowDialoguesSequentially(characterToSend,parts, true));
                        lastCallTime = elapsedTime; // Обновляем время последнего вызова
                    }

                    elapsedTime += 0.1f; // Увеличиваем счетчик времени

                    yield return new WaitForSecondsRealtime(0.1f);             // Пауза до следующего кадра
                }

                yield return null;
                // Если время ожидания истекло, можно выполнить какой-то fallback-лог
                if (string.IsNullOrEmpty(patch_to_sound))
                {
                    MelonLogger.Msg("Timeout reached, patch_to_sound_file is still empty.");
                }
            }

            // После того как patch_to_sound_file стал не пустым, вызываем метод DisplayResponseAndEmotion
            yield return DisplayResponseAndEmotion(characterToSend,response, patch_to_sound, audioSource);

            dialogActive = false;
        }

        private static IEnumerator DisplayResponseAndEmotion(characterType characterToSend, string response, string patch_to_sound, AudioSource audioSource = null)
        {
            MelonLogger.Msg("DisplayResponseAndEmotion");


            string modifiedResponse = MitaMovement.FindMovementStyle(characterToSend,response);

            AudioClip audioClip = null;

            if (!string.IsNullOrEmpty(patch_to_sound))
            {
                try
                {
                    MelonLogger.Msg("patch_to_sound not null");
                    audioClip = NetworkController.LoadAudioClipFromFileAsync(patch_to_sound).Result;

                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error loading audio file: {ex.Message}");
                }
            }

            float delay = modifiedResponse.Length / simbolsPerSecond;

            if (audioSource != null) PlaySound(audioClip, audioSource);
            else MelonCoroutines.Start(PlayMitaSound(delay, audioClip, modifiedResponse.Length));


            List<string> dialogueParts = SplitText(modifiedResponse, maxLength: 70);

            // Запуск диалогов последовательно, с использованием await или вложенных корутин
            yield return MelonCoroutines.Start(ShowDialoguesSequentially(characterToSend,dialogueParts, false));


        }

        public static IEnumerator ShowDialoguesSequentially(characterType characterToSend,List<string> dialogueParts, bool itIsWaitingDialogue)
        {
            InputControl.BlockInputField(true);
            foreach (string part in dialogueParts)
            {

                string partCleaned = Utils.CleanFromTags(part); // Очищаем от всех тегов
                float delay = Math.Clamp(partCleaned.Length / simbolsPerSecond, minDialoguePartLen, maxDialoguePartLen);


                yield return MelonCoroutines.Start(ShowDialogue(characterToSend,part, delay, itIsWaitingDialogue));


            }
            if (!itIsWaitingDialogue && CommandProcessor.ContinueCounter > 0) CommandProcessor.ContinueCounter = CommandProcessor.ContinueCounter - 1;
            InputControl.BlockInputField(false);



        }
        public static IEnumerator PlayerTalk(string text)
        {
            GameObject currentDialog = null;


            float delay = Math.Clamp(text.Length / simbolsPerSecond, minDialoguePartLen, maxDialoguePartLen);

            currentDialog = InstantiateDialog(false);
            if (currentDialog != null)
            {

                try
                {
                    Dialogue_3DText answer = currentDialog.GetComponent<Dialogue_3DText>();
                    if (answer == null)
                    {
                        throw new Exception("Dialogue_3DText component not found.");
                    }

                    answer.speaker = MitaCore.Instance.playerPerson.gameObject;
                    answer.textPrint = text;
                    MelonLogger.Msg($"Player Text is {answer.textPrint}");
                    answer.themeDialogue = Dialogue_3DText.Dialogue3DTheme.Player;
                    answer.timeShow = delay;
                    addDialogueMemory(answer,characterType.Player);


                    currentDialog.SetActive(true);
                    DataChange.MitaBoringtimer = 0f;
                }
                catch (Exception ex)
                {
                    MelonLogger.Msg($"PlayerTalk: {ex.Message}");
                }

                yield return new WaitForSeconds(delay * 1.15f);

                Utils.DestroyAfterTime(currentDialog, (delay * 1.15f) + 5f);



            }
            else
            {
                MelonLogger.Msg("currentDialog is null.");
            }


        }


        private static IEnumerator ShowDialogue(characterType characterToSend, string part, float delay, bool itIsWaitingDialogue = false)
        {



            string modifiedPart = part;
            List<string> commands;
            EmotionType emotion = EmotionType.none;

            if (!itIsWaitingDialogue)
            {
                MelonLogger.Msg("ShowDialogue");
                try
                {

                    MelonLogger.Msg("Begin try:" + modifiedPart);
                    modifiedPart = MitaFaceAnimationModded.SetFaceStyle(modifiedPart);
                    modifiedPart = MitaClothesModded.ProcessClothes(modifiedPart);
                    modifiedPart = PlayerEffectsModded.ProcessPlayerEffects(modifiedPart);
                    modifiedPart = MitaAnimationModded.getMitaAnimationModded(characterToSend).setAnimation(modifiedPart);
                    modifiedPart = AudioControl.ProcessMusic(modifiedPart);
                    modifiedPart = CommandProcessor.ProcesHint(modifiedPart);
                    modifiedPart = ObjectAnimationMita.ProcessInteraction(modifiedPart);
                    (emotion, modifiedPart) = MitaFaceAnimationModded.SetEmotionBasedOnResponse(modifiedPart);
                    MelonLogger.Msg("After SetEmotionBasedOnResponse " + modifiedPart);

                    (commands, modifiedPart) = CommandProcessor.ExtractCommands(modifiedPart);
                    if (commands.Count > 0)
                    {
                        CommandProcessor.ProcessCommands(commands);
                    }
                    MelonLogger.Msg("After ExtractCommands " + modifiedPart);
                    modifiedPart = Utils.CleanFromTags(modifiedPart);
                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error processing part of response: {ex.Message}");
                }
            }

            GameObject currentDialog = InstantiateDialog();

            Dialogue_3DText answer = currentDialog.GetComponent<Dialogue_3DText>();


            answer.textPrint = modifiedPart;
            changeTextColor(currentDialog, characterToSend);

            answer.timeShow = delay;
            answer.speaker = MitaCore.Instance.MitaPersonObject;

            if (modifiedPart != "***" && modifiedPart != "...") MelonLogger.Msg($"Text is {answer.textPrint}");
            if (!itIsWaitingDialogue) addDialogueMemory(answer, MitaCore.Instance.currentCharacter);
            if (emotion != EmotionType.none) answer.emotionFinish = emotion;
            currentEmotion = emotion;

            currentDialog.SetActive(true);
            if (!NetworkController.connectedToSilero && !itIsWaitingDialogue) MelonCoroutines.Start(AudioControl.PlayTextAudio(part));

            yield return new WaitForSeconds(delay * delayModifier);
            //MelonLogger.Msg($"Deleting dialogue {currentDialog.name}");
            Utils.DestroyAfterTime(currentDialog, delay * 1.15f + 5f);

        }

        static void changeTextColor(GameObject currentDialog,characterType characterToSend)
        {
            if (characterToSend == characterType.Crazy) return;

            Color characterColor = CharacterControl.GetCharacterTextColor(characterToSend);
            var textMesh = currentDialog.GetComponentInChildren<Text>();
            if (textMesh != null)
            {
                textMesh.color = characterColor;
            }
        }
        public static GameObject InstantiateDialog(bool Mita = true)
        {
            Transform world = GameObject.Find("World")?.transform;
            if (world == null)
            {
                MelonLogger.Msg("World object not found.");
                return null;
            }
            if (Mita)
            {
                return GameObject.Instantiate(CustomDialog, world.Find("Quests/Quest 1/Dialogues"));
            }
            else
            {
                return GameObject.Instantiate(CustomDialogPlayer, world.Find("Quests/Quest 1/Dialogues"));
            }
        }
        private static void PlaySound(AudioClip audioClip, AudioSource audioSource)
        {
            MelonLogger.Msg("PlaySound not Dialogue");

            audioSource.clip = audioClip;
            audioSource.Play();


        }
        private static IEnumerator PlayMitaSound(float delay, AudioClip audioClip, int len)
        {
            MelonLogger.Msg("PlayMitaSound");



            // Если есть аудио, проигрываем его до начала текста
            if (audioClip != null)
            {
                GameObject currentDialog = InstantiateDialog();

                Dialogue_3DText answer = currentDialog.GetComponent<Dialogue_3DText>();
                MelonLogger.Msg("Loading voice...");
                answer.timeSound = delay;
                answer.LoadVoice(audioClip);
                audioClip = null;
                MelonLogger.Msg($"Setting speaker {MitaCore.Instance.MitaPersonObject.name}");
                answer.speaker = MitaCore.Instance.MitaPersonObject;

                currentDialog.SetActive(true);

                yield return new WaitForSeconds(delay * 1.15f);
                //MelonLogger.Msg($"Deleting dialogue {currentDialog.name}");

                Utils.DestroyAfterTime(currentDialog, delay * 1.15f + 5f);


            }


            MelonLogger.Msg("Dialogue part finished and destroyed.");
        }

        private static void addDialogueMemory(Dialogue_3DText dialogue_3DText,characterType speaker)
        {
            TextDialogueMemory textDialogueMemory = new TextDialogueMemory();
            textDialogueMemory.text = dialogue_3DText.textPrint;
            if (dialogue_3DText.themeDialogue == Dialogue_3DText.Dialogue3DTheme.Mita)
            {
                Color characterColor = CharacterControl.GetCharacterTextColor(speaker);
                textDialogueMemory.clr = Color.white;
                textDialogueMemory.clr2 = characterColor;
                textDialogueMemory.clr1 = Color.white;
            }
            else
            {
                textDialogueMemory.clr = new Color(1f, 0.6f, 0f);
                textDialogueMemory.clr2 = new Color(1f, 0.6f, 0f);
                textDialogueMemory.clr1 = new Color(1f, 0.6f, 0f);
            }
            MitaCore.Instance.playerController.dialoguesMemory.Add(textDialogueMemory);
        }

        private static List<string> SplitText(string text, int maxLength)
        {
            List<string> parts = new List<string>();
            Dictionary<string, string> placeholders = new Dictionary<string, string>();

            // Регулярное выражение для поиска служебных частей
            string pattern = @"<.*?>.*?</.*?>";
            int placeholderCounter = 0;

            // Заменяем служебные части на уникальные маркеры
            string processedText = Regex.Replace(text, pattern, match =>
            {
                string placeholder = $"@@{placeholderCounter}@@";
                placeholders[placeholder] = match.Value; // Сохраняем оригинальный текст
                placeholderCounter++;
                return placeholder;
            });

            // Разделяем по строкам
            string[] lines = processedText.Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries);

            foreach (string line in lines)
            {
                // Если длина строки меньше maxLength, добавляем её сразу
                if (line.Length <= maxLength)
                {
                    parts.Add(line.Trim());
                }
                else
                {
                    // Разделяем на предложения
                    string[] sentences = line.Split(new[] { '.', '!', '?' }, StringSplitOptions.RemoveEmptyEntries);
                    string currentPart = "";

                    foreach (string sentence in sentences)
                    {
                        string trimmedSentence = sentence.Trim();
                        if ((currentPart.Length + trimmedSentence.Length + 1) <= maxLength)
                        {
                            currentPart += (currentPart.Length > 0 ? " " : "") + trimmedSentence + ".";
                        }
                        else
                        {
                            if (!string.IsNullOrWhiteSpace(currentPart)) parts.Add(currentPart.Trim());
                            currentPart = trimmedSentence + ".";
                        }
                    }

                    // Добавляем оставшийся текст
                    if (!string.IsNullOrWhiteSpace(currentPart)) parts.Add(currentPart.Trim());
                }
            }

            // Восстанавливаем служебные части
            for (int i = 0; i < parts.Count; i++)
            {
                foreach (var placeholder in placeholders)
                {
                    parts[i] = parts[i].Replace(placeholder.Key, placeholder.Value);
                }
            }

            return parts;
        }
        public static void SetupDialogueTemplates(Transform worldHouse)
        {
            Transform dialogOriginal = worldHouse.Find("Quests/Quest 1/Dialogues/Dialogue Mita/Dialogue Finish Aihastion/DMita 2");

            if (dialogOriginal == null)
            {
                MelonLogger.Msg("Target object 'DMita 2' not found.");
                dialogOriginal = worldHouse.Find("Quests/Quest 1 Start/3D Text 5");

                if (dialogOriginal == null)
                {

                    MelonLogger.Msg("Target object '3D Text 5' not found.");
                }

            }

            DialogueControl.CustomDialog = GameObject.Instantiate(dialogOriginal.gameObject, worldHouse.Find("Quests/Quest 1/Dialogues"));
            DialogueControl.CustomDialog.name = "Custom Dialogue Mita";

            // Опускаем объект CustomDialog на 200 единиц по оси Y
            Vector3 newPosition = DialogueControl.CustomDialog.transform.position; // Получаем текущую позицию
            newPosition.y -= 200; // Уменьшаем Y на 200
            DialogueControl.CustomDialog.transform.position = newPosition; // Применяем новую позицию


            Dialogue_3DText CustomDialogText = DialogueControl.CustomDialog.GetComponent<Dialogue_3DText>();

            CustomDialogText.nextText = null;
            CustomDialogText.sizeHeight = 0.0687f;
            CustomDialogText.sizeSymbol = 0.0014f;
            CustomDialogText.sizeWidth = 0.75f;
            CustomDialogText.xPrint = 0.413f;
            CustomDialogText.indexString = -1;

            dialogOriginal = worldHouse.Find("Quests/Quest 1/Dialogues/Dialogue Player/Dialogue Hello/DPlayer 3");
            DialogueControl.CustomDialogPlayer = GameObject.Instantiate(dialogOriginal.gameObject, worldHouse.Find("Quests/Quest 1/Dialogues"));
            DialogueControl.CustomDialogPlayer.name = "Custom Dialogue Player";

            CustomDialogText = DialogueControl.CustomDialogPlayer.GetComponent<Dialogue_3DText>();

            CustomDialogText.nextText = null;
            CustomDialogText.sizeHeight = 0.0687f;
            CustomDialogText.sizeSymbol = 0.0014f;
            CustomDialogText.sizeWidth = 0.75f;
            CustomDialogText.xPrint = 0.413f;
            CustomDialogText.indexString = -1;
            CustomDialogText.showSubtitles = true;
        }
    }
}
