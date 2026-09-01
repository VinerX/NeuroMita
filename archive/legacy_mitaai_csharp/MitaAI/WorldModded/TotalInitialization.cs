using Il2Cpp;
using Il2CppEPOOutline;
using MelonLoader;
using MitaAI.Mita;
using MitaAI.WorldModded;
using System;
using System.Collections;
using System.Linq;
using System.Runtime.Versioning;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Playables;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using static Il2Cpp.Event_CreateResource;

namespace MitaAI
{
    // В теории сюда уйдет вся стартовая настройка
    public static class TotalInitialization
    {
        static ObjectInteractive exampleComponent;
        public static HashSet<string> additiveLoadedScenes = new HashSet<string>();


        #region ОбъектыКРаспределению

        // Прям на глаза ставить
        // 0 0,025 0
        // 90 0 0
        public static GameObject HeartNeonTemplate;

        // Перед заменой сохрани Face текстуру
        // Это на Head компоненту скопировать
        public static GameObject ScaryFaceTemplate;


        // Надо вместо градиента что-то путное
        public static GameObject InterfaseStatsTemplate;
        #endregion


        public static GameObject Glasses;




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

    
        public static void initTVGames(Transform world)
        {
            GameObject pult = Utils.TryfindChild(world, "Quests/Quest 1/Addon/Interactive Aihastion");
            pult.active = false;
            pult.GetComponent<ObjectInteractive>().active = true;

            GameObject pultCopy= GameObject.Instantiate(pult, world.Find("House"));

            MinigamesTelevisionController minigamesTelevisionController =  Utils.TryfindChild(world, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/TV/GameTelevision").GetComponent<MinigamesTelevisionController>();
            minigamesTelevisionController.destroyAfter = false;

         

            pultCopy.active = true;


            GameObject GameAihastion = Utils.TryfindChild(world, "Quests/Quest 1/Game Aihastion");
        }


        #endregion



        #region getObjectsFromScenes

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


        // Постепенно надо будет сюда перенести все
        public static void initStartSecret2()
        {


            try
            {
                if (MitaCore.worldHouse == null)
                {
                    MelonLogger.Msg($"initStartSecret2 World is null");
                } 





                TVModded.SetTVController();

                Hints.interfaceHintTeplate = GameObject.Instantiate(MitaCore.worldHouse.Find("Quests/Quest 1/Game Card/Interface Game/2D HintKey ShowCard").gameObject);
                Hints.flyingHintTeplate = GameObject.Instantiate(MitaCore.worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom/Bedroom Wardrobe/Bedroom WardrobeDoorR/3D HintKey Open").gameObject);


            }
            catch (Exception ex) 
            {

                MelonLogger.Error(ex);
            }
            


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

            // Это загрузит Ядро!!

            sceneToLoad = "Scene 15 - BasementAndDeath";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateBasementAndDeath(sceneToLoad));


            sceneToLoad = "Scene 7 - Backrooms";
            additiveLoadedScenes.Add(sceneToLoad);
            yield return MelonCoroutines.Start(WaitForSceneAndInstantiateWorldBackrooms(sceneToLoad));


            // Это загрузит кстати Комнату игрока
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
                // Инициализация объекта pipe
                MitaAnimationModded.pipe = MitaCore.worldBasement.Find("World/Mita Future/MitaPerson Future/RightItem/Tube Basement").gameObject;
                MitaAnimationModded.pipe.active = true;



                Transform door = MitaCore.worldBasement.transform.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/General/BasementDoorFrame/BasementDoor");
                door.parent.gameObject.GetComponent<Animator>().enabled = false;
                door.parent.gameObject.GetComponent<Events_Data>().enabled = false;
                door.FindChild("BasementDoorHandle").gameObject.active = false;
                door.localRotation = Quaternion.EulerAngles(0, 0, 270);
                door.gameObject.active = true;

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(MitaCore.worldBasement);
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

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(MitaCore.worldBackrooms2);

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
            PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(MitaCore.worldTogether);
            PlayerAnimationModded.FindPlayerAnimationsRecursive(MitaCore.worldTogether);
            //PlayerAnimationModded.Check();

            try
            {
                HeartNeonTemplate = GameObject.Instantiate(MitaCore.worldTogether.Find("Acts/Mita/MitaPerson Mita/Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Right Eye/HeartNeon").gameObject);
                Glasses = GameObject.Instantiate(MitaCore.worldTogether.Find("Acts/Act General/Mita TakeGlasses/Position Glasses/Mita'sGlasses").gameObject);
                Glasses.active = false;
            }
            finally
            {

            }

            //InitObjects();


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

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(world);


                InterfaseStatsTemplate =  GameObject.Instantiate(world.Find("Tamagotchi/InterfaceTamagotchi/Life/PersonageBack").gameObject);
                InterfaseStatsTemplate.active = false;
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

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(world);

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

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(world.transform);
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"{world.name} founding error: {ex}");
            }
            //yield return new WaitForSeconds(1f);
            SceneManager.UnloadScene(sceneToLoad);
        }
        
        private static IEnumerator WaitForSceneAndInstantiateWorldStartHorror(string sceneToLoad)
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

                ScaryFaceTemplate = new GameObject("ScaryFaceTemplate");
                GameObject.DontDestroyOnLoad(ScaryFaceTemplate);
                var MatTexture = world.Find("Acts/Mita/MitaPerson Mita/Head").GetComponent<Material_Texture>();
                var MatTextureCopy = ScaryFaceTemplate.AddComponent<Material_Texture>();
                MatTextureCopy.indexMaterial = MatTexture.indexMaterial;
                MatTextureCopy.startIndex = MatTexture.startIndex;
                MatTextureCopy.textures = MatTexture.textures;
                MatTextureCopy.valueMaterial = MatTexture.valueMaterial;
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"Shorthair founding error: {ex}");
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
                MitaCore.ShortHairObject = GameObject.Instantiate(world.Find("General/Mita Old").gameObject, MitaCore.worldHouse);
                //var MitaClothes = MitaCore.ShortHairObject.GetComponentInChildren<MitaClothes>();

                //GlobalGame.clothMita = "original";
                //GlobalGame.clothVariantMita = 0;
                //MitaClothes.rendHairs = MitaCore.ShortHairObject.transform.Find("MitaPerson Old/Hair").GetComponent<SkinnedMeshRenderer>();
                //MitaClothes.rendHead = MitaCore.ShortHairObject.transform.Find("MitaPerson Old/Head").GetComponent<SkinnedMeshRenderer>();
               
                //MitaClothes.ReCloth();

                MitaCore.ShortHairObject.active = false;
            }

            catch (Exception ex)
            {

                MelonLogger.Error($"Start horro founding error: {ex}");
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

                // Там реально дубль world!!!
                var room = world.Find("World/RealRoom");
                room.SetParent(MitaCore.worldHouse.Find("House"));
                room.SetPositionAndRotation(new Vector3(1.0871f,0, 5.0743f), Quaternion.EulerAngles(0,180,0));
                room.Find("Door").gameObject.SetActive(false);

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(world);


                var dayFrame = GameObject.Instantiate(world.Find("Quest/Quest 3 RealRoom/Canvas RealRoom/FrameDay"));
                dayFrame.gameObject.SetActive(false);
                dayFrame.gameObject.name = "Day Frame";
                dayFrame.SetParent(GameObject.Find("Interface").transform);
                PlayerEffectsModded.DayEffect = dayFrame.gameObject;

                //dayFrame.GetComponentInChildren<Localization_UIText>().deactiveTextTranslate = true;// .enabled = false;
                



                // Добавление музыкальных объектов
                AudioControl.addMusicObject(world.Find("Sounds/Audio Ambient RealRoom 1").gameObject, "Music Daily calm rutine");
                AudioControl.addMusicObject(world.Find("Sounds/Audio MitaAttack").gameObject, "Music some Tension");
                AudioControl.addMusicObject(world.Find("Sounds/Audio Ambient RealRoom 2").gameObject, "Music Daily calm rutine 2");

            }


            catch (Exception ex)
            {

                MelonLogger.Error($"Founding error MobilePlayer: {ex}");
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
               

                AudioControl.addMusicObject(worldGlasses.Find("Audio/Music").gameObject, "Music backround calm");
                AudioControl.addMusicObject(worldGlasses.Find("Audio/MusicBag").gameObject, "Music tension strange");
                AudioControl.addMusicObject(worldGlasses.Find("Audio/Music Echo").gameObject, "Embient hard");


                MitaCore.MilaObject.transform.Find("Mila Person").GetComponent<Animator>().PlayInFixedTime("Walk");
                MitaCore.MilaObject.active = false;

                MitaCore.MilaObject.transform.Find("Mila Person").GetComponent<CapsuleCollider>().enabled = true;
                MitaCore.MilaObject.transform.Find("Capsule").gameObject.active = false;
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


        private static IEnumerator WaitForSceneAndInstantiateBasementAndDeath(string sceneToLoad)
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
                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(world);

                world.Find("Quest").gameObject.active = false;
                world.Find("House").gameObject.active = false;
                world.Find("EventDay").gameObject.active = false;
                world.Find("Sounds").gameObject.active = false;
                world.Find("Acts").gameObject.active = false;

                var CoreRoom = world.Find("House/CoreRoom");
                CoreRoom.SetParent(MitaCore.worldHouse);
                CoreRoom.gameObject.active = true;
                CoreRoom.position = new Vector3(1.013f, 0f,10.242f);
                CoreRoom.gameObject.active = false;
                //AudioControl.addMusicObject(world.Find("Sounds/Ambient Evil 2").gameObject, "Embient horrific waiting");
                //AudioControl.addMusicObject(world.Find("Sounds/Ambient Evil 3").gameObject, "Embient horrific tension large");

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(world);

                world.Find("Quest/Quest 1 В подвале").GetComponentInChildren<ObjectAnimationPlayer>().AnimationStop();
                PlayerAnimationModded.UnstackPlayer();
                //world.


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
                    MelonLogger.Error("Failed to find Neck1 object in the hierarchy");
                }

                MitaCore.SleepyObject.SetActive(false);

                PlayerAnimationModded.copyAllObjectAnimationPlayerFromParent(worldDreamer);
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"{worldDreamer.name} founding error: {ex}");
            }
            
            SceneManager.UnloadScene(sceneToLoad);
        }
        

        private static IEnumerator AfterAllLoadded()
        {

            try
            {
                Interactions.init();
                
            }
            catch (Exception ex)
            {

                MelonLogger.Error(ex);
            }

            MelonLogger.Msg("After all loaded");
            characterType MitaToStart = Settings.Get<characterType>("MitaType");

            int currentDays = Settings.Get<int>("DaysInGame");
            currentDays = currentDays + 1;
            Settings.Set("DaysInGame", currentDays);
            MelonLogger.Msg($"DaysInGame: {Settings.Get<int>("DaysInGame")}"); // Проверяем

            PlayerAnimationModded.playObjectAnimationOnPlayer("AnimationPlayer NextScene");
            PlayerEffectsModded.turnBlackScreen(false);
            PlayerEffectsModded.ShowDayFromNumber(currentDays, "Сеанс");

            MelonLogger.Msg($"Mita from settings {MitaToStart}");
            
            MitaCore.Instance.addChangeMita(null, character: MitaToStart, true,true);
            
            yield return new WaitForSeconds(1f);

            EventsModded.sceneEnter(MitaToStart);

            MitaCore.AllLoaded = true;

            try { Interactions.GamePadInteractiveFix.active = true; }
            catch{

            }
            
            TestingGround();
        }

        private static void TestingGround()
        {

            MelonLogger.Msg("Try TestingGround");


            
            
            //ChairRoom4OIP.GetComponent<ObjectAnimationPlayer>().eventStartAnimaiton.AddListener()
            MelonLogger.Msg("End TestingGround");
            // Тест Миты Кастомной
            //TestMitaFroDemo();
        }
        private static void TestMitaFroDemo()
        {

                try
                {

                GameObject Mita = GameObject.Instantiate(AssetBundleLoader.LoadAssetByName<GameObject>(AssetBundleLoader.bundleTestMita, "Mita"));

                // Чиню поворот


                // Пока не принял решение, искать как починить текущий или брать из демо
                bool LookFromDemo = true;
                
                var Old = Mita.GetComponentInChildren<Character_Look>(); //

                Old.speedRotateBody = 1f;
                var New = Old.gameObject.AddComponent<Character_Look_Old>();

                try
                {
                    Character_Look_Old.CopyCharacterLookToOld(Old, New);
                }
                catch (Exception ex)
                {
                    MelonLogger.Error("CopyCharacterLookToOld", ex);
                }
                
                New.speedRotateFactor = 0.5f;
                New.legRight = New.pivotLegs.Find("LegRight").transform;
                New.legLeft = New.pivotLegs.Find("LegLeft").transform;
                New.activeBodyIK = true;


                if (LookFromDemo) Old.enabled = false;
                else New.enabled = false;





                // Чиню люпсинк
                var blandshapeOriginal = MitaCore.CrazyObject.transform.Find("MitaPerson Mita/Head").gameObject.GetComponent<Audio_BlendShapeVoice>();
                var blandshape = Mita.transform.Find("MitaPerson Mita/Head").gameObject.AddComponent<Audio_BlendShapeVoice>();

                blandshape.audioVoice = Mita.transform.Find("MitaPerson Mita/Armature/Hips/Spine/Chest/Neck2/Neck1/Head").GetComponent<AudioSource>();
                blandshape.mesh = Mita.transform.Find("MitaPerson Mita/Head").GetComponent<SkinnedMeshRenderer>();

                blandshape.animationMouth = blandshapeOriginal.animationMouth;
                blandshape.animationOffInSpeak = blandshapeOriginal.animationOffInSpeak;
                blandshape.shapesOffInSpeak = blandshapeOriginal.shapesOffInSpeak;
                blandshape.animationMouth = blandshapeOriginal.animationMouth;
                blandshape.intensity = 3;


                // Пробую одежку поменять

                try
                {
                    var mitaClothes = ComponentCopier.CopyComponent(MitaCore.CrazyObject.GetComponentInChildren<MitaClothes>(), Mita.transform.Find("MitaPerson Mita").gameObject, MitaCore.CrazyObject.transform.Find("MitaPerson Mita"), Mita.transform.Find("MitaPerson Mita"));

                }
                catch (Exception e) { MelonLogger.Error(e); }


                MitaCore.CrazyObject = Mita;
                Mita.name = "MitaTestFromDemo";
                MitaCore.Instance.addChangeMita(Mita, characterType.Crazy, turnOfOld:false);











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
                    door.localRotation = Quaternion.Euler(0, 0, 103);




                }
                catch (Exception)
                {
                    MelonLogger.Msg("Error while handling wardrobe transform.");
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
