using MelonLoader;
using MitaAI.Mita;
using MitaAI.PlayerControls;
using System;
using System.Collections;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using UnityEngine;

namespace MitaAI
{
    public static class DataChange
    {
        public static float textTimeout = 40f;     // Лимит времени ожидания

        private const float MitaBoringInterval = 180f;
        public static float MitaBoringtimer = 0f;
        
        public static Dictionary<int, string> sound_files = new Dictionary<int, string>();

        static private float lastActionTime = -Mathf.Infinity;  // Для отслеживания времени последнего действия
        private const float actionCooldown = 6f;  // Интервал в секундах, надо сделать умнее для нормальных диалогов
        
        // Добавляем переменные для отслеживания последних сообщений, чтобы избежать дублирования
        private static string lastPlayerMessage = "";
        // Заменяем старые переменные на словарь для хранения данных по каждому персонажу
        private static Dictionary<characterType, (string message, int counter)> lastSystemData = 
            new Dictionary<characterType, (string, int)>();
        private static int maxDuplicates = 0; // Жёсткий лимит: 0 дубликатов (блокировать все дубликаты)

        public static IEnumerator HandleDialogue()
        {
            //MelonLogger.Msg("HandleDialogue");

            string playerText = MitaCore.Instance.playerMessage;
            MitaCore.Instance.playerMessage = "";
            bool sentPlayerMessage = false;

            string dataToSent = "waiting";
            string dataToSentSystem = "-";
            string info = "-";
            characterType characterToWas = characterType.None;
            characterType characterToSend = MitaCore.Instance.currentCharacter;
            List<characterType> Characters = CharacterControl.GetCharactersToAnswer(false);


            float currentTime = Time.unscaledTime;
            // Проверка на превышение интервала между действиями
            bool timeoutSatisfied = currentTime - lastActionTime > actionCooldown - (CharacterControl.needToIgnoreTimeout() ? 4 : 0);
            
            // Особая логика для режима охоты - принудительно сбрасываем счетчики дубликатов
            if (MitaState.GetCurrentState(characterToSend) == MitaStateType.hunt && timeoutSatisfied)
            {
                lastSystemData.Clear(); // Очищаем словарь с данными о сообщениях
            }

            if (timeoutSatisfied)
            {
                //MelonLogger.Msg("Ready to send");
                if (playerText != "")
                {
                    // Проверка на дублирование сообщения от игрока
                    if (playerText == lastPlayerMessage)
                    {
                        MelonLogger.Warning("Duplicate player message detected, skipping");
                        yield break;
                    }
                    
                    lastPlayerMessage = playerText;
                    MelonLogger.Msg("HAS playerMessage");
                    sentPlayerMessage = true;
                    Characters = CharacterControl.GetCharactersToAnswer();
                    if (Characters.Count > 0)
                    {
                        characterToSend = Characters.First();
                        CharacterMessages.sendInfoListeners(playerText, Characters, characterToSend);
                        MitaBoringtimer = 0f;
                        

                    }


                    dataToSent = playerText;

                    lastActionTime = Time.unscaledTime;
                }
                else if (CharacterMessages.systemMessages.Count > 0)
                {
                    MelonLogger.Msg("HAS SYSTEM MESSAGES");
                    MitaBoringtimer = 0f;

                    //Отправляю залпом.
                    while (CharacterMessages.systemMessages.Count() > 0)
                    {
                        var message = CharacterMessages.systemMessages.Dequeue();
                        dataToSentSystem += message.Item1 + "\n";
                        characterToSend = message.Item2;

                        // Проверяем, есть ли запись о последнем сообщении этого персонажа
                        if (lastSystemData.TryGetValue(characterToSend, out var lastData))
                        {
                            // Если сообщение совпадает с предыдущим для этого персонажа
                            if (message.Item1 == lastData.message)
                            {
                                lastData.counter++;
                                if (lastData.counter >= maxDuplicates)
                                {
                                    MelonLogger.Warning($"Слишком много дублей от {characterToSend}, пропускаем");
                                    lastSystemData[characterToSend] = lastData; // Обновляем счетчик
                                    continue;
                                }
                                lastSystemData[characterToSend] = lastData; // Обновляем счетчик
                            }
                            else
                            {
                                // Новое уникальное сообщение - устанавливаем счетчик на 1 (первое появление)
                                lastSystemData[characterToSend] = (message.Item1, 1);
                            }
                        }
                        else
                        {
                            // Первое сообщение от этого персонажа - устанавливаем счетчик на 1 (первое появление)
                            lastSystemData[characterToSend] = (message.Item1, 1);
                        }
                        
                        if (characterToWas == characterType.None || characterToWas == characterToSend)
                        {
                            characterToWas = message.Item2;
                        }
                        else
                        {
                            CharacterMessages.sendSystemMessage(message.Item1, characterToSend);
                            break;
                        }
                    }

                    lastActionTime = Time.unscaledTime;
                }
                else if (MitaBoringtimer >= MitaBoringInterval && MitaState.GetCurrentState(characterToSend) == MitaStateType.normal)
                {
                    MitaBoringtimer = 0f;
                    dataToSentSystem = "Player did nothing for 90 seconds";
                    lastActionTime = Time.unscaledTime;
                }
            }

            string response = "";

            // Добавляются все систем инфо
            foreach (var message in CharacterMessages.systemInfos.ToList())
            {
                if (message.Item2 == characterToSend)
                {
                    info += message.Item1 + "\n";
                    CharacterMessages.systemInfos.Remove(message);
                }
            }



            if (characterToSend != MitaCore.Instance.currentCharacter)
            {
                if (characterToSend != characterType.GameMaster)
                {
                    var MitaObj = MitaCore.getMitaPersonObjectByEnum(characterToSend);
                    if (MitaObj.GetComponentInChildren<Character>().enabled) MitaCore.Instance.addChangeMita(MitaObj,characterToSend, false, false, false, false);
                }
                else
                {
                    MitaCore.Instance.currentCharacter = characterToSend;
                }
            }

            if (dataToSent != "waiting" || dataToSentSystem != "-") CurrentInfoControl.prepareForSend();


            Task<Dictionary<string, JsonElement>> responseTask = NetworkController.GetResponseFromPythonSocketAsync(dataToSent, dataToSentSystem, info, characterToSend);

            if (responseTask == null) yield break;


            float waitMessageTimer = 0.5f;
            float elapsedTime = 0f; // Счетчик времени
            float lastCallTime = 0f; // Время последнего вызова


            while (!responseTask.IsCompleted)
            {
                elapsedTime += 0.1f;
                if (elapsedTime >= textTimeout)
                {
                    MelonLogger.Msg("Too long waiting for text");
                    break;
                }

                //MelonLogger.Msg($"!responseTask.IsCompleted{elapsedTime}/{timeout}");
                if (elapsedTime - lastCallTime >= waitMessageTimer && !DialogueControl.dialogActive)
                {
                    try
                    {
                        List<String> parts = new List<String> { "..." };
                        MelonCoroutines.Start(DialogueControl.ShowDialoguesSequentially(characterToSend,parts, true));
                        lastCallTime = elapsedTime; // Обновляем время последнего вызова
                    }
                    catch (Exception ex)
                    {

                        MelonLogger.Msg(ex);
                    }

                }
                yield return new WaitForSecondsRealtime(0.1f);
            }
            


            string patch = null;
            bool GM_ON = false;
            bool GM_READ = false;
            bool GM_VOICE = false;
            int id = 0;
            if (responseTask.IsCompleted)
            {


                Dictionary<string, JsonElement> messageData2 = responseTask.Result;
               // if (response == null || response.Count() == 0)
                //{
                 //   yield break;
                //}

                try
                {

                    id = messageData2["id"].GetInt32();
                    string type = messageData2["type"].GetString();

                    string new_character = messageData2["character"].GetString();
                    response = messageData2["response"].GetString();
                    bool connectedToSilero = messageData2["silero"].GetBoolean();

                    int idSound = messageData2["id_sound"].GetInt32();
                    //int idSound_cp = messageData2.ContainsKey("id_sound_cp") ? messageData2["id_sound_cp"].GetInt32() : 0;

                    patch = messageData2.ContainsKey("patch_to_sound_file") ? messageData2["patch_to_sound_file"].GetString() : "";
                    string user_input = messageData2.ContainsKey("user_input") ? messageData2["user_input"].GetString() : "";

                    GM_ON = messageData2.ContainsKey("GM_ON") ? messageData2["GM_ON"].GetBoolean() : false;
                    GM_READ = messageData2.ContainsKey("GM_READ") ? messageData2["GM_READ"].GetBoolean() : false;
                    GM_VOICE = messageData2.ContainsKey("GM_VOICE") ? messageData2["GM_VOICE"].GetBoolean() : false;
                    int GM_REPEAT = messageData2.ContainsKey("GM_REPEAT") ? messageData2["GM_REPEAT"].GetInt32() : 2;

                    int limitmod = messageData2.ContainsKey("CC_Limit_mod") ? messageData2["CC_Limit_mod"].GetInt32() : 100;

                    if (messageData2.ContainsKey("LANGUAGE")) LocalizationModded.setLanguage(messageData2["LANGUAGE"].GetString());

                    CustomUI.isAllowed = messageData2.ContainsKey("MITAS_MENU") ? messageData2["MITAS_MENU"].GetBoolean() : false;
                    RadialMenu.isAllowed = messageData2.ContainsKey("EMOTION_MENU") ? messageData2["EMOTION_MENU"].GetBoolean() : false;
                    
                    if (messageData2.ContainsKey("TEXT_WAIT_TIME")) DataChange.textTimeout = messageData2["TEXT_WAIT_TIME"].GetInt32();
                    if (messageData2.ContainsKey("VOICE_WAIT_TIME")) DialogueControl.voiceTimout = messageData2["VOICE_WAIT_TIME"].GetInt32();
                    


                    InputControl.instantSend = messageData2.ContainsKey("instant_send") ? messageData2["instant_send"].GetBoolean() : false;


                    if (!string.IsNullOrEmpty(patch))
                    {

                        sound_files[idSound] = patch;

                            
                    }

                    if (CharacterControl.gameMaster != null)
                    {
                        CharacterControl.gameMaster.timingEach = GM_REPEAT;
                        CharacterControl.gameMaster.enabled = GM_ON;


                    }
                    NetworkController.connectedToSilero = connectedToSilero;
                    CharacterControl.limitMod = limitmod;


                    InputControl.UpdateInput(user_input);



                }
                catch (Exception ex)
                {

                    MelonLogger.Error(ex);
                }

            }
            else
            {
                response = "Too long waited for text from python";
                NetworkController.connectedToSilero = false;
            }




            if (response != "")
            {
                MelonLogger.Msg($"after GetResponseFromPythonSocketAsync char {characterToSend} {GM_READ} {GM_VOICE}");

                if (characterToSend.ToString().Contains("Cart")) MelonCoroutines.Start(DialogueControl.DisplayResponseAndEmotionCoroutine(id, characterToSend, response, AudioControl.cartAudioSource));
                else if (characterToSend == characterType.GameMaster)
                {



                    if (GM_READ) MelonCoroutines.Start(DialogueControl.DisplayResponseAndEmotionCoroutine(id, characterToSend, response, AudioControl.playerAudioSource, GM_VOICE));
                    else CommandProcessor.ProcessCommands(CommandProcessor.ExtractCommands(response).Item1);
                }
                else MelonCoroutines.Start(DialogueControl.DisplayResponseAndEmotionCoroutine(id, characterToSend,response));

                if (characterToSend != characterType.GameMaster) CharacterMessages.sendInfoListeners(Utils.CleanFromTags(response), Characters, characterToSend, CharacterControl.extendCharsString(characterToSend));
                else CharacterMessages.sendInfoListenersFromGm(Utils.CleanFromTags(response), Characters, characterToSend);


                //Тестово - хочешь чтобы было без лишнего отрубай это

                MelonCoroutines.Start(testNextAswer(response, characterToSend, sentPlayerMessage));



            }

            static IEnumerator testNextAswer(string response, characterType currentCharacter, bool fromPlayer)
            {
                yield return new WaitForSeconds(0.25f);
                while (DialogueControl.dialogActive)
                {
                    yield return null;
                }

                CharacterControl.nextAnswer(Utils.CleanFromTags(response), currentCharacter, fromPlayer);
            }

        }

    }
}
