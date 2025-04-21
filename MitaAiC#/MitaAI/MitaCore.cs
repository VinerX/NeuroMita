using Il2Cpp;
using MelonLoader;
using UnityEngine;
using System.Text.RegularExpressions;
using System.Reflection;
using System.Collections;
using System.Globalization;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine.AI;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using MitaAI.Mita;
using MitaAI.PlayerControls;
using UnityEngine.Events;
using UnityEngine.UI;
using UnityEngine.Networking.Match;
using System.Text.Json;
using UnityEngine.Playables;
using Il2CppInterop.Runtime.Injection;


[assembly: MelonInfo(typeof(MitaAI.MitaCore), "MitaAI", "1.0.0", "Dmitry", null)]
[assembly: MelonGame("AIHASTO", "MiSideFull")]

namespace MitaAI
{
    
    public class MitaCore : MelonMod
    {




        public static bool experimentalFunctionsOn = true;

        // Ссылка на экземпляр MitaCore, если он нужен
        public static MitaCore Instance;
        private LogicCharacter characterLogic;
            
        public MitaCore()
        {
            Instance = this;
            Settings.Initialize();
        }
        // Метод, который будет вызываться после выполнения PrivateMethod
        
        public GameObject MitaObject;
        public GameObject MitaPersonObject;
        public MitaPerson Mita;

        public static GameObject CrazyObject;
        public static GameObject CreepyObject; 
        public static GameObject CappyObject;
        public static GameObject KindObject;
        public static GameObject ShortHairObject;
        public static GameObject MilaObject; 
        public static GameObject SleepyObject; 


        Animator_FunctionsOverride MitaAnimatorFunctions;
        public Character_Look MitaLook;
        public static GameObject Console;

        static public GameObject getMitaPersonObjectByEnum(characterType character, bool getMitaPersonObject = false)
        {
            GameObject mitaObject;
            switch (character)
            {
                case characterType.Crazy:
                    mitaObject = CrazyObject;
                    break;
                case characterType.Kind:
                    mitaObject = KindObject;
                    break;
                case characterType.ShortHair:
                    mitaObject = ShortHairObject;
                    break;
                case characterType.Cappy:
                    mitaObject = CappyObject;
                    break;
                case characterType.Mila:
                    mitaObject = MilaObject;
                    break;
                case characterType.Sleepy:
                    mitaObject = SleepyObject;
                    break;
                case characterType.Creepy:
                    mitaObject = CreepyObject;
                    break;

                // Cartdiges
                case characterType.Cart_divan:
                    mitaObject = Console;
                    break;
                case characterType.Cart_portal:
                    mitaObject = Console;
                    break;


                default:
                    mitaObject = CrazyObject;
                    break;

            }
            if (getMitaPersonObject && !character.ToString().Contains("Cart") ) mitaObject = findMitaPersonObject(mitaObject);

            return mitaObject;

        }
        public static GameObject findMitaPersonObject(GameObject MitaObject)
        {
            GameObject MitaPersonObject = null;
            // Рекурсивно добавляем всех детей, если текущий объект не исключен
            int childCount = MitaObject.transform.childCount;
            for (int i = 0; i < childCount; i++)
            {
                Transform child = MitaObject.transform.GetChild(i);
                // Проверяем, содержит ли имя дочернего объекта подстроку "Mita Person"
                if (child != null && (child.name.Contains("Person") || child.name.Contains("Mita")))
                {
                    MelonLogger.Msg("found  MitaPersonObject");
                    MitaPersonObject = child.gameObject;
                    break; // Прерываем цикл, как только нашли первый подходящий объект
                }
            }
            return MitaPersonObject;
        }

        public void addChangeMita(GameObject NewMitaObject = null,characterType character = characterType.Crazy, bool ChangeAnimationControler = true, bool turnOfOld = true,bool changePosition = true,bool changeAnimation = true)
        {
            if (NewMitaObject == null)
            {
                NewMitaObject = getMitaPersonObjectByEnum(character);

            }

            MelonLogger.Msg($"Change Mita {currentCharacter} to {character} Begin");

            try
            {


                if (NewMitaObject == null)
                {
                    MelonLogger.Msg("New Mita Object is null!!!");
                    return;
                }
                
                if (turnOfOld)
                {
                    MitaObject.active = false;
                }
                
                currentCharacter = character;
                NewMitaObject.SetActive(true);
                MelonLogger.Msg("Change Mita activated her");
                MitaObject = NewMitaObject;

                MitaPersonObject =  findMitaPersonObject(MitaObject);



                if (MitaPersonObject == null)
                {
                    MelonLogger.Msg("Mita (Mita Person comp) is null");
                    MitaPersonObject = MitaObject.transform.Find("MitaPerson Future").gameObject;
                };

                if (changePosition) MitaPersonObject.transform.position = Vector3.zero;

                Character characterComponent = MitaPersonObject.GetComponent<Character>();
                if (characterComponent == null)
                {
                    characterComponent = MitaPersonObject.AddComponent<Character>();
                    characterComponent.Init(character,MitaPersonObject,Mita);
                }
                characterComponent.enabled = true;

                MitaLook = MitaPersonObject.transform.Find("IKLifeCharacter").GetComponent<Character_Look>();

                if (MitaLook.forwardPerson == null)
                {
                    MitaLook.forwardPerson = MitaPersonObject.transform;
                }
                if (character == characterType.Creepy)
                {
                    LogicCharacter.Instance.Initialize(MitaPersonObject, character);
                }
                if (character == characterType.Creepy)
                {
                    LogicCharacter.Instance.Initialize(MitaPersonObject, character);
                }

                MelonLogger.Msg("333");

                MitaAnimatorFunctions = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
                Mita = MitaObject.GetComponent<MitaPerson>();


                if (Mita == null) { 

                    MelonLogger.Msg("MitaPersonObject is null");
                };

                var mitaAnimationModded = MitaAnimationModded.getMitaAnimationModded(characterComponent);

                mitaAnimationModded.mitaAnimatorFunctions = MitaAnimatorFunctions;
                var animator = MitaPersonObject.GetComponent<Animator>();
                mitaAnimationModded.animator = animator;


                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");

                try
                {
                    
                    var audioSource = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head").GetComponent<AudioSource>();
                    AudioControl.dataValues_Sounds.audioSource = audioSource;
                    if (audioSource == null) MelonLogger.Msg("Audiosourse is null(((");
                    
                    // Получаем тип компонента
                    Type audioDialogueType = typeof(Il2Cpp.AudioDialogue);

                    // Получаем поле audioVoice через Reflection
                    FieldInfo audioVoiceField = audioDialogueType.GetField("audioVoice", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);

                    if (audioVoiceField != null)
                    {
                        // Получаем компонент AudioDialogue
                        var audioDialogue = AudioControl.MitaDualogueSpeak.GetComponent<Il2Cpp.AudioDialogue>();

                        // Устанавливаем значение поля через Reflection
                        audioVoiceField.SetValue(audioDialogue, audioSource);
                    }
                    else
                    {
                        Debug.LogError("Поле audioVoice не найдено!");
                    }

                }
                catch (Exception ex)
                {

                    MelonLogger.Msg($"5a0 {ex}");
                }
               

                if (ChangeAnimationControler)
                {
                    try
                    {

                        mitaAnimationModded.animator.runtimeAnimatorController = mitaAnimationModded.runtimeAnimatorController;
                        //AnimatorOverrideController AOC = MitaAnimationModded.animator.runtimeAnimatorController as AnimatorOverrideController;
                        //AOC.runtimeAnimatorController = MitaAnimationModded.runtimeAnimatorController;
                        MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");
                    }
                    catch (Exception ex)
                    {

                        MelonLogger.Msg($"5a {ex}");
                    }
                }

                try
                {
                    
                    
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"5a {ex}");
                }


                
                MelonLogger.Msg("666");
                //MitaAnimationModded.overrideController = MitaAnimationModded.runtimeAnimatorController;
                //location21_World.mitaTransform = MitaPersonObject.transform;
                //location21_World.
                try
                { 
                    location34_Communication = MitaObject.GetComponentInChildren<Location34_Communication>();
                    

                    if (location34_Communication == null ) location34_Communication = GameObject.Instantiate(Loc34_Template, MitaObject.transform).GetComponent< Location34_Communication>();

                    location34_Communication.gameObject.GetComponentInChildren<CapsuleCollider>().transform.localScale = new Vector3(0.01f, 0.01f, 0.01f);
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"Location34_Communication set error: {ex}");
                }


                try
                {
                    location34_Communication.play = true;
                    location34_Communication.mitaAnimator = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
                    location34_Communication.mita = Mita;

                    mitaAnimationModded.location34_Communication = location34_Communication;
                    mitaAnimationModded.location34_Communication.mita = Mita;
                    mitaAnimationModded.location34_Communication.mitaCanWalk = true;
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"Loc setting set error: {ex}");
                }


                Settings.MitaType.Value = character;
                Settings.Save();
               // MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");
                
               

               
                MitaAnimationModded.init(characterComponent, MitaAnimatorFunctions, location34_Communication, MitaLook, ChangeAnimationControler, changeAnimation);


                
     


                //if (!changeAnimation) MitaAnimationModded.resetToIdleAnimation();

                MitaClothesModded.init_hair();
                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");




                Rigidbody rigidbody = MitaPersonObject.GetComponent<Rigidbody>();
                if (rigidbody == null)
                {
                    rigidbody = MitaPersonObject.AddComponent<Rigidbody>();
                    rigidbody.freezeRotation = true;
                    rigidbody.useGravity = false;
                    rigidbody.centerOfMass = new Vector3(0, 0.65f, 0);
                    rigidbody.mass = 2f;
                    rigidbody.maxAngularVelocity = 0.3f; //0.3 как и было
                    rigidbody.maxDepenetrationVelocity = 7f;//0.3f; //было до этого = 0.9f когда пробовал влад;
                    rigidbody.drag = 15;
                    rigidbody.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic; //ContinuousDynamic вместо Continuous для обработки динамических обьектов
                    rigidbody.interpolation = RigidbodyInterpolation.Interpolate;
                }
;
                MitaPersonObject.GetComponent<CapsuleCollider>().radius = 0.13f;
            }
            catch (Exception ex)
            {

                MelonLogger.Error("Mita change: ", ex);
            }

            MelonLogger.Msg("Change Mita Final");
        }


        public static Transform getMitaHand(GameObject MitaObject,bool left = false)
        {
            if (left) MitaObject.transform.Find("Armature/Hips/Spine/Chest/Left shoulder/Left arm/Left elbow/Left wrist/Left item");
            return MitaObject.transform.Find("Armature/Hips/Spine/Chest/Right shoulder/Right arm/Right elbow/Right wrist/Right item");
        }

        

        public characterType currentCharacter = characterType.Crazy;

        

        

        

        public GameObject knife;

        public PlayerPerson playerPerson;
        public GameObject playerPersonObject;
        public GameObject playerObject;

        public GameObject playerControllerObject;
        public GameController playerController;


        public static Text HintText;

        public GameObject cartridgeReader;

        public float distance = 0f;
        
        public Location34_Communication location34_Communication;
        public Location21_World location21_World;

        public static Transform worldTogether;
        public static Transform worldHouse;
        public static Transform worldBasement;
        public static Transform world;
        public static Transform worldBackrooms2;





        static public Menu MainMenu;

        public static GameObject playerCamera;
        public GameObject AnimationKiller;
        public static BlackScreen blackScreen;



        private const float Interval = 0.35f;
        private float timer = 0f;
        
        // Добавляем блокировку для предотвращения одновременных вызовов HandleDialogue
        private bool isHandleDialogueRunning = false;

        public Vector3 lastPosition;

        public string playerMessage = "";
        

        public string hierarchy = "-";

        static List<AnimationClip> MitaAnims = new List<AnimationClip>();
        
        static public Il2CppAssetBundle bundle;
        //static public Il2CppAssetBundle bundle2;

        static string requiredSceneName = "Scene 4 - StartSecret";
        public string requiredSave = "SaveGame startsecret";
        static string CurrentSceneName;

        public static bool isRequiredScene()
        {
            return CurrentSceneName == requiredSceneName;
        }


        static public bool AllLoaded = false;
        public static bool isAllLoadeed()
        {
            return AllLoaded;
        }


        HarmonyLib.Harmony harmony;
        public override void OnInitializeMelon()
        {
            ClassInjector.RegisterTypeInIl2Cpp<Character>();

            base.OnInitializeMelon();

            characterLogic = LogicCharacter.Instance;
            harmony = new HarmonyLib.Harmony("NeuroMita");
            harmony.PatchAll(System.Reflection.Assembly.GetExecutingAssembly());
            MelonLogger.Msg("OnInitializeMelon patch");
            MitaClothesModded.init(harmony);
            NetworkController.Initialize();
            LocalizationModded.init();
            CustomUI customUI = new CustomUI();
            customUI.StartCustomUI();
        }

        public override void OnLateInitializeMelon()
        {
            base.OnLateInitializeMelon();
            try
            {   
                bundle = AssetBundleLoader.initBundle();

                if (bundle == null)
                {
                    MelonLogger.Msg("AssetBundleLoader не прогрузился(" );
                }
            }
            catch (Exception e)
            {
                MelonLogger.Msg(e);
            }


        }




       
        public void playerClickSafe()
        {
            CharacterMessages.sendSystemMessage("Игрок кликает на кнопку сейфа");
        }



        public override void OnSceneWasUnloaded(int buildIndex, string sceneName)
        {
            if (sceneName == requiredSceneName)
            {
                CharacterMessages.sendSystemInfo("Игрок покинул уровень");
                MitaCore.AllLoaded = false;
            }
            base.OnSceneWasUnloaded(buildIndex, sceneName);
        }

        public override void OnSceneWasLoaded(int buildIndex, string sceneName)

        {
            

            MelonLogger.Msg("Scene loaded " + sceneName);
            if (!TotalInitialization.additiveLoadedScenes.Contains(sceneName))
            {
                MelonLogger.Msg("Scene loaded not addictive" + sceneName);
                CurrentSceneName = sceneName;
            }
            else
            {
                MelonLogger.Msg("Scene loaded addictive " + sceneName);
                return;
            }

            if (CurrentSceneName == "SceneMenu")
            {


                UINeuroMita.init();
                TotalInitialization.GetObjectsFromMenu();


            }

            else if (requiredSceneName == CurrentSceneName)
            {

                InitializeGameObjects();
            }
        }





        public Rooms roomPlayer = Rooms.Unknown;
        public Rooms roomMita = Rooms.Unknown;

        public void CheckRoom(PlayerMove playerMove)
        {
            if (playerMove == null) return;
            roomPlayer = (Rooms)GetRoomID(playerMove.transform);
        }

        public Rooms GetRoomID(Transform playerTransform)
        {
            if (playerTransform == null)
                return Rooms.Unknown;

            Vector3 position = playerTransform.position;
            float posX = position.x;
            float posZ = position.z;
            float posY = position.y;

            if (Utils.getDistanceBetweenObjects(worldHouse.gameObject,playerPersonObject)>50f) return Rooms.Unknown;
            if (posY <= -0.2f)
                return Rooms.Basement;

            if (posX > 5.3f)
                return posZ >= 0 ? Rooms.Kitchen : Rooms.Bedroom;

            if (posX > -4f && posX < 5f)
                return Rooms.MainHall;

            if (posX > -11.0f && posX < -4.3f)
                return Rooms.Toilet;

            return Rooms.Unknown;
        }

        GameObject Loc34_Template;


        private void InitializeGameObjects()
        {

            GameObject Trigger = GameObject.Find("World/Quests/Quest 1/Trigger Entry Kitchen");
            Trigger.SetActive(false);


            GameObject Location34_CommunicationObject = GameObject.Find("World/Quests/Quest 1/Addon");
            location34_Communication = GameObject.Find("World/Quests/Quest 1/Addon").GetComponent<Location34_Communication>();

            location34_Communication.mitaCanWalk = true;
            location34_Communication.indexSwitchAnimation = 1;
            location34_Communication.play = true;

            CollectChildObjects(Location34_CommunicationObject);

            Loc34_Template = location34_Communication.gameObject;

            Mita = GameObject.Find("Mita")?.GetComponent<MitaPerson>();




            MitaObject = GameObject.Find("Mita").gameObject;

            MitaPersonObject = MitaObject.transform.Find("MitaPerson Mita").gameObject;
            CrazyObject = MitaObject;

            location34_Communication.transform.SetParent(CrazyObject.transform);


            var comp = MitaPersonObject.AddComponent<Character>();
            comp.Init(characterType.Crazy,MitaPersonObject,Mita);

            currentCharacter = characterType.Crazy;

            MitaLook = MitaObject.transform.Find("MitaPerson Mita/IKLifeCharacter").gameObject.GetComponent<Character_Look>();
            MitaAnimatorFunctions = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
            MitaAnimationModded.init(comp,MitaAnimatorFunctions, location34_Communication, MitaLook);
            Mita.AiShraplyStop();

            //GameObject eyeObject = Utils.TryfindChild(MitaPersonObject.transform, "Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Right Eye");
            //eyeModifier = new EyeGlowModifier(eyeObject);
            //eyeObject = Utils.TryfindChild(MitaPersonObject.transform, "Armature/Hips/Spine/Chest/Neck2/Neck1/Head/Left Eye");
            //eyeModifier = new EyeGlowModifier(eyeObject);

            //Mita.gameObject.GetComponent<UnityEngine.AI.NavMeshAgent>().enabled = true;

            playerPerson = GameObject.Find("Person")?.GetComponent<PlayerPerson>();
            playerPersonObject = playerPerson.gameObject;
            playerObject = playerPerson.transform.parent.gameObject;
            playerControllerObject = playerObject.transform.parent.gameObject;
            playerController = playerControllerObject.GetComponent<GameController>();

            playerObject.GetComponent<PlayerMove>().speedPlayer = 1f;
            playerObject.GetComponent<PlayerMove>().canRun = true;
            PlayerHands.Init(playerObject.transform);
            LookAtPlayer.Init(playerPersonObject.transform);

            if (playerPersonObject.GetComponent<AudioSource>() == null) AudioControl.playerAudioSource = playerPersonObject.AddComponent<AudioSource>();

            // Отключить если нужно
            GameMaster GM = playerPersonObject.AddComponent<GameMaster>();
            GM.init_GameMaster();
            GM.enabled = false;





            Text HintText = GameObject.Find("GameController/Interface/HintScreen/Text").GetComponent<Text>();

            blackScreen = GameObject.Find("Game/Interface/BlackScreen").GetComponent<BlackScreen>();
            try
            {
                playerCamera = playerPerson.transform.parent.gameObject.transform.FindChild("HeadPlayer/MainCamera").gameObject;
                MelonLogger.Msg("Camera found" + playerCamera.name);
            }
            catch (Exception)
            {

                MelonLogger.Msg("Camera not MelonLogger.Msg(\"Camera found\" + playerCamera.name);found" + playerCamera.name);
            }



            if (Mita == null || playerPerson == null) return;


            CommandProcessor.Initialize(this, playerObject.transform, MitaObject.transform, location34_Communication);


            worldHouse = GameObject.Find("World")?.transform;
            World worldSettings = worldHouse.gameObject.GetComponent<World>();
            MitaObject.transform.SetParent(worldHouse);
            location21_World = worldHouse.gameObject.AddComponent<Location21_World>();

            PlayerAnimationModded.Init(playerObject, worldHouse, playerObject.GetComponent<PlayerMove>());
            PlayerEffectsModded.Init(playerPersonObject);
            LightingAndDaytime.Init(location21_World, worldHouse);

            ShaderReplacer.init();


            MelonCoroutines.Start(StartDayTime());
            //MelonCoroutines.Start(UpdateLighitng());




            try
            {
                AudioControl.Init(worldHouse);
            }
            catch (Exception ex) { MelonLogger.Error(ex); }

            worldSettings.limitFloor = -200f;
            if (worldHouse == null)
            {
                MelonLogger.Msg("World object not found.");

            }

            DialogueControl.SetupDialogueTemplates(worldHouse.transform);

            MelonLogger.Msg($"Attempt initStartSecret2");

            TotalInitialization.initStartSecret2();

            MelonLogger.Msg($"Attempt Interactions before");





            //MelonLogger.Msg($"Attempt after");
            MelonLogger.Msg($"Attempt Interactions end");
            try
            {
                MelonCoroutines.Start(TotalInitialization.AddOtherScenes());
            }
            catch (Exception e)
            {
                MelonLogger.Error(e);
            }



            //Interactions.Test(GameObject.Find("Table"));
            MelonCoroutines.Start(ConnectionTimer());





            //TestBigMita();
        }

        

        public static void DeleteChildren(GameObject parent)
        {
            if (parent == null)
            {
                MelonLoader.MelonLogger.Error("Parent object is null.");
                return;
            }

            // Создаем временный массив, чтобы избежать изменения итерируемой коллекции
            Transform[] children = new Transform[parent.transform.childCount];
            for (int i = 0; i < parent.transform.childCount; i++)
            {
                children[i] = parent.transform.GetChild(i);
            }

            // Удаляем каждого ребенка
            foreach (Transform child in children)
            {
                GameObject.Destroy(child.gameObject);
            }

            MelonLoader.MelonLogger.Msg($"All children of {parent.name} have been deleted.");
        }



        public IEnumerator ConnectionTimer()
        {
            while (true)
            {
                // Проверяем условия
                if ( !isRequiredScene() )
                {
                    yield break;

                }

                if (!AllLoaded)
                {
                    yield return null; // Пропускаем итерацию, если условия не выполнены
                    continue;// Пропускаем итерацию, если условия не выполнены
                }

                // Обновляем таймеры
                timer += Time.unscaledDeltaTime;
                DataChange.MitaBoringtimer += Time.unscaledDeltaTime;

                // Проверяем, достиг ли timer значения Interval и не запущен ли уже HandleDialogue
                if (timer >= Interval && !isHandleDialogueRunning)
                {
                    timer = 0f; // Сбрасываем таймер
                    isHandleDialogueRunning = true; // Устанавливаем флаг, что HandleDialogue запущен
                    
                    yield return DataChange.HandleDialogue(); // Запускаем HandleDialogue и ждем его завершения
                    
                    isHandleDialogueRunning = false; // Сбрасываем флаг после завершения
                }

                yield return null; // Ждем следующего кадра
            }
        }

        private IEnumerator UpdateLighting()
        {
            yield return new WaitForSeconds(1f);
            while (true)
            {
                try
                {
                    LightingAndDaytime.CheckDay();

                }
                catch (Exception e)
                {

                    MelonLogger.Msg("Error LightingAndDaytime CheckDay" + e);
                }
                yield return new WaitForSeconds(2.3f); // Ждем 7 секунд перед следующим циклом
            }
        }

        private IEnumerator StartDayTime()
        {

            yield return new WaitForSeconds(1f);
            LightingAndDaytime.setTimeDay(0.5f);
        }


        public float getDistanceToPlayer()
        {
            if (MitaPersonObject == null || playerObject == null) { return 0f; }
            return Utils.getDistanceBetweenObjects(MitaPersonObject, playerObject);


        }
                  
        // Глобальный список для хранения дочерних объектов
        List<GameObject> globalChildObjects = new List<GameObject>();

        // Функция для получения дочерних объектов и добавления их в глобальный список
        void CollectChildObjects(GameObject parentObject)
        {
            // Проверяем, что объект не null
            if (parentObject == null)
            {
                MelonLogger.Error("Parent object is null!");
                return;
            }

            // Получаем Transform родительского объекта
            Transform parentTransform = parentObject.transform;

            // Перебираем всех детей
            for (int i = 0; i < parentTransform.childCount; i++)
            {
                Transform childTransform = parentTransform.GetChild(i);

                if (childTransform != null)
                {
                    // Добавляем дочерний объект в глобальный список
                    globalChildObjects.Add(childTransform.gameObject);

                    if (i == 0)
                    {
                        GameObject newPoint = GameObject.Instantiate(childTransform.gameObject,new Vector3(12.8382f,-2.9941f,-16.8005f),Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Basement 1";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");

                        newPoint = GameObject.Instantiate(childTransform.gameObject, new Vector3(17.0068f, -2.9941f, -13.2256f), Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Basement 2";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");


                        newPoint = GameObject.Instantiate(childTransform.gameObject, new Vector3(10.9679f, -2.9941f, -19.5763f), Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Basement Camera";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");

                        newPoint = GameObject.Instantiate(childTransform.gameObject, new Vector3(19.6421f, -2.9941f, -14.9584f), Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Basement Safe";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");

                        newPoint = GameObject.Instantiate(childTransform.gameObject, new Vector3(11.2978f, 0, -7.3997f), Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Enter_Basement";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");
                        
                        newPoint = GameObject.Instantiate(childTransform.gameObject, new Vector3(11.1936f, 0, -8.9503f), Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Leave_Basement";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");

                        newPoint = GameObject.Instantiate(childTransform.gameObject, new Vector3(12.1435f, -2.9941f, -11.9181f), Quaternion.identity, childTransform.parent);
                        newPoint.name = "Point Basement Near Cartridge";
                        globalChildObjects.Add(newPoint);
                        remakeArrayl34(location34_Communication, newPoint, "b");
                        

                    }

                }
            }
            
            // Выводим общее количество детей
            MelonLogger.Msg($"Total children collected: {globalChildObjects.Count}");
        }

        
        public void remakeArrayl34(Location34_Communication Location34_Communication, GameObject newPoint, string room)
        {

            // Создаем новый массив с размером на 1 больше
            Il2CppReferenceArray<Location34_PositionForMita> newArray = new Il2CppReferenceArray<Location34_PositionForMita>(Location34_Communication.positionsForMita.Length + 1);

            // Копируем старые данные
            for (int i = 0; i < Location34_Communication.positionsForMita.Length; i++)
            {
                newArray[i] = Location34_Communication.positionsForMita[i];
            }

            // Добавляем новый элемент
            Location34_PositionForMita l = new Location34_PositionForMita();

            l.target = newPoint.transform;
            l.room = room;

            newArray[newArray.Length - 1] = l;

            Location34_Communication.positionsForMita = newArray;

            
        }

        public string GetLocations()
        {
            MelonLogger.Msg("TryGetLocations");

            string message = "Objects names in <> for walk or teleport to";

            for (int i = 0; i < globalChildObjects.Count; i++)
            {
                if (globalChildObjects[i] == null) continue;

                if( globalChildObjects[i].name.Contains("Point") || globalChildObjects[i].name.Contains("Position")  )
                {

                    message += $"<{globalChildObjects[i].name}>";

                }

            }

            return message;

        }

        public Transform GetRandomLoc()
        {
            MelonLogger.Msg("Before try Tring GetRandomLoc");
            try
            {
                MelonLogger.Msg("Tring GetRandomLoc");
                // Проверяем, что список не пустой
                if (globalChildObjects == null || globalChildObjects.Count == 0)
                {
                    MelonLogger.Error("globalChildObjects is null or empty!");
                    return null; // Возвращаем null, если список пуст
                }

                // Генерируем случайный индекс
                int randomIndex = UnityEngine.Random.Range(0, globalChildObjects.Count);

                // Получаем случайный объект по индексу
                GameObject randomObject = globalChildObjects[randomIndex];

                // Проверяем, что объект действительно существует и имеет компонент Transform
                if (randomObject == null)
                {
                    MelonLogger.Error("Random object is null!");
                    return null; // Возвращаем null, если объект не найден
                }

                // Логируем имя объекта
                MelonLogger.Msg($"Random object selected: {randomObject.name}");

                // Возвращаем компонент Transform
                return randomObject.transform;
            }
            catch (Exception)
            {
                MelonLogger.Msg("Error with random loc");
                return null;
            }

        }

        public IEnumerator MitaSharplyStopTimed(float time)
        {
            yield return new WaitForSeconds(time);
            Mita.AiShraplyStop();
        }

        public override void OnUpdate()
        {
            if (!isAllLoadeed())
                return;

            TryExecute(Interactions.Update);
            TryExecute(InputControl.processInpute);
            TryExecute(PlayerMovement.onUpdate);
            TryExecute(CharacterControl.Update);
            TryExecute(() => characterLogic?.Update());
            TryExecute(UINeuroMita.CheckPauseMenu);
        }

        private void TryExecute(Action action)
        {
            try
            {
                action?.Invoke();
            }
            catch (Exception e)
            {
                MelonLogger.Msg($"Error in {action?.Method.Name}: {e}");
            }
        }



        public void setCharacterState(MitaAI.characterType targetChar, MitaAI.characterType newState) // не доделано, будет отрубать персонажа
                {
            try
            {
                if (targetChar == MitaAI.characterType.None) return;
                
                GameObject charObj = getMitaPersonObjectByEnum(targetChar);
                if (charObj == null) return;
                
                var navMesh = charObj.GetComponent<NavMeshAgent>();
                if (navMesh != null) navMesh.enabled = false;
                
                var animator = charObj.GetComponent<Animator>();
                if (animator != null) animator.enabled = false;
                
                charObj.SetActive(false);
                
                if (newState == MitaAI.characterType.None)
                {
                    MelonLogger.Msg($"Fully deactivated character: {targetChar}");
                    currentCharacter = MitaAI.characterType.None;
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Error in setCharacterState: {ex.Message}");
            }
        }

        public void removeMita(GameObject mitaObject, MitaAI.characterType character)
        {
            try
            {
                if (mitaObject != null)
                {
                    mitaObject.SetActive(false);
                    mitaObject.GetComponentInChildren<Character>().enabled = false;
                    //var navMesh = mitaObject.GetComponent<NavMeshAgent>();
                    //if (navMesh != null) navMesh.enabled = false;

                    //var animator = mitaObject.GetComponent<Animator>();
                    //if (animator != null) animator.enabled = false;

                    MelonLogger.Msg($"Character {character} removed");
                }
                if (character == currentCharacter) currentCharacter = MitaAI.characterType.None;

            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Error removing character: {ex.Message}");
            }
        }


    }
}
