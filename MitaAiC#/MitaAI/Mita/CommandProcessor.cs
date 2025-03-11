using Il2Cpp;
using MelonLoader;
using MitaAI.WorldModded;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.AI;
using static MelonLoader.MelonLogger;

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
            Transform newPosition = new GameObject().transform;
            Vector3 direction = (MitaTransform.position - playerPerson.position).normalized;
            switch (command.ToLower())
            {
                case "подойти к игроку":
                    mitaCore.Mita.AiWalkToTarget(playerPerson);
                    location34_Communication.indexSwitchAnimation = 1;
                    break;
                case "подойти к игроку вплотную":
                    mitaCore.Mita.AiWalkToTarget(playerPerson);
                    location34_Communication.indexSwitchAnimation = 1;
                    break;
                case "подойти к игроку близко":
                    newPosition.transform.position = playerPerson.position + direction * 1.2f; // closeDistance — ваше значение
                    mitaCore.Mita.AiWalkToTarget(newPosition);
                    location34_Communication.indexSwitchAnimation = 1;
                    GameObject.Destroy(newPosition);
                    break;
                case "подойти к игроку далеко":
                    newPosition.transform.position = playerPerson.position + direction * 3f; // farDistance — ваше значение
                    mitaCore.Mita.AiWalkToTarget(newPosition);
                    location34_Communication.indexSwitchAnimation = 1;
                    GameObject.Destroy(newPosition);
                    break;

                case "подойти к случайной точке":
                    loc = mitaCore.GetRandomLoc();
                    mitaCore.sendSystemInfo($"Ты пошла к {loc.name}");
                    mitaCore.Mita.AiWalkToTarget(loc);
                    location34_Communication.indexSwitchAnimation = 1;
                    break;

                case "телепортироваться к случайной точке":
                    loc = mitaCore.GetRandomLoc();
                    mitaCore.sendSystemInfo($"Ты успешно телепортировалась к {loc.name}");
                    mitaCore.Mita.MitaTeleport(loc);
                    location34_Communication.indexSwitchAnimation = 1;
                    break;

                case "телепортироваться к игроку":
                    mitaCore.Mita.MitaTeleport(playerPerson);
                    location34_Communication.indexSwitchAnimation = 1;
                    break;

                // Начало агрессии
                case "зарезать игрока":
                    MelonCoroutines.Start(mitaCore.ActivateAndDisableKiller(3f));
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
                    mitaCore.beginHunt();
                    break;
                case "закончить охоту с ножом":
                    mitaCore.endHunt();
                    break;
                case "вернуться к норме":
                    MitaGames.removeAllMenekens();
                    mitaCore.endHunt();
                    break;

                case "resethaircolor":
                    MitaClothesModded.resetMitaHairColor();
                    break;

                case "continue":
                    ContinueCounter = ContinueCounter + 1;
                    MelonLogger.Msg($"Cont times {ContinueCounter}");
                    if (ContinueCounter < 3)
                    {
                        mitaCore.sendSystemInfo($"У тебя осталось {3 - ContinueCounter} возможностей продолжить фразу");
                        mitaCore.sendSystemMessage("Ты продолжаешь фразу или мысль");
                    }
                    else
                    {
                        MelonLogger.Warning("tryied 4 continue");
                        mitaCore.sendSystemInfo("Ты не смогла продолжить фразу сразу, так как лимит в 3 continue подряд был превышен");
                    }
                    break;

                case "Надеть очки":
                    mitaCore.GlassesObj(true);
                    break;
                case "Снять очки":
                    mitaCore.GlassesObj(false);
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

            if (parts.Length == 2 && float.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out float time))
            {
                HandleTwoPartCommand(parts[0].ToLower(), time);
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

        private static void HandleTwoPartCommand(string command, float time)
        {
            switch (command)
            {
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

                default:
                    MelonLogger.Msg($"Unknown two-part command: {command}");
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
                    MitaClothesModded.setMitaHairColor(new Color(r, g, b, 1f));
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
            }
        }

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

    }

}
