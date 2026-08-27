using Il2Cpp;
using MelonLoader;
using System.Text.RegularExpressions;
using UnityEngine;
namespace MitaAI.Mita
{
    public static class MitaFaceAnimationModded
    {

        public static string getFaceInfo(GameObject MitaPersonObject)
        {
            if (MitaPersonObject == null) return "";

            string info = "";

            var heartNeon = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Right Eye/heartNeon");
            if (heartNeon != null && heartNeon.gameObject.active)
            {
                info += "\nВ твоих глазах светятся розовые сердечки";
            }
            var glasess = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Mita'sGlasses");
            if (glasess != null && glasess.gameObject.active)
            {
                info += "\nYou wear glasses";
            }

            return info;
        }

        public static (List<string>, string) ExtractEmotions(string response)
        {

            MelonLogger.Msg($"Inside ExtractEmotions start: " + response);
            List<string> emotions = new List<string>();
            string pattern = @"<e>(.*?)</e>";
            MatchCollection matches = Regex.Matches(response, pattern);

            foreach (Match match in matches)
            {
                if (match.Success)
                {
                    emotions.Add(match.Groups[1].Value);
                }
            }

            // Удаляем теги эмоций из текста
            string cleanedResponse = Regex.Replace(response, @"<e>.*?</e>", "");

            MelonLogger.Msg($"Inside ExtractEmotions end: " + cleanedResponse);
            return (emotions, cleanedResponse);

        }

        public static(EmotionType, string) SetEmotionBasedOnResponse(string response)
        {
            MelonLogger.Msg($"Inside SetEmotionBasedOnResponse: " + response);
            try
            {
                var (emotions, cleanedResponse) = ExtractEmotions(response);
                EmotionType emotion = EmotionType.none;
                if (emotions.Count > 0)
                {
                    Enum.TryParse<EmotionType>(emotions[0], true, out var result);

                    MitaCore.Instance.Mita.FaceEmotionType(result);
                    if (emotions.Count > 1)
                    {
                        Enum.TryParse<EmotionType>(emotions[1], true, out var result2);
                        emotion = result2;
                    }

                }
                MelonLogger.Msg($"Inside SetEmotionBasedOnResponse end: " + cleanedResponse);
                return (emotion, cleanedResponse);
            }
            catch (Exception ex)
            {
                MelonLogger.Msg($"Error extracting emotion: {ex.Message}");
                //Mita.FaceEmotionType(GetRandomEmotion());
                return (EmotionType.none, response); // Если произошла ошибка, возвращаем исходный текст
            }
        }

        public static string SetFaceStyle(string response)
        {

            // Регулярное выражение для извлечения эмоций
            string pattern = @"<f>(.*?)</f>";
            Match match = Regex.Match(response, pattern);

            string faceStyle = string.Empty;
            string cleanedResponse = Regex.Replace(response, @"<f>.*?</f>", ""); // Очищаем от всех тегов

            if (match.Success)
            {
                // Если эмоция найдена, устанавливаем её в переменную faceStyle
                faceStyle = match.Groups[1].Value;
            }

            try
            {

                //if (MitaCore.Instance.currentCharacter != characterType.Crazy)
                //{
                  //  MelonLogger.Error("SetFaceStyleMita Not crazy");
                    //return cleanedResponse;
                //}


                // Проверка на наличие объекта Mita перед применением эмоции
                if (MitaCore.Instance.Mita == null || MitaCore.Instance.Mita.gameObject == null)
                {
                    MelonLogger.Error("SetFaceStyle Mita object is null or Mita.gameObject is not active.");
                    return cleanedResponse; // Возвращаем faceStyle и очищенный текст
                }

                // Устанавливаем лицо, если оно найдено
                switch (faceStyle)
                {
                    case "Смущаться":
                        //Mita.FaceColorUpdate();
                        MitaCore.Instance.Mita.FaceLayer(1);
                        break;
                    case "Маска грусти":
                        //Mita.FaceColorUpdate();
                        MitaCore.Instance.Mita.FaceLayer(2);
                        break;
                    case "LoveEyesOn":
                        setLoveEye(MitaCore.Instance.MitaPersonObject);
                        break;
                    case "LoveEyesOff":
                        setLoveEye(MitaCore.Instance.MitaPersonObject,false);
                        break;






                    case "GlassesOn":
                        GlassesObj(MitaCore.Instance.MitaPersonObject,true);
                        break;
                    case "GlasessOff":
                        GlassesObj(MitaCore.Instance.MitaPersonObject,false);
                        break;




                    default:
                        //Mita.FaceColorUpdate();
                        try
                        {
                            MitaCore.Instance.Mita.FaceLayer(0);
                        }
                        catch (Exception)
                        {
                        }
                        
                        break;
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Problem with FaceStyle: {ex}");
            }

            // Возвращаем кортеж: лицо и очищенный текст
            return cleanedResponse;
        }

        public static void GlassesObj(GameObject MitaPersonObject,bool on)
        {


            var Glasess = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Mita'sGlasses")?.gameObject;

            if (Glasess == null)
            {
                Glasess = GameObject.Instantiate(TotalInitialization.Glasses, MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head").transform);
                Glasess.transform.localPosition = new Vector3(0,0.085f,0.125f);
                Glasess.transform.localEulerAngles = new Vector3(270, 0, 0);
                Glasess.name = "Mita'sGlasses";
                // TO DO Чекнуть поворот

                Glasess.transform.Find("Mita'sGlassesLeftEar").transform.SetLocalPositionAndRotation(new Vector3(-0.0787f,0,0), Quaternion.identity);
                Glasess.transform.Find("Mita'sGlassesRightEar").transform.SetLocalPositionAndRotation(new Vector3(0.0787f, 0, 0), Quaternion.identity);
            }

            Glasess.SetActive(on);

        }

        static void setLoveEye(GameObject MitaPersonObject, bool on = true)
        {

            var RightEye = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Right Eye");
            var LeftEye = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Left Eye");


            // Прям на глаза ставить
            // 0 0,025 0
            // 90 0 0

            GameObject heartNeon = null;
            GameObject heartNeonL = null;
            try
            {
               heartNeon  = RightEye.Find("HeartNeon").gameObject;
               heartNeonL = LeftEye.Find("HeartNeonL").gameObject;

            }
            catch (Exception)
            {

            }

            MelonLogger.Msg("setLoveEye 2");

            if (heartNeon == null)
            {
                heartNeon = GameObject.Instantiate(TotalInitialization.HeartNeonTemplate, RightEye);
                heartNeon.transform.localPosition = new Vector3(0,0.025f,0);
                heartNeon.transform.localEulerAngles = new Vector3(90,0,0);
                heartNeon.name = "HeartNeon";


                heartNeonL = GameObject.Instantiate(TotalInitialization.HeartNeonTemplate, LeftEye);
                heartNeonL.transform.localPosition = new Vector3(0, 0.025f, 0);
                heartNeonL.transform.localEulerAngles = new Vector3(90, 0, 0);
                heartNeonL.name = "HeartNeonL";
            }
            MelonLogger.Msg("setLoveEye 3");

            heartNeon.SetActive(on);
            heartNeonL.SetActive(on);


        }

    }

}
