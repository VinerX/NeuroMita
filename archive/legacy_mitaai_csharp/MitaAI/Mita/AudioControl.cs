using Il2Cpp;
using MelonLoader;
using System.Collections;
using System.Text.RegularExpressions;
using UnityEngine;


namespace MitaAI.Mita
{
    static class AudioControl
    {
        // Словарь для хранения музыкальных объектов
        private static Dictionary<string, GameObject> _audioObjects = new Dictionary<string, GameObject>();

        public static GameObject currentAudioObject;
        public static GameObject templateAudioObject;
        public static Transform sound_parent;

        public static DataValues_Sounds dataValues_Sounds;
        public static AudioClip chibiMitaAudio;
        static AudioSource mitaAudioSourse;
        public static GameObject MitaDualogueSpeak;

        public static AudioSource cartAudioSource;
        public static AudioSource playerAudioSource;

        private static GameObject fingerClick;

        public static string getCurrrentMusic()
        {
            if (currentAudioObject == null) return "None";
            else return currentAudioObject.name;
        }
        public static string MusicInfo()
        {
            string musicInfo = "";
            try
            {
                musicInfo += $"\nCurrent music is {getCurrrentMusic()},available options to set using block <music>: ";

                foreach (string item in _audioObjects.Keys)
                {
                    musicInfo += $"<music>{item}</music>";
                }
                return musicInfo;
            }
            catch (Exception ex) { 

                MelonLogger.Error(ex);
                return "musicInfo";
               
            }
 
        }

        // Метод для инициализации словаря
        public static void Init(Transform worldHouse)
        {

            sound_parent =  MitaCore.worldHouse.FindChild("Audio");

            // Добавляем объекты в словарь с обработкой исключений
            try
            {
                _audioObjects["Music 1"] = worldHouse.Find("Audio/Music 1").gameObject;
                currentAudioObject = _audioObjects["Music 1"];
                templateAudioObject = currentAudioObject;
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Failed to find or add 'Music 1': {e.Message}");
            }

            fingerClick = worldHouse.Find("Audio/Audio ClickFinger").gameObject;
            fingerClick.GetComponent<Audio_DestroyTime>().enabled = false;
            fingerClick.GetComponent<Time_Events>().enabled = false;
            fingerClick.GetComponent<Object_DontDestroy>().enabled = false;
            fingerClick.GetComponent<Achievement_function>().enabled = false;

            try
            {
                _audioObjects["Music BedClick"] = worldHouse.Find("Audio/MusicBedClick").gameObject;
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Failed to find or add 'Music BedClick': {e.Message}");
            }

            try
            {
                _audioObjects["Music 2"] = worldHouse.Find("Audio/Music 2").gameObject;
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Failed to find or add 'Music 2': {e.Message}");
            }

            try
            {
                _audioObjects["Music 3 Tamagochi"] = worldHouse.Find("Audio/Music 3 Tamagochi").gameObject;
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Failed to find or add 'Music 3 Tamagochi': {e.Message}");
            }


            MelonLogger.Msg($"_audioObjects count {_audioObjects.Count()}");


            try
            {
                MitaDualogueSpeak = worldHouse.Find("Dialogues/DialogueMita Speak").gameObject;
                dataValues_Sounds = MitaDualogueSpeak.GetComponent<DataValues_Sounds>();
                chibiMitaAudio = dataValues_Sounds.sounds[0];
                mitaAudioSourse = MitaCore.Instance.MitaObject.transform.Find("MitaPerson Mita/Armature/Hips/Spine").GetComponent<AudioSource>();
                
            }


            catch (Exception e)
            {

                MelonLogger.Error($"Failed to find or add 'Dialogues/DialogueMita Speak': {e.Message}");
            }

            getObjectFromMenu();

            // По умолчанию все объекты выключены
            //   foreach (var audioObject in _audioObjects.Values)
            //{
            //  audioObject.SetActive(false);
            //}
        }


        public static void playFingerClick() {

            MelonCoroutines.Start(playFingerClickWait());
            
        }

        public static IEnumerator playFingerClickWait()
        {

            fingerClick.active = true;
            yield return new WaitForSeconds(2f);
            fingerClick.active = false;
        }

        private static void getObjectFromMenu()
        {

            for (int i = 0; i < TotalInitialization.objectsFromMenu.Count; i++)
            {
                try
                {
                    addMusicObject(TotalInitialization.objectsFromMenu[i]);
                }
                catch (Exception e) { MelonLogger.Error(e); } 

            }

            
        }

        public static void addMusicObject(GameObject gameObject, string newName = "")
        {
            try
            {
                
                if (gameObject.transform.parent != sound_parent)
                {
                    GameObject newMusic = GameObject.Instantiate(templateAudioObject);
                    newMusic.GetComponent<AudioSource>().clip = gameObject.GetComponent<AudioSource>().clip;
                    newMusic.active = false;
                    newMusic.transform.SetParent(templateAudioObject.transform.parent);
                    newMusic.GetComponent<Audio_Pitch>().pitch = 1;
                    newMusic.GetComponent<AudioSource>().pitch = 1;
                    if (newName != "") newMusic.name = newName;
                    else newMusic.name = gameObject.name;
                    _audioObjects[gameObject.name] = newMusic;
                    GameObject.Destroy(gameObject);
                }
                else _audioObjects[gameObject.name] = gameObject;
            }
            catch (Exception ex)
            {

                MelonLogger.Error($"Failed to add music {gameObject.name} to dict {ex}");
            }
            
        }


        public static string ProcessMusic(string response)
        {
            MelonLogger.Msg($"Inside ProcessMusic");
            string pattern = @"<music>(.*?)</music>";
            MatchCollection matches = Regex.Matches(response, pattern);

            foreach (Match match in matches)
            {
                if (match.Success)
                {
                    string music = match.Groups[1].Value;
                    MelonLogger.Msg($"Found {music}");
                    TurnAudio(music);
                    break;
                }
            }

            string result = Regex.Replace(response, @"<music>.*?</music>", "");


            MelonLogger.Msg($"Inside ProcessMusic End");
            return result;

        }
        // Функция для включения объекта по имени и выключения остальных
        public static void TurnAudio(string audioName, bool on = true)
        {
            try
            {
                // Проверяем, существует ли объект с таким именем в словаре
                if (_audioObjects.ContainsKey(audioName))
                {

                    currentAudioObject?.SetActive(false);
                    currentAudioObject = null;

                    // Включаем нужный объект
                    if (audioName != "None")
                    {
                        currentAudioObject = _audioObjects[audioName];
                        currentAudioObject.SetActive(true);
                        currentAudioObject.GetComponent<AudioSource>().Play();
                    }

                }
                else
                {
                    MelonLogger.Msg($"Audio object with name '{audioName}' not found!");
                }
            }
            catch (Exception e)
            {

                MelonLogger.Error($"Tried turn {audioName} error {e}");
            }


        }

        public static IEnumerator PlayTextAudio(string text)
        {
            MelonLogger.Msg("Chibi Sound Play");
            for (int i = 0; i < text.Length; i = i + 3)
            {
                GameObject currentDialog = DialogueControl.InstantiateDialog();
                if (text[i] != ' ')
                {
                    
                    currentDialog.SetActive(true);
                    Dialogue_3DText answer = currentDialog.GetComponent<Dialogue_3DText>();
                    
                    answer.timeSound = AudioControl.chibiMitaAudio.length * UnityEngine.Random.Range(60, 141) * 0.01f;

                    answer.speaker = MitaCore.Instance.Mita?.gameObject;
                    //AudioControl.chibiMitaAudio.SetSpeed(1 * (UnityEngine.Random.Range(1, 40)*0.01) );
                    answer.LoadVoice(AudioControl.chibiMitaAudio);

                    yield return new WaitForSecondsRealtime(0.07f);
                }
                else
                {
                    yield return new WaitForSecondsRealtime(0.14f);
                }
                
                GameObject.Destroy(currentDialog);
            }
        }
    }
}