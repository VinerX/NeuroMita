using Il2Cpp;
using Il2CppEPOOutline;
using MelonLoader;
using MitaAI.Mita;
using System;
using System.Collections;
using System.Linq;
using System.Runtime.Versioning;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace MitaAI
{
    // В теории сюда уйдет вся стартовая настройка
    public static class TotalInitialization
    {
        static ObjectInteractive exampleComponent;
        public static HashSet<string> additiveLoadedScenes = new HashSet<string>();

        // Инициализация шаблонного компонента
        public static void InitExampleComponent(Transform world)
        {
            GameObject pult = Utils.TryfindChild(world, "Quests/Quest 1/Addon/Interactive Aihastion");
            if (pult != null)
            {
                exampleComponent = ObjectInteractive.Instantiate(pult.GetComponent<ObjectInteractive>());
                MelonLogger.Msg("Example component initialized!");
            }
            else
            {
                MelonLogger.Msg("Failed to find template object!");
            }
        }
        #region InitObjects
        public static void InitObjects()
        {
            //TotalInitialization.initTVGames(MitaCore.worldHouse);
            TotalInitialization.initCornerSofa(MitaCore.worldHouse);
        }


        public static void initCornerSofa(Transform world)
        {
            MelonLogger.Msg("initCornerSofa");
            GameObject sofa = Utils.TryfindChild(world, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/SofaChair");
            GameObject sofaChil = new GameObject("OI");
            sofaChil.transform.parent = sofa.transform;
            sofaChil.transform.localPosition = new Vector3(-0.4855f, 0.3255f, 0.0982f);
            sofaChil.transform.localRotation = Quaternion.Euler(10f, 90f, 90f);
            var objectAnimationPlayer = sofaChil.AddComponent<ObjectAnimationPlayer>();
            var objectInteractive = sofa.AddComponent<ObjectInteractive>();
            objectAnimationPlayer.angleHeadRotate = 70;
            //Utils.CopyComponentValues(exampleComponent, objectInteractive);

            objectAnimationPlayer.animationStart = PlayerAnimationModded.getPlayerAnimationClip("Player StartSit1");
            objectAnimationPlayer.animationLoop = PlayerAnimationModded.getPlayerAnimationClip("Player Sit");
            objectAnimationPlayer.animationStop = PlayerAnimationModded.getPlayerAnimationClip("Player Stand");
            //objectInteractive.eventClick = EventsProxy.ChangeAnimationEvent(sofa, "SofaSit");

            //GameObject GameAihastion = Utils.TryfindChild(world, "Quests/Quest 1/Game Aihastion");

        }
    
        public static void initTVGames(Transform world)
        {
            GameObject pult = Utils.TryfindChild(world, "Quests/Quest 1/Addon/Interactive Aihastion");
            pult.active = false;
            pult.GetComponent<ObjectInteractive>().active = true;

            GameObject pultCopy= GameObject.Instantiate(pult, pult.transform.parent);

            MinigamesTelevisionController minigamesTelevisionController =  Utils.TryfindChild(world, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/TV/GameTelevision").GetComponent<MinigamesTelevisionController>();
            minigamesTelevisionController.destroyAfter = false;

         

            pultCopy.active = true;

            GameObject GameAihastion = Utils.TryfindChild(world, "Quests/Quest 1/Game Aihastion");
        }

        public static void initConsole(Transform worldBasement)
        {
            GameObject console = Utils.TryfindChild(MitaCore.worldBasement, "Act/Console");
            MitaCore.Instance.cartridgeReader = console;
            AudioControl.cartAudioSource = console.AddComponent<AudioSource>();

            ObjectInteractive objectInteractive = console.GetComponent<ObjectInteractive>();
            console.GetComponent<Animator>().enabled = true;
            console.GetComponent<Outlinable>().enabled = true;

            //GameObject console_res = GameObject.Instantiate(console, console.transform.parent);
            //console_res.name = console.name+"_res";
            //console_res.active = false;

            Utils.TryTurnChild(MitaCore.worldBasement, "Quests/Quest1 Start/Dialogues Привет - Передай ключ",false);
            Utils.TryTurnChild(MitaCore.worldBasement, "Quests/Quest1 Start/Dialogues Console", false);
            objectInteractive.active = true;
            objectInteractive.destroyComponent = false;

            ObjectAnimationPlayer drop = Utils.TryfindChild(MitaCore.worldBasement, "Quests/Quest1 Start/AnimationPlayer Drop").GetComponent<ObjectAnimationPlayer>();
            //drop.eventsPlayer = new Il2CppSystem.Collections.Generic.List<UnityEngine.Events.UnityEvent>();
            //drop.animationStart.events = new Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppReferenceArray<AnimationEvent>(0);

            //MitaCore.AddAnimationEvent(drop.gameObject, drop.animationStart,"ConsoleEnd");
            //drop.eventStartAnimaiton = null;
            //drop.eventStartLoop = null;
            drop.eventFinish = EventsProxy.ChangeAnimationEvent(drop.gameObject, "ConsoleEnd");
            //GameObject console = Utils.TryfindChild(MitaCore.worldBasement, "Act/Console");

        }
        #endregion



        #region getObjectsFromOtherScenes

        public static List<GameObject> objectsFromMenu = new List<GameObject>();
        public static void GetObjectsFromMenu()
        {
            MelonLogger.Msg("Start GetObjectsFromMenu");

            GameObject MusicToSave = new GameObject();
            MusicToSave.transform.SetParent(GameObject.Find("Game").transform);
            MusicToSave.name = "MusicToSave";

            GameObject Menu = GameObject.Find("MenuGame");
            GameObject Sounds = Menu.transform.Find("Sounds").gameObject;

            GameObject music = null;
            try { 

                music = Sounds.transform.Find("Music").gameObject;
                music = GameObject.Instantiate(music);
                music.active = false;
                music.name = "Music happy intensive";
                music.transform.parent = MusicToSave.transform;
                objectsFromMenu.Add(music);


            }
            catch (Exception e) { MelonLogger.Error(e); }
            try
            {
                music = Sounds.transform.Find("MusicCloth").gameObject;
                music = GameObject.Instantiate(music);
                music.active = false;
                music.name = "Music relax";
                music.transform.parent = MusicToSave.transform;
                objectsFromMenu.Add(music);



            }
            catch (Exception e) { MelonLogger.Error(e); }

            try
            {
                music = Sounds.transform.Find("MusicDescription").gameObject;
                music = GameObject.Instantiate(music);
                music.active = false;
                music.name = "Music puzzle style";
                music.transform.parent = MusicToSave.transform;
                objectsFromMenu.Add(music);

            }
            catch (Exception e) { MelonLogger.Error(e); }





            MelonLogger.Msg("End GetObjectsFromMenu");
        }

        public static IEnumerator AddOtherScenes()
        {
            // Запускаем корутину для ожидания загрузки сцены
            string sceneToLoad;

            bool loadMusic = true;

            if (loadMusic)
            {
                sceneToLoad = "Scene 12 - Freak";
                additiveLoadedScenes.Add(sceneToLoad);
                yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldFreak(sceneToLoad));

                sceneToLoad = "Scene 17 - Dreamer";
                additiveLoadedScenes.Add(sceneToLoad);
                yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldDreamer(sceneToLoad));

                sceneToLoad = "Scene 2 - InGame";
                additiveLoadedScenes.Add(sceneToLoad);
                yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldInGame(sceneToLoad));

                sceneToLoad = "Scene 8 - ReRooms";
                additiveLoadedScenes.Add(sceneToLoad);
                yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldReRooms(sceneToLoad));
            }




            sceneToLoad = "Scene 7 - Backrooms";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldBackrooms(sceneToLoad));

            sceneToLoad = "Scene 14 - MobilePlayer";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateMobilePlayer(sceneToLoad));

            sceneToLoad = "Scene 10 - ManekenWorld";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldManekenWorld(sceneToLoad));

            sceneToLoad = "Scene 6 - BasementFirst";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldBasement(sceneToLoad));

            sceneToLoad = "Scene 19 - Glasses";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldGlasses(sceneToLoad));
     
            sceneToLoad = "Scene 11 - Backrooms";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldBackrooms2(sceneToLoad));

            sceneToLoad = "Scene 3 - WeTogether";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldTogether(sceneToLoad));


            yield return MelonCoroutines.Start(AfterAllLoadded());


        }
        private static IEnumerator WaitForSceneAndInstantiateWorldBasement(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            MitaCore.worldBasement = FindObjectInScene(scene.name, "World");
            if (MitaCore.worldBasement == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }

            MelonLogger.Msg($"Object found: {MitaCore.worldBasement.name}");
            
            GameObject cat = GameObject.Instantiate(AssetBundleLoader.LoadAssetByName<GameObject>(AssetBundleLoader.bundle, "CatPrefab"));
            cat.name = "Cat";
            cat.transform.SetPositionAndRotation(new Vector3(17.012f, -1.5668f, -10.5676f), Quaternion.Euler(357.514f, 149.9964f, 0));
            cat.transform.localScale = new Vector3(0.07f, 0.07f, 0.07f);
            cat.transform.parent = MitaCore.worldBasement.Find("House");

            try
            {
                Transform door = MitaCore.worldBasement.transform.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/General/BasementDoorFrame/BasementDoor");
                door.parent.gameObject.GetComponent<Animator>().enabled = false;
                door.parent.gameObject.GetComponent<Events_Data>().enabled = false;
                door.FindChild("BasementDoorHandle").gameObject.active = false;
                door.localRotation = Quaternion.EulerAngles(0, 0, 270);
                door.gameObject.active = true;
            }
            catch (Exception ex)
            {
                MelonLogger.Error(ex);
            }
   


            InitializeGameObjectsWhenReady();
        }
        private static IEnumerator WaitForSceneAndInstantiateWorldBackrooms2(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            MitaCore.worldBackrooms2 = FindObjectInScene(scene.name, "World");
            if (MitaCore.worldBackrooms2 == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            MitaCore.worldBackrooms2.gameObject.SetActive(false);
            MelonLogger.Msg($"Object found: {MitaCore.worldBackrooms2.name}");
            try
            {
                MitaGames.ManekenTemplate = GameObject.Instantiate(Utils.TryfindChild(MitaCore.worldBackrooms2, "Quest/Quest 1 (Room 1 - Room 6)/Mita Maneken 1"), MitaCore.worldHouse);

                MitaGames.ManekenTemplate.transform.position = Vector3.zero;
                MitaGames.ManekenTemplate.transform.Find("MitaManeken 1").gameObject.GetComponent<Mob_Maneken>().speedNav = 4;

                AudioControl.addMusicObject(MitaCore.worldBackrooms2.Find("Sounds/Music Backrooms").gameObject, "Music puzzle 2");

            }
            catch (Exception ex)
            {

                MelonLogger.Msg($"WaitForSceneAndInstantiate2 found: {ex}");
            }

            SceneManager.UnloadScene(sceneToLoad);

        }
        private static IEnumerator WaitForSceneAndInstantiateWorldTogether(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            MitaCore.worldTogether = FindObjectInScene(scene.name, "World");
            if (MitaCore.worldTogether == null)
            {
                MelonLogger.Msg("MitaCore.worldTogether object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            MitaCore.worldTogether.gameObject.SetActive(false);
            PlayerAnimationModded.FindPlayerAnimationsRecursive(MitaCore.worldTogether.transform);
            PlayerAnimationModded.Check();

            InitObjects();


            //SceneManager.UnloadScene(sceneToLoad);

        }

        private static IEnumerator WaitForSceneAndInstantiateWorldInGame(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform world = FindObjectInScene(scene.name, "World");
            if (world == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            world.gameObject.SetActive(false);


            try
            {
                AudioControl.addMusicObject(world.Find("Audio/Ambient Music").gameObject, "Morning music");
                AudioControl.addMusicObject(world.Find("Audio/Ambient Horror 1").gameObject);
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);

        }

        private static IEnumerator WaitForSceneAndInstantiateWorldBackrooms(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform world = FindObjectInScene(scene.name, "World");
            if (world == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
    
            try
            {
                MelonLogger.Msg($"Object found: {world.name}");

                MitaCore.CappyObject = GameObject.Instantiate(Utils.TryfindChild(world, "Acts/Mita Кепка"), MitaCore.worldHouse);
                MitaCore.KindObject = GameObject.Instantiate(Utils.TryfindChild(world, "Acts/Mita Добрая"), MitaCore.worldHouse);

                world.gameObject.SetActive(false);
                

               


                AudioControl.addMusicObject(world.Find("Sounds/Music Cap").gameObject, "Music cappy playful");
                AudioControl.addMusicObject(world.Find("Sounds/Music Ambient Start").gameObject, "Music cappy playful 2");
                
            }
       
            catch (Exception ex)
            {

                MelonLogger.Error($"{scene.name} founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);

        }

        private static IEnumerator WaitForSceneAndInstantiateWorldReRooms(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            GameObject world = FindObjectInScene(scene.name, "World").gameObject;
            if (world == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
       

           
            try
            {
                MelonLogger.Msg($"Object found: {world.name}");
                world.gameObject.SetActive(false);

                AudioControl.addMusicObject(world.transform.Find("Sounds/Music").gameObject, "Music calm");
                AudioControl.addMusicObject(world.transform.Find("Sounds/Music Alternative").gameObject, "Music for concentration");
                
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"{world.name} founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);
        }
        
        private static IEnumerator WaitForSceneAndInstantiateWorldManekenWorld(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform worldManekenWorld = FindObjectInScene(scene.name, "World");
            if (worldManekenWorld == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            worldManekenWorld.gameObject.SetActive(false);

            MelonLogger.Msg($"Object found: {worldManekenWorld.name}");
            try
            {
                MitaCore.ShortHairObject = GameObject.Instantiate(Utils.TryfindChild(worldManekenWorld, "General/Mita Old"), MitaCore.worldHouse);
                MitaCore.ShortHairObject.active = false;

            }

            catch (Exception ex)
            {

                MelonLogger.Error($"Shorthair founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);

        }
        private static IEnumerator WaitForSceneAndInstantiateMobilePlayer(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform world = FindObjectInScene(scene.name, "World");
            if (world == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            world.gameObject.SetActive(false);

            MelonLogger.Msg($"Object found: {world.name}");
            try
            {
                MitaAnimationModded.bat= GameObject.Instantiate(Utils.TryfindChild(world, "Quest/Quest 1/Mita KitchenAttack/MitaPerson Mita/Armature/Hips/Spine/Chest/Right shoulder/Right arm/Right elbow/Right wrist/Right item/Bat"), MitaCore.worldHouse);
                MitaAnimationModded.bat.transform.SetParent(MitaCore.Instance.MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Right shoulder/Right arm/Right elbow/Right wrist/Right item"));
                MitaAnimationModded.bat.transform.localPosition = Vector3.zero;
                MitaAnimationModded.bat.transform.localRotation = Quaternion.identity;
                MitaAnimationModded.bat.active = false;

                MitaCore.CreepyObject = GameObject.Instantiate(Utils.TryfindChild(world, "Quest/Quest 1/CreepyMita"), MitaCore.worldHouse);
                MitaCore.CreepyObject.active = false;
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"Founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);
        }
        private static IEnumerator WaitForSceneAndInstantiateWorldGlasses(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform worldGlasses = FindObjectInScene(scene.name, "World");
            if (worldGlasses == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            worldGlasses.gameObject.SetActive(false);

            MelonLogger.Msg($"Object found: {worldGlasses.name}");
            try
            {
                MitaCore.MilaObject = GameObject.Instantiate(Utils.TryfindChild(worldGlasses, "Quests/General/Mila Glasses"), MitaCore.worldHouse);
                MitaCore.MilaObject.active = false;

                AudioControl.addMusicObject(worldGlasses.Find("Audio/Music").gameObject, "Music backround calm");
                AudioControl.addMusicObject(worldGlasses.Find("Audio/MusicBag").gameObject, "Music tension strange");
                AudioControl.addMusicObject(worldGlasses.Find("Audio/Music Echo").gameObject, "Embient hard");
                
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"Mila founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);
        }

        private static IEnumerator WaitForSceneAndInstantiateWorldFreak(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform world = FindObjectInScene(scene.name, "World");
            if (world == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            world.gameObject.SetActive(false);

            MelonLogger.Msg($"Object found: {world.name}");
            try
            {
                // Инициализация CreepyMita и удаление аудио компонентов
                MitaCore.CreepyObject = GameObject.Instantiate(Utils.TryfindChild(world, "Acts/CreepyMita/CreepyMita"), MitaCore.worldHouse);
                // Отключаем звук CreepyMita Teeth
                GameObject audioTeeth = Utils.TryfindChild(MitaCore.CreepyObject.transform, "Armature/Hips/Spine/Chest/Neck2/Neck1/Head/AudioTeeth");
                if (audioTeeth != null)
                {
                    AudioSource audioSource = audioTeeth.GetComponent<AudioSource>();
                    if (audioSource != null && audioSource.clip != null && audioSource.clip.name == "CreepyMita Teeth")
                    {
                        audioSource.clip = null;
                        MelonLogger.Msg("Successfully removed 'CreepyMita Teeth' audio clip from AudioTeeth");
                    }
                    else
                    {
                        MelonLogger.Msg($"Audio clip is either null or not 'CreepyMita Teeth' (current: {(audioSource != null && audioSource.clip != null ? audioSource.clip.name : "null")})");
                    }
                }
                else
                {
                    MelonLogger.Error("Failed to find AudioTeeth object");
                }
                
                MitaCore.CreepyObject.active = false;

                // Добавление музыкальных объектов
                AudioControl.addMusicObject(world.Find("Sounds/Ambient Evil 1").gameObject, "Embient horrific tension");
                AudioControl.addMusicObject(world.Find("Sounds/Ambient Evil 2").gameObject, "Embient horrific waiting");
                AudioControl.addMusicObject(world.Find("Sounds/Ambient Evil 3").gameObject, "Embient horrific tension large");
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"CreepyMita initialization error: {ex}");
            }
            
            SceneManager.UnloadScene(sceneToLoad);
        }

        private static IEnumerator WaitForSceneAndInstantiateWorldDreamer(string sceneToLoad)
        {
            // Загружаем сцену
            MelonLogger.Msg($"Loading scene: {sceneToLoad}");
            additiveLoadedScenes.Add(sceneToLoad);
            SceneManager.LoadScene(sceneToLoad, LoadSceneMode.Additive);

            // Ожидание завершения загрузки сцены
            Scene scene;
            do
            {
                scene = SceneManager.GetSceneByName(sceneToLoad);
                yield return null; // Ждем следующий кадр
            } while (!scene.isLoaded);

            MelonLogger.Msg($"Scene {sceneToLoad} loaded.");

            // Находим объект в загруженной сцене
            Transform worldDreamer = FindObjectInScene(scene.name, "World");
            if (worldDreamer == null)
            {
                MelonLogger.Msg("World object not found.");
                yield break; // Прерываем выполнение, если объект не найден
            }
            worldDreamer.gameObject.SetActive(false);

            MelonLogger.Msg($"Object found: {worldDreamer.name}");
            try
            {
                MitaCore.SleepyObject = GameObject.Instantiate(Utils.TryfindChild(worldDreamer, "General/Mita Dreamer"), MitaCore.worldHouse);
                
                // Включаем коллайдер
                Collider[] colliders = MitaCore.SleepyObject.GetComponentsInChildren<Collider>(true);
                foreach (Collider collider in colliders)
                {
                    collider.enabled = true;
                    MelonLogger.Msg($"Enabled collider on: {collider.gameObject.name}");
                }
                
                // Деактивируем Particle Sleep который отвечает за эффект сна   
                GameObject particleSleep = Utils.TryfindChild(MitaCore.SleepyObject.transform, "Mita Dream/Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Particle Sleep");
                if (particleSleep != null)
                {
                    particleSleep.SetActive(false);
                    MelonLogger.Msg("Successfully deactivated Particle Sleep");
                }
                else
                {
                    MelonLogger.Error("Failed to find Particle Sleep object");
                }

                // Отключаем аудио клип Mita Sleep 1
                GameObject audioSoundsLoop = Utils.TryfindChild(MitaCore.SleepyObject.transform, "Mita Dream/Armature/Hips/Spine/Chest/Neck2/Neck1/Head/AudioSoundsLoop");
                if (audioSoundsLoop != null)
                {
                    AudioSource audioSource = audioSoundsLoop.GetComponent<AudioSource>();
                    if (audioSource != null && audioSource.clip != null && audioSource.clip.name == "Mita Sleep 1")
                    {
                        audioSource.clip = null;
                        MelonLogger.Msg("Successfully removed 'Mita Sleep 1' audio clip from AudioSoundsLoop");
                    }
                    else
                    {
                        MelonLogger.Msg($"Audio clip is either null or not 'Mita Sleep 1' (current: {(audioSource != null && audioSource.clip != null ? audioSource.clip.name : "null")})");
                    }
                }
                else
                {
                    MelonLogger.Error("Failed to find AudioSoundsLoop object");
                }

                MitaCore.SleepyObject.SetActive(false);
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"{worldDreamer.name} founding error: {ex}");
            }
            
            SceneManager.UnloadScene(sceneToLoad);
        }

        private static IEnumerator AfterAllLoadded()
        {
            

            MelonLogger.Msg("After all loaded");
            MitaCore.character MitaToStart = Settings.Get<MitaCore.character>("MitaType");
            MelonLogger.Msg($"Mita from settings {MitaToStart}");
            if (MitaCore.Instance.currentCharacter != MitaToStart)
            {
                MelonLogger.Msg($"Run change Mita");
                MitaCore.Instance.changeMita(null,character : MitaToStart);
            }
            yield return new WaitForSeconds(1f);

            EventsModded.sceneEnter(MitaToStart);

            MitaCore.AllLoaded = true;
            TestingGround();
        }
        
        private static void TestingGround()
        {
            try
            {

                //GameObject MitaPrefab = GameObject.Instantiate(AssetBundleLoader.LoadAssetByName<GameObject>(AssetBundleLoader.bundle, "MitaPrefab"));


                //MitaPrefab.name = "Mita Prefab 2003";
                //MitaCore.Instance.changeMita(MitaPrefab, MitaCore.character.Mita);

                //ShaderReplacer.ReplaceShaders(MitaCore.worldHouse.gameObject);
                //ShaderReplacer.ReplaceShaders(MitaCore.worldBasement.gameObject);

                // Звук
                //GameObject testSound = new GameObject("TestSound");
                //AudioSource audioSource = testSound.AddComponent<AudioSource>();
                //AudioClip audioClip = AssetBundleLoader.LoadAssetByName<AudioClip>(AssetBundleLoader.bundle, "MusicBoss");
                //audioSource.clip = audioClip;
                //audioSource.Play();
            }
            catch (Exception e)
            {

                MelonLogger.Error(e);
            }

        }
        
        private static void InitializeGameObjectsWhenReady()
        {

            // Ваши действия после инициализации MitaCore.worldBasement
            try
            {
                // Пробуем найти и безопасно преобразовать объект в Transform
                var wardrobeTransform = MitaCore.worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom/Bedroom Wardrobe");

                try
                {
                    var wardrobeGameObject = wardrobeTransform.gameObject;
                    wardrobeGameObject.GetComponent<BoxCollider>().enabled = false;
                    //wardrobeGameObject.GetComponent<BoxCollider>().isTrigger = true;
                    wardrobeGameObject.AddComponent<WardrobeFix>();


                    Transform door =  wardrobeGameObject.transform.Find("Bedroom WardrobeDoorL");
                    door.gameObject.AddComponent<BoxCollider>();
                    door.localRotation = Quaternion.Euler(0, 0, 335);

                    door = wardrobeGameObject.transform.Find("Bedroom WardrobeDoorR");
                    door.gameObject.AddComponent<BoxCollider>();
                    door.localRotation = Quaternion.Euler(0, 0, 180);




                }
                catch (Exception)
                {
                    MelonLogger.Msg("Error while handling wardrobe transform.");
                }

                try
                {
                    TotalInitialization.initConsole(MitaCore.worldBasement);
                }
                catch (Exception ex)
                {

                    MelonLogger.Msg("Error while handling initConsole: " + ex);
                }

                Utils.TryfindChild(MitaCore.worldBasement, "Act/ContinueScene").SetActive(false);
                Utils.TryfindChild(MitaCore.worldBasement, "Quests/Quest1 Start").SetActive(true);
                Utils.TryfindChild(MitaCore.worldBasement, "Quests/Quest1 Start/Trigger Near").SetActive(false);
                //Utils.TryfindChild(MitaCore.worldBasement, "/Act/ContinueScene\"").SetActive(false);

                //Utils.TryTurnChild(MitaCore.worldBasement, "Quests/Quest1 Start",false);
                Utils.TryTurnChild(MitaCore.worldBasement, "Mita Future", false);
                try
                {
                    var door = Utils.TryfindChild(MitaCore.worldBasement, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/General/BasementDoorFrame");
                    door.SetActive(true);
                    Utils.TryTurnChild(door.transform, "BasementDoor", false);
                }
                catch (Exception)
                {


                }
                // Работа с AnimationKiller
                MelonLogger.Msg("AnimationKiller start");
                string objectPath = "Quests/Quest2 HideAndSeek/Animation Killer";
                MitaCore.Instance.AnimationKiller = FindAndInstantiateObject(MitaCore.worldBasement, objectPath, "222");

                MitaCore.Instance.knife = FindAndInstantiateObject(MitaCore.Instance.AnimationKiller.transform, "Mita/MitaPerson Mita/Armature/Hips/Spine/Chest/Right shoulder/Right arm/Right elbow/Right wrist/Right item/Knife", "333");
                MitaCore.Instance.knife.transform.SetParent(Utils.TryfindChild(MitaCore.Instance.MitaPersonObject.transform, "Armature/Hips/Spine/Chest/Right shoulder/Right arm/Right elbow/Right wrist/Right item").transform);
                MitaCore.Instance.knife.transform.localPosition = new Vector3(0, 0, 0);
                MitaCore.Instance.knife.transform.localRotation = Quaternion.identity;
                MitaCore.Instance.knife.SetActive(false);

                //AnimationKiller.GetComponent<Location6_MitaKiller>().mita = Mita.transform;
                var musicTension = Utils.TryfindChild(MitaCore.worldBasement, "Sounds/Ambient 1");
                
                musicTension.name = "Music 4 Tension";
                AudioControl.addMusicObject(musicTension);

                MitaCore.Instance.AnimationKiller.SetActive(false);
                //DeleteChildren(AnimationKiller.transform.Find("PositionsKill").gameObject);

                if (MitaCore.Instance.AnimationKiller != null)
                {
                    MelonLogger.Msg("AnimationKiller instantiated and ready for use.");
                    var mitaChild = MitaCore.Instance.AnimationKiller.transform.Find("Mita");

                    if (mitaChild != null)
                    {
                        //mitaChild.gameObject.SetActive(false);
                        //Mita.transform.SetParent(AnimationKiller.transform, true);
                        MelonLogger.Msg("Child object 'Mita' deactivated.");
                    }
                    else
                    {
                        MelonLogger.Msg("Child object 'Mita' not found.");
                    }
                }
                else
                {
                    MelonLogger.Msg("Failed to initialize AnimationKiller.");
                }
            }
            catch (Exception e)
            {
                MelonLogger.Msg($"Error in InitializeGameObjectsWhenReady: {e.Message}");
            }
        }

        public static Transform FindObjectInScene(string sceneName, string objectPath)
        {
            // Получаем сцену по имени
            Scene scene = SceneManager.GetSceneByName(sceneName);

            // Проверяем, загружена ли сцена
            if (!scene.IsValid() || !scene.isLoaded)
            {
                MelonLoader.MelonLogger.Msg($"Scene {sceneName} not loaded or broken");
                return null;
            }

            // Получаем корневые объекты сцены
            var rootObjects = scene.GetRootGameObjects();
            foreach (var rootObject in rootObjects)
            {
                MelonLogger.Msg(rootObject.name);
                if (rootObject.name == "World")
                {
                    return rootObject.transform;
                }
            }

            MelonLoader.MelonLogger.Msg($" {objectPath} not found in {sceneName}.");
            return null;
        }
        private static GameObject FindAndInstantiateObject(Transform parent, string path, string logPrefix)
        {
            try
            {
                MelonLogger.Msg($"{logPrefix}: Attempting to find object at path: {path}");

                // Проверяем, что родитель не null
                if (parent == null)
                {
                    MelonLogger.Msg($"{logPrefix}: Parent is null. Cannot search for object.");
                    return null;
                }

                // Ищем объект по указанному пути
                Transform target = parent.Find(path);
                if (target == null)
                {
                    MelonLogger.Msg($"{logPrefix}: Object not found at path: {path}");
                    return null;
                }

                // Логируем успешный поиск
                MelonLogger.Msg($"{logPrefix}: Object found. Instantiating...");
                GameObject instance = GameObject.Instantiate(target.gameObject);

                // Проверяем успешную инстанциацию
                if (instance == null)
                {
                    MelonLogger.Msg($"{logPrefix}: Failed to instantiate object.");
                    return null;
                }

                MelonLogger.Msg($"{logPrefix}: Object instantiated successfully.");
                return instance;
            }
            catch (Exception e)
            {
                MelonLogger.Msg($"{logPrefix}: Exception occurred - {e.Message}");
                return null;
            }
        }

        #endregion

    }

}
