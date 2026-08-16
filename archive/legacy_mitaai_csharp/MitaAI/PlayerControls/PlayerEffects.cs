using Il2Cpp;
using MelonLoader;
using UnityEngine;
using UnityEngine.UI;
using System.Text.RegularExpressions;
using System.Collections;
using Il2CppInterop.Runtime.InteropTypes;
using System.Globalization;



namespace MitaAI
{
    public static class PlayerEffectsModded
    {
        static PlayerCameraEffects playerEffects;
        public static GameObject playerEffectsObject;
        public static BlackScreen blackScreen;
        public static GameObject DayEffect;
        public static void Init(GameObject playerPerson)
        {
            playerEffects = playerPerson.transform.parent.Find("HeadPlayer/MainCamera").gameObject.GetComponent<PlayerCameraEffects>();
            playerEffectsObject = playerPerson.transform.parent.Find("HeadPlayer/MainCamera/CameraPersons").gameObject;
            blackScreen= GameObject.Find("Game/Interface/BlackScreen").GetComponent<BlackScreen>();
            blackScreen.timeOff = 0.25f;
            turnBlackScreen(true, false);
        }

        public static string ProcessPlayerEffects(string response)
        {
            MelonLogger.Msg("Starting ProcessPlayerEffects...");

            List<string> effects = new List<string>();
            string pattern = @"<v>(.*?)</v>";
            MatchCollection matches = Regex.Matches(response, pattern);

            foreach (Match match in matches)
            {
                if (match.Success)
                {
                    effects.Add(match.Groups[1].Value);
                    MelonLogger.Msg($"Found effect tag: {match.Groups[1].Value}");
                }
            }

            string result = Regex.Replace(response, @"<v>.*?</v>", "");
            MelonLogger.Msg("Removed effect tags from response.");

            try
            {
                foreach (string effectAndTime in effects)
                {
                    MelonLogger.Msg($"Processing effect and time: {effectAndTime}");

                    string[] parts = effectAndTime.Split(',');
                    string effect = "";
                    float time = 1f;

                    if (parts.Length == 2 && float.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out time))
                    {
                        effect = parts[0];
                        MelonLogger.Msg($"Parsed effect: {effect}, time: {time}");
                    }
                    else
                    {
                        MelonLogger.Msg($"Invalid format for effect and time: {effectAndTime}");
                        continue;
                    }

                    Component effectComponent = null;
                    try
                    {
                        MelonLogger.Msg($"Attempting to find component for effect: {effect}");
                        switch (effect.ToLower())
                        {
                            case "глитч":
                                effectComponent = playerEffectsObject.GetComponentByName("Glitch");
                                break;
                            case "телемост":
                                playerEffects.EffectDatamosh(true);
                                MelonCoroutines.Start(DisableEffectAfterDelay(playerEffects, "EffectDatamosh", time)); // Запускаем корутину для выключения эффекта
                                break;
                            case "тв-удар":
                                playerEffects.EffectClickTelevision();
                                break;
                            case "помехи":
                                effectComponent = playerEffectsObject.GetComponentByName("Noise");
                                break;
                            case "негатив":
                                effectComponent = playerEffectsObject.GetComponentByName("Negative");
                                break;
                            case "кровь":
                                MelonCoroutines.Start(AddRemoveBloodEffect(time));
                                break;
                            case "blure":
                                MelonCoroutines.Start(DisableEffectAfterDelay(playerEffects, "Blure", time)); // Запускаем корутину для выключения эффекта
                                break;
                            default:
                                MelonLogger.Msg($"Unknown effect: {effect}");
                                continue;
                        }

                        if (effectComponent != null)
                        {
                            if (effectComponent is MonoBehaviour monoBehaviourComponent)
                            {
                                // Если это стандартный MonoBehaviour
                                monoBehaviourComponent.enabled = true; // Включаем компонент
                                MelonCoroutines.Start(Utils.ToggleComponentAfterTime(monoBehaviourComponent, time)); // Запускаем корутину
                            }
                            else if (effectComponent is Il2CppObjectBase il2cppComponent)
                            {
                                // Если это Il2CppObjectBase
                                MelonLogger.Msg($"Il2Cpp component detected: {il2cppComponent.GetType().Name}");

                                // Проверяем, имеет ли компонент свойство enabled
                                var enabledProperty = il2cppComponent.GetType().GetProperty("enabled");
                                var behaviour = il2cppComponent.TryCast<Behaviour>();
                                behaviour.enabled = true;

                                // Запускаем корутину, передавая Il2Cpp-компонент
                                MelonCoroutines.Start(Utils.HandleIl2CppComponent(il2cppComponent, time));

                            }
                            else
                            {
                                MelonLogger.Warning($"Component {effectComponent?.GetType().Name} is not a MonoBehaviour or Il2CppObjectBase.");
                            }
                        }

                    }
                    catch (Exception ex)
                    {
                        MelonLogger.Msg($"Error processing effect '{effect}': {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Msg($"Error in ProcessPlayerEffects: {ex.Message}");
            }

            MelonLogger.Msg("Finished ProcessPlayerEffects.");
            return result;
        }

        public static IEnumerator AddRemoveBloodEffect(float time)
        {
            playerEffects.FastVegnetteActive(true);
            yield return new WaitForSecondsRealtime(5);
            playerEffects.FastVegnetteActive(false);
        }



        private static IEnumerator DisableEffectAfterDelay(Il2CppObjectBase il2cppComponent, string effectMethodName, float delay)
        {
            yield return new WaitForSeconds(delay); // Ожидаем заданное время

            // Получаем тип компонента Il2Cpp
            var componentType = il2cppComponent.GetType();

            // Используем метод GetMethod для получения метода с именем effectMethodName
            var method = componentType.GetMethod(effectMethodName);

            if (method != null)
            {
                // Передаём параметр false для выключения эффекта
                method.Invoke(il2cppComponent, new object[] { false });
                MelonLogger.Msg($"Effect {effectMethodName} has been disabled after {delay} seconds.");
            }
            else
            {
                MelonLogger.Warning($"Effect method {effectMethodName} not found on Il2Cpp component.");
            }
        }
        public static void turnBlackScreen(bool on,bool sharply = true)
        {
            blackScreen.HoldBlack(on,sharply);
            
        }

        public static void ShowDayFromNumber(int number, string title = null,bool avoidSplit = true)
        {
            string numStr = number.ToString();
            string n1 = "", n2 = "", n3 = "";


            if (avoidSplit)
            {
                showDay(title, n2: number.ToString());
                return;
            }


            switch (numStr.Length)
            {
                case 1:
                    n2 = numStr; // Однозначное → в центр (n2)
                    break;
                case 2:
                    n2 = numStr[0].ToString(); // Двузначное → n2 и n3
                    n3 = numStr[1].ToString();
                    break;
                case 3:
                    n1 = numStr[0].ToString(); // Трёхзначное → n1, n2, n3
                    n2 = numStr[1].ToString();
                    n3 = numStr[2].ToString();
                    break;
                default:
                    Debug.LogError("Число должно быть от 0 до 999!");
                    return;
            }
            showDay(title,n1: n1, n2: n2, n3: n3);
        }

        public static void showDay(string name=null, string n1 = null, string n2 = null, string n3 = null)
        {



            if (name != null)
                try
                {
                    DayEffect.GetComponentInChildren<Localization_UIText>().StringNumber = -1;
                    //DayEffect.GetComponentInChildren<Localization_UIText>().enabled = false;
                    DayEffect.GetComponentInChildren<Localization_UIText>() .Start();
                }
                catch { }

                DayEffect.transform.Find("TextDay").GetComponent<Text>().text = name;
                Utils.setTextTimed(DayEffect.transform.Find("TextDay").GetComponent<Text>(), name, 0.35f);

            if (n1 != null)
                DayEffect.transform.Find("Number 1").GetComponent<Text>().text = n1;

            if (n2 != null)
                DayEffect.transform.Find("Number 2").GetComponent<Text>().text = n2;

            if (n3 != null) 
                DayEffect.transform.Find("Number 3").GetComponent<Text>().text = n3;

            DayEffect.active = true;

            Utils.ToggleObjectActiveAfterTime(DayEffect);
        }

    }





    }