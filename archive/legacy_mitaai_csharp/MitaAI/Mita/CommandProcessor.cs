using Il2Cpp;
using Il2CppSystem.Threading;
using MelonLoader;
using MitaAI.WorldModded;
using System;
using System.Collections;
using System.Globalization;
using System.Text.RegularExpressions;
using System.Transactions;
using UnityEngine;
using UnityEngine.AI;


namespace MitaAI.Mita
{
    public static class CommandProcessor
    {
        static MitaCore mitaCore;
        private static Transform playerPerson;
        private static Transform MitaPersonObject;
        private static Location34_Communication location34_Communication;
        public static int ContinueCounter = 0;

        public static void Initialize(MitaCore mitaCore2, Transform playerPersonTransform, Transform mitaPersonObjectTransform, Location34_Communication location34_Communication2)
        {
            mitaCore = mitaCore2;
            playerPerson = playerPersonTransform;
            MitaPersonObject = mitaPersonObjectTransform;
            location34_Communication = location34_Communication2;
        }

        public static (List<string>, string) ExtractCommands(string response)
        {
            List<string> commands = new List<string>();
            string pattern = @"<c>(.*?)</c>";
            MatchCollection matches = Regex.Matches(response, pattern);

            foreach (Match match in matches)
            {
                if (match.Success)
                {
                    string command = match.Groups[1].Value;
                    if (command.ToLower() == "continue")
                    {
                        ContinueCounter++;
                        if (ContinueCounter > 3)
                        {
                            MelonLogger.Msg($"Достигнут лимит продолжений (3), пропускаем команду Continue");
                            continue;
                        }
                    }
                    commands.Add(command);
                }
            }

            bool wasContinue = response.ToLower().Contains("continue");
            string result = Regex.Replace(response, @"<c>.*?</c>", "");
            if (wasContinue) result += " ▶▶▶ ";
            // Удаляем теги эмоций из текста
            return (commands, result);
        }
        public static void ProcessCommands(List<string> commands)
        {
            MelonLogger.Msg("ProcessCommands start");
            foreach (string command in commands)
            {
                try
                {
                    if (command.Contains(','))
                    {
                        ProcessComplexCommand(command);
                    }
                    else
                    {
                        ProcessSimpleCommand(command);
                    }
                }
                catch (Exception ex)
                {
                    MelonLogger.Msg($"Error processing command '{command}': {ex.Message}");
                }
            }

        }

        private static void ProcessSimpleCommand(string command)
        {
            Transform loc;

            Transform MitaTransform = MitaCore.Instance.MitaPersonObject.transform;
            Transform newPosition = getMovePosition();
            Vector3 direction = (MitaTransform.position - playerPerson.position).normalized;
            switch (command.ToLower())
            {
                case "подойти к игроку":
                    newPosition.transform.position = playerPerson.position + direction * 0.85f; // closeDistance — ваше значение
                    ObjectAnimationMita.finishWorkingOAM();
                    mitaCore.Mita.AiWalkToTargetTranform(newPosition,null);
                    location34_Communication.indexSwitchAnimation = 1;
                    Utils.DestroyAfterTime(newPosition.gameObject, 5f);
                    break;
                case "подойти к игроку вплотную":
                    newPosition.transform.position = playerPerson.position + direction * 0.45f; // closeDistance — ваше значение
                    ObjectAnimationMita.finishWorkingOAM();
                    mitaCore.Mita.AiWalkToTargetTranform(newPosition, null);
                    location34_Communication.indexSwitchAnimation = 1;
                    Utils.DestroyAfterTime(newPosition.gameObject, 5f);
                    break;
                case "подойти к игроку близко":
                    newPosition.transform.position = playerPerson.position + direction * 1f; // closeDistance — ваше значение
                    ObjectAnimationMita.finishWorkingOAM();
                    mitaCore.Mita.AiWalkToTargetTranform(newPosition, null);
                    location34_Communication.indexSwitchAnimation = 1;
                    Utils.DestroyAfterTime(newPosition.gameObject, 5f);
                    break;
                case "подойти к игроку далеко":
                    newPosition.transform.position = playerPerson.position + direction * 2f; // farDistance — ваше значение
                    ObjectAnimationMita.finishWorkingOAM();
                    mitaCore.Mita.AiWalkToTargetTranform(newPosition, null);
                    location34_Communication.indexSwitchAnimation = 1;
                    Utils.DestroyAfterTime(newPosition.gameObject, 5f);
                    break;

                case "подойти к случайной точке":
                    loc = mitaCore.GetRandomLoc();
                    CharacterMessages.sendSystemInfo($"Ты пошла к {loc.name}");
                    ObjectAnimationMita.finishWorkingOAM();
                    mitaCore.Mita.AiWalkToTargetTranform(loc, null);
                    location34_Communication.indexSwitchAnimation = 1;
                    MitaMovement.MitaSetStaing(MitaCore.Instance.currentCharacter);
                    break;

                case "телепортироваться к случайной точке":
                    loc = mitaCore.GetRandomLoc();
                    ObjectAnimationMita.finishWorkingOAM();
                    CharacterMessages.sendSystemInfo($"Ты успешно телепортировалась к {loc.name}");
                    mitaCore.Mita.MitaTeleport(loc);
                    mitaCore.Mita.AiShraplyStop();
                    location34_Communication.indexSwitchAnimation = 1;
                    MitaMovement.MitaSetStaing(MitaCore.Instance.currentCharacter);
                    break;

                case "телепортироваться к игроку":
                    ObjectAnimationMita.finishWorkingOAM();
                    mitaCore.Mita.MitaTeleport(playerPerson);
                    mitaCore.Mita.AiShraplyStop();
                    location34_Communication.indexSwitchAnimation = 1;
                    break;

                // Начало агрессии
                case "зарезать игрока":
                    MelonCoroutines.Start(ActivateAndDisableKiller(3f));
                    break;

                case "выключить игрока":
                    MitaCore.MainMenu.ButtonLoadScene("SceneMenu");
                    break;

                // Блок Манекенов
                case "заспавнить манекен":
                    MitaGames.spawnManeken();
                    break;

                case "отключить все манекены":
                    MitaGames.TurnAllMenekens(false);
                    break;

                case "включить все манекены":
                    MitaGames.TurnAllMenekens(true);
                    break;

                case "удалить все манекены":
                    MitaGames.removeAllMenekens();
                    break;

                case "начать охоту с ножом":
                    MitaGames.beginHunt();
                    break;
                case "закончить охоту с ножом":
                    MitaGames.endHunt();
                    break;
                case "вернуться к норме":
                    MitaGames.removeAllMenekens();
                    MitaGames.endHunt();
                    break;

                case "resethaircolor":
                    MitaClothesModded.resetMitaHairColor();
                    break;

                case "continue":
                    ContinueCounter = ContinueCounter + 1;
                    MelonLogger.Msg($"Cont times {ContinueCounter}");
                    if (ContinueCounter < 3)
                    {
                        CharacterMessages.sendSystemInfo($"У тебя осталось {3 - ContinueCounter} возможностей продолжить фразу", MitaCore.Instance.currentCharacter);
                        CharacterMessages.sendSystemMessage("Ты продолжаешь фразу или мысль",MitaCore.Instance.currentCharacter);
                    }
                    else
                    {
                        MelonLogger.Warning("tryied 4 continue");
                        CharacterMessages.sendSystemInfo("Ты не смогла продолжить фразу сразу, так как лимит в 3 continue подряд был превышен", MitaCore.Instance.currentCharacter);
                    }
                    break;




                case "tojail":
                    Jail(true);
                    break;
                case "fromjail":
                    Jail(false);
                    break;


                // Дополнительные команды...
                default:
                    HandleDefaultCommand(command);
                    break;
            }
        }

        private static void ProcessComplexCommand(string command)
        {
            string[] parts = command.Split(',');

            if (parts.Length == 2)
            {
                HandleTwoPartCommand(parts[0].ToLower(), parts[1]);
            }
            else if(parts.Length == 3)
            {
                HandleThreePartCommand(parts[0], parts[1], parts[2]);
            }
            else if (parts.Length == 4 &&
                     float.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out float r) &&
                     float.TryParse(parts[2], NumberStyles.Float, CultureInfo.InvariantCulture, out float g) &&
                     float.TryParse(parts[3], NumberStyles.Float, CultureInfo.InvariantCulture, out float b))
            {
                HandleFourPartCommand(parts[0].ToLower(), r, g, b);
            }
            else
            {
                MelonLogger.Msg($"Invalid command format: {command}");
            }
        }

        private static void HandleTwoPartCommand(string command, string secondCommand)
        {
            GameObject gameObject;

            float.TryParse(secondCommand, NumberStyles.Float, CultureInfo.InvariantCulture, out float time);
            switch (command.ToLower())
            {
                case "подойти к":

                    try
                    {
                        ObjectAnimationMita.finishWorkingOAM();
                        Transform newPosition = GameObject.Find(secondCommand).transform;
                        mitaCore.Mita.AiWalkToTarget(newPosition);
                        CharacterMessages.sendSystemInfo($"Ты пошла к {secondCommand}");
                        MitaMovement.MitaSetStaing(MitaCore.Instance.currentCharacter);
                    }
                    catch (Exception ex)
                    {
                        MelonLogger.Error($"Tried to go to point {secondCommand} {ex}");
                        CharacterMessages.sendSystemInfo($"точки {secondCommand} не нашлось");
                        MitaMovement.MitaSetStaing(MitaCore.Instance.currentCharacter);
                    }

                    break;

                case "телепортироваться в":

                    try
                    {
                        ObjectAnimationMita.finishWorkingOAM();
                        Transform newPosition = GameObject.Find(secondCommand).transform;
                        mitaCore.Mita.MitaTeleport(newPosition);
                        mitaCore.Mita.AiShraplyStop();
                        CharacterMessages.sendSystemInfo($"Ты телепортировалась в {secondCommand}");
                    }
                    catch (Exception ex)
                    {
                        MelonLogger.Error($"Tried to teleport to point {secondCommand} {ex}");
                        CharacterMessages.sendSystemInfo($"точки {secondCommand} не нашлось");
                    }

                    break;
                case "телепортироваться к":

                    try
                    {
                        ObjectAnimationMita.finishWorkingOAM();
                        Transform newPosition = GameObject.Find(secondCommand).transform;
                        mitaCore.Mita.MitaTeleport(newPosition);
                        mitaCore.Mita.AiShraplyStop();
                        CharacterMessages.sendSystemInfo($"Ты телепортировалась в {secondCommand}");
                    }
                    catch (Exception ex)
                    {
                        MelonLogger.Error($"Tried to teleport to point {secondCommand} {ex}");
                        CharacterMessages.sendSystemInfo($"точки {secondCommand} не нашлось");
                    }

                    break;

                case "lookat":
                    if (secondCommand.Contains("Player") || secondCommand.Contains("player")) secondCommand = "HeadPlayer";
                    MitaCore.Instance.MitaLook.LookOnObject(GameObject.Find(secondCommand).transform);
                    break;
                case "lookaturnto":
                    if (secondCommand.Contains("Player") || secondCommand.Contains("player")) secondCommand = "HeadPlayer";
                    MitaCore.Instance.MitaLook.LookOnObjectAndRotate(GameObject.Find(secondCommand).transform);
                    break;
                case "turnto":
                    if (secondCommand.Contains("Player") || secondCommand.Contains("player")) secondCommand = "HeadPlayer";
                    MitaCore.Instance.MitaLook.RotateOnTarget(GameObject.Find(secondCommand).transform);
                    break;


                case "изменить моргание игрока":
                    MitaGames.blinkTimer = Math.Max(2, Math.Min(time, 10));
                    break;

                case "изменить время дня":
                    LightingAndDaytime.setTimeDay(time);
                    MelonLogger.Msg($"Time of day changed to {time}");
                    break;
                case "изменить размер игрока":
                    time = Math.Clamp(time, 0.5f, 3f);
                    playerPerson.localScale = new Vector3(time, time, time);
                    break;
                case "изменить свой размер":
                    time = Math.Clamp(time, 0.5f, 3f);
                    MitaPersonObject.transform.localScale = new Vector3(time, time, time);
                    break;
                case "изменить скорость игрока":
                    playerPerson.gameObject.GetComponent<PlayerMove>().speedPlayer = time;
                    break;
                case "изменить свою скорость":
                    try
                    {
                        MitaPersonObject.GetComponent<NavMeshAgent>().speed = time;
                    }
                    catch (Exception)
                    {

                    }

                    break;
                #region GameMaster
                case "sendall":

                    MelonLogger.Msg($"GameMaster Try {command} Send {secondCommand} To all");
                    CharacterMessages.sendInfoListenersFromGm(secondCommand);
                    break;
                case "speaker":

                    MelonLogger.Msg($"GameMaster choose speaker");
                    if (Enum.TryParse<characterType>(secondCommand, true, out var characterToSend)) 
                        CharacterControl.SetNextSpeaker(characterToSend);
                    else
                        CharacterMessages.sendSystemInfo($"Failed to chose next speaker {secondCommand}, not found");
                    
                    //CharacterMessages.sendSystemMessage(characterToSend);
                    break;
                #endregion



                default:
                    MelonLogger.Msg($"Unknown two-part command: {command}");
                    break;
            }
        }
        private static void HandleThreePartCommand(string command, string secondCommand, string thrirdCommand)
        {
            switch (command.ToLower())
            {
                #region GameMaster
                case "send":

                    MelonLogger.Msg($"GameMaster Try {command} Send {thrirdCommand} To {secondCommand}");
                    Enum.TryParse<characterType>(secondCommand, true, out var characterToSend);
                    CharacterMessages.sendSystemInfo(thrirdCommand, characterToSend);
                    break;

                #endregion

                default:
                    MelonLogger.Msg($"Unknown three-part command: {command}");
                    break;
            }
        }

        private static void HandleFourPartCommand(string command, float r, float g, float b)
        {
            switch (command)
            {
                case "изменить освещение":
                    LightingAndDaytime.applyColor(new Color(r, g, b, 1f));
                    MelonLogger.Msg($"Lighting color changed to RGB({r}, {g}, {b})");
                    break;
                case "haircolor":
                    var color = new Color(Math.Clamp(r,0,3), Math.Clamp(g,0,3), Math.Clamp(b,0,3), 1f);
                    MitaClothesModded.setMitaHairColor(color);
                    MelonLogger.Msg($"HairColor changed to RGB({r}, {g}, {b})");
                    break;

                default:
                    MelonLogger.Msg($"Unknown four-part command: {command}");
                    break;
            }
        }

        private static void HandleDefaultCommand(string command)
        {
            if (command.Contains("PositionMita"))
            {
                try
                {
                    GameObject point = GameObject.Find(command);
                    mitaCore.Mita.MitaTeleport(point.transform);
                    location34_Communication.indexSwitchAnimation = 1;
                }
                catch (Exception e)
                {
                    MelonLogger.Msg($"Unknown point: {command} error {e}");
                }
            }
            else
            {
                MelonLogger.Msg($"Unknown command: {command}");
                CharacterMessages.sendSystemInfo($"command {command} not found. Maybe tag <p> is not correct");
            }
        }

        // Подсказка слева сверху
        public static string ProcesHint(string response)
        {


            string pattern = @"<hint>(.*?)</hint>";
            MatchCollection matches = Regex.Matches(response, pattern);

            foreach (Match match in matches)
            {
                if (match.Success)
                {
                    MitaCore.Instance.playerController.ShowHint(match.Groups[1].Value, new Vector2(25, -25));
                    break;
                }
            }


            string result = Regex.Replace(response, @"<hint>.*?</hint>", "");

            // Удаляем теги эмоций из текста
            return result;

        }




        public static IEnumerator ActivateAndDisableKiller(float delay)
        {
            MelonLogger.Msg("Player killed");

            if (MitaCore.Instance.AnimationKiller.transform.Find("PositionsKill").childCount > 0)
            {
                MitaCore.Instance.AnimationKiller.transform.Find("PositionsKill").GetChild(0).SetPositionAndRotation(playerPerson.transform.position, playerPerson.transform.rotation);
            }
            MitaCore.Instance.AnimationKiller.SetActive(true); // Включаем объект


            // Сохраняем исходную позицию и ориентацию Миты
            Vector3 originalPosition = MitaPersonObject.transform.position;
            Quaternion originalRotation = MitaPersonObject.transform.rotation;
            MitaPersonObject.transform.SetPositionAndRotation(new Vector3(500, 500, 500), Quaternion.identity);
            yield return new WaitForSeconds(0.1f);
            try
            {
                MitaCore.Instance.AnimationKiller.GetComponent<Location6_MitaKiller>().Kill(); // Вызываем метод Kill()
                MitaGames.endHunt();
            }
            catch (Exception e)
            {

                MelonLogger.Msg(e);
            }

            yield return new WaitForSecondsRealtime(delay);

            CharacterMessages.sendSystemMessage("You successfully killed the player using knife, and he respawned somewhere.");

            MitaCore.Instance.AnimationKiller.SetActive(false); // Включаем объект
            // Возвращаем Миту в исходное положение
            Utils.TryTurnChild(MitaCore.worldHouse, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom", true);

            try
            {
                MitaPersonObject.transform.SetPositionAndRotation(originalPosition, originalRotation);
                MitaCore.Instance.Mita.AiShraplyStop();
            }
            catch (Exception)
            {

                throw;
            }

            PlayerAnimationModded.TurnHandAnim();

            if (AudioControl.getCurrrentMusic() != "Music 4 Tension")
            {
                MelonLogger.Msg("Need to turn of Tension");
                AudioControl.TurnAudio("Music 4 Tension", false);

                yield return new WaitForSecondsRealtime(2f);

                AudioControl.TurnAudio("Music 4 Tension", false);
            }



        }

        // TODO дать доброй мите в промпте
        public static void Jail(bool Enter)
        {
            if (Enter)
            {
                try
                {
                    // Находим игрока
                    GameObject player = GameObject.Find("GameController/Player");
                    if (player != null)
                    {
                        // Телепортируем на указанные координаты
                        player.transform.position = new Vector3(10.8995f, -2.9825f, -10.6286f);

                        // Деактивируем FixPosition так как в клетку не пустит
                        Transform rightWrist = player.transform.Find("RightWrist FixPosition");
                        if (rightWrist != null)
                        {
                            rightWrist.gameObject.SetActive(false);
                        }

                        Transform leftWrist = player.transform.Find("LeftWrist FixPosition");
                        if (leftWrist != null)
                        {
                            leftWrist.gameObject.SetActive(false);
                        }

                        MelonLogger.Msg("Player teleported and wrist positions deactivated");
                    }
                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error during Jail Enter handling: {ex}");
                }
            }

            else
            {
                try
                {
                    // Находим игрока
                    GameObject player = GameObject.Find("GameController/Player");
                    if (player != null)
                    {
                        // Телепортируем на новые координаты
                        player.transform.position = new Vector3(12.532f, -2.9825f, -10.612f);

                        // Активируем FixPosition
                        Transform rightWrist = player.transform.Find("RightWrist FixPosition");
                        if (rightWrist != null)
                        {
                            rightWrist.gameObject.SetActive(true);
                        }

                        Transform leftWrist = player.transform.Find("LeftWrist FixPosition");
                        if (leftWrist != null)
                        {
                            leftWrist.gameObject.SetActive(true);
                        }

                        MelonLogger.Msg("Player teleported and wrist positions activated");
                    }
                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error during Jail Leave handling: {ex}");
                }
            }

           
        }
        static Transform movePos;
        static Transform getMovePosition()
        {
            if (movePos == null)
                movePos = new GameObject().transform;
            return movePos;
        }

        // В случае экстренной ситуации вызвать
        static void TestBigMita()
        {
            MelonLogger.Msg("Start TestBigMita");
            MitaCore.Instance.MitaObject.transform.FindChild("MitaPerson Mita").localScale = new Vector3(15f, 15f, 15f);

            Vector3 direction = (MitaCore.Instance.MitaObject.transform.position - MitaCore.Instance.playerObject.transform.position).normalized;

            MitaCore.Instance.MitaObject.transform.SetPositionAndRotation(new Vector3(15f, 0f, 15f), Quaternion.LookRotation(direction));

            try
            {
                GameObject floor = GameObject.Instantiate(Utils.TryfindChild(MitaCore.worldHouse, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom/FloorBedroom").gameObject);
                floor.transform.localScale = new Vector3(30f, 1, 30f);
            }
            catch (Exception ex)
            {
                MelonLogger.Msg("TestBigMita end " + ex);
            }

            MitaCore.worldHouse.Find("House").gameObject.SetActive(false);
            MitaCore.worldBasement.Find("House").gameObject.SetActive(false);

        }
    }

}
