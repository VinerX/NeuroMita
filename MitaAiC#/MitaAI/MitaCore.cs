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


[assembly: MelonInfo(typeof(MitaAI.MitaCore), "MitaAI", "1.0.0", "Dmitry", null)]
[assembly: MelonGame("AIHASTO", "MiSideFull")]

namespace MitaAI
{
    
    public class MitaCore : MelonMod
    {
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
        public static GameObject CreepyObject; // Объект для уродливой Миты
        public static GameObject CappyObject;
        public static GameObject KindObject;
        public static GameObject ShortHairObject;
        public static GameObject MilaObject; // Объект для нового персонажа
        public static GameObject SleepyObject; // Объект для нового персонажа


        Animator_FunctionsOverride MitaAnimatorFunctions;
        public Character_Look MitaLook;
        public static GameObject Console;
        static public GameObject getMitaByEnum(MitaAI.character character, bool getMitaPersonObject = false)
        {
            GameObject mitaObject;
            switch (character)
            {
                case MitaAI.character.Crazy:
                    mitaObject = CrazyObject;
                    break;
                case MitaAI.character.Kind:
                    mitaObject = KindObject;
                    break;
                case MitaAI.character.ShortHair:
                    mitaObject = ShortHairObject;
                    break;
                case MitaAI.character.Cappy:
                    mitaObject = CappyObject;
                    break;
                case MitaAI.character.Mila:
                    mitaObject = MilaObject;
                    break;
                case MitaAI.character.Sleepy:
                    mitaObject = SleepyObject;
                    break;
                case MitaAI.character.Creepy:
                    mitaObject = CreepyObject;
                    break;

                // Cartdiges
                case MitaAI.character.Cart_divan:
                    mitaObject = Console;
                    break;
                case MitaAI.character.Cart_portal:
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

        public void addChangeMita(GameObject NewMitaObject = null,MitaAI.character character = MitaAI.character.Crazy, bool ChangeAnimationControler = true, bool turnOfOld = true,bool changePosition = true,bool changeAnimation = true)
        {
            if (NewMitaObject == null)
            {
                NewMitaObject = getMitaByEnum(character);

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

                if (MitaPersonObject.GetComponent<Character>() == null)
                {
                    var comp = MitaPersonObject.AddComponent<Character>();
                    comp.init(character);
                }

                // Интеграция CharacterLogic
                Character characterComponent = MitaPersonObject.GetComponent<Character>();
                if (characterComponent == null)
                {
                    characterComponent.init(character); // Предполагается, что init инициализирует персонажа
                }

                MitaLook = MitaPersonObject.transform.Find("IKLifeCharacter").GetComponent<Character_Look>();

                if (MitaLook.forwardPerson == null)
                {
                    MitaLook.forwardPerson = MitaPersonObject.transform;
                }
                if (character == MitaAI.character.Creepy)
                {
                    LogicCharacter.Instance.Initialize(MitaPersonObject, character);
                }
                if (character == MitaAI.character.Creepy)
                {
                    LogicCharacter.Instance.Initialize(MitaPersonObject, character);
                }

                MelonLogger.Msg("333");

                MitaAnimatorFunctions = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
                Mita = MitaObject.GetComponent<MitaPerson>();


                if (Mita == null) { 

                    MelonLogger.Msg("MitaPersonObject is null");
                };
                MitaAnimationModded.mitaAnimatorFunctions = MitaAnimatorFunctions;
                var animator = MitaPersonObject.GetComponent<Animator>();
                MitaAnimationModded.animator = animator;


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
                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");

                if (ChangeAnimationControler)
                {
                    try
                    {

                        MitaAnimationModded.animator.runtimeAnimatorController = MitaAnimationModded.runtimeAnimatorController;
                        //AnimatorOverrideController AOC = MitaAnimationModded.animator.runtimeAnimatorController as AnimatorOverrideController;
                        //AOC.runtimeAnimatorController = MitaAnimationModded.runtimeAnimatorController;
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


                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");
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

                    MitaAnimationModded.location34_Communication = location34_Communication;
                    MitaAnimationModded.location34_Communication.mita = Mita;
                    MitaAnimationModded.location34_Communication.mitaCanWalk = true;
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"Loc setting set error: {ex}");
                }


                Settings.MitaType.Value = character;
                Settings.Save();
                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");
                
                if (!changeAnimation) MelonCoroutines.Start(walkingFix());

               
                MitaAnimationModded.init(MitaAnimatorFunctions, location34_Communication, ChangeAnimationControler, changeAnimation);


                
     


                if (!changeAnimation) MitaAnimationModded.resetToIdleAnimation();

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

            }
            catch (Exception ex)
            {

                MelonLogger.Error("Mita change: ", ex);
            }

            MelonLogger.Msg("Change Mita Final");
        }
        IEnumerator walkingFix()
        {
            yield return new WaitForSeconds(7f);
            Mita.AiShraplyStop();
            //Mita.AiWalkToTarget(worldHouse);
        }

        public static Transform getMitaHand(GameObject MitaObject,bool left = false)
        {
            if (left) MitaObject.transform.Find("Armature/Hips/Spine/Chest/Left shoulder/Left arm/Left elbow/Left wrist/Left item");
            return MitaObject.transform.Find("Armature/Hips/Spine/Chest/Right shoulder/Right arm/Right elbow/Right wrist/Right item");
        }

        

        public MitaAI.character currentCharacter = MitaAI.character.Crazy;

        public static MovementStyles movementStyle = MovementStyles.walkNear;

        public MitaState mitaState = MitaState.normal;

        

        public GameObject knife;

        public PlayerPerson playerPerson;
        public GameObject playerPersonObject;
        public GameObject playerObject;

        public GameObject playerControllerObject;
        public GameController playerController;

        public GameController gameController;
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
        //static public Queue<string> playerMessages = new Queue<string>();

        public List<MitaAI.character> playerMessageCharacters = new List<MitaAI.character>();


        

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
            base.OnInitializeMelon();
            characterLogic = LogicCharacter.Instance;
            harmony = new HarmonyLib.Harmony("NeuroMita");
            harmony.PatchAll(System.Reflection.Assembly.GetExecutingAssembly());
            MelonLogger.Msg("OnInitializeMelon patch");
            MitaClothesModded.init(harmony);
            NetworkController.Initialize();
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
            comp.init(MitaAI.character.Crazy);

            currentCharacter = MitaAI.character.Crazy;

            MitaLook = MitaObject.transform.Find("MitaPerson Mita/IKLifeCharacter").gameObject.GetComponent<Character_Look>();
            MitaAnimatorFunctions = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
            MitaAnimationModded.init(MitaAnimatorFunctions, location34_Communication);
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

            if (playerPersonObject.GetComponent<AudioSource>() == null) AudioControl.playerAudioSource = playerPersonObject.AddComponent<AudioSource>();

            // Отключить если нужно
            GameMaster GM = playerPersonObject.AddComponent<GameMaster>();
            GM.init_GameMaster();
            GM.enabled = false;



            

            Text HintText =  GameObject.Find("GameController/Interface/HintScreen/Text").GetComponent<Text>();

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



            MelonLogger.Msg(Mita != null ? "Mita found!" : "Mita not found.");
            MelonLogger.Msg(playerPerson != null ? "Player found!" : "Player not found.");

            if (Mita == null || playerPerson == null) return;


            CommandProcessor.Initialize(this, playerObject.transform,MitaObject.transform,location34_Communication);

                
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

            MelonLogger.Msg($"Attempt initStartSecret2");
            
            TotalInitialization.initStartSecret2();

            MelonLogger.Msg($"Attempt Interactions before");
            try
            {
                Interactions.init();
            }
            catch (Exception)
            {

                throw;
            }


            

            //MelonLogger.Msg($"Attempt after");
            MelonLogger.Msg($"Attempt Interactions end");
            try
            {
                MelonCoroutines.Start( TotalInitialization.AddOtherScenes() );
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
                timer += Time.deltaTime;
                DataChange.MitaBoringtimer += Time.deltaTime;

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



                    }

                }
            }
            
            // Выводим общее количество детей
            MelonLogger.Msg($"Total children collected: {globalChildObjects.Count}");
        }

        
        public void remakeArrayl34(Location34_Communication Location34_Communication, GameObject newPoint, string room)
        {
            MelonLogger.Msg($"Start Il2CppReferenceArray {Location34_Communication} 33 {newPoint} ");
            // Создаем новый массив с размером на 1 больше
            Il2CppReferenceArray<Location34_PositionForMita> newArray = new Il2CppReferenceArray<Location34_PositionForMita>(Location34_Communication.positionsForMita.Length + 1);
            MelonLogger.Msg($" Il2CppReferenceArray222");
            // Копируем старые данные
            for (int i = 0; i < Location34_Communication.positionsForMita.Length; i++)
            {
                newArray[i] = Location34_Communication.positionsForMita[i];
            }

            MelonLogger.Msg($" Il2CppReferenceArray333");
            // Добавляем новый элемент
            Location34_PositionForMita l = new Location34_PositionForMita();
            MelonLogger.Msg($" Il2CppReferenceArray444");
            l.target = newPoint.transform;
            l.room = room;
            MelonLogger.Msg($" Il2CppReferenceArray5");
            newArray[newArray.Length - 1] = l;

            Location34_Communication.positionsForMita = newArray;
            MelonLogger.Msg($"End");
            
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
        




        // Добавляет диалог в историю


        

        public IEnumerator MitaSharplyStopTimed(float time)
        {
            yield return new WaitForSeconds(time);
            Mita.AiShraplyStop();
        }



        // Корутин для активации и деактивации объекта
        public IEnumerator ActivateAndDisableKiller(float delay)
        {
            MelonLogger.Msg("Player killed");

            if (AnimationKiller.transform.Find("PositionsKill").childCount > 0)
            {
                AnimationKiller.transform.Find("PositionsKill").GetChild(0).SetPositionAndRotation(playerPerson.transform.position, playerPerson.transform.rotation);
            }
            AnimationKiller.SetActive(true); // Включаем объект


            // Сохраняем исходную позицию и ориентацию Миты
            Vector3 originalPosition = MitaPersonObject.transform.position;
            Quaternion originalRotation = MitaPersonObject.transform.rotation;
            MitaPersonObject.transform.SetPositionAndRotation(new Vector3(500, 500, 500), Quaternion.identity);
            yield return new WaitForSeconds(0.1f);
            try
            {
                AnimationKiller.GetComponent<Location6_MitaKiller>().Kill(); // Вызываем метод Kill()
                MitaGames.endHunt();
            }
            catch (Exception e)
            {

                MelonLogger.Msg(e);
            }
            
            yield return new WaitForSecondsRealtime(delay);

            CharacterMessages.sendSystemMessage("You successfully killed the player using knife, and he respawned somewhere.");

            AnimationKiller.SetActive(false); // Включаем объект
            // Возвращаем Миту в исходное положение
            Utils.TryTurnChild(worldHouse, "House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom", true);

            try
            {
                MitaPersonObject.transform.SetPositionAndRotation(originalPosition, originalRotation);
                Mita.AiShraplyStop();
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






        public (EmotionType, string) SetEmotionBasedOnResponse(string response)
        {
            MelonLogger.Msg($"Inside SetEmotionBasedOnResponse: " + response);
            try
            {
                var (emotions, cleanedResponse) = ExtractEmotions(response);
                EmotionType emotion = EmotionType.none;
                if (emotions.Count > 0)
                {
                    Enum.TryParse<EmotionType>(emotions[0], true, out var result);

                    Mita.FaceEmotionType(result);
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
        public string SetFaceStyle(string response)
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
                // Проверка на наличие объекта Mita перед применением эмоции
                if (Mita == null || Mita.gameObject == null || currentCharacter!=MitaAI.character.Crazy)
                {
                    MelonLogger.Error("Mita object is null or Mita.gameObject is not active.");
                    return cleanedResponse; // Возвращаем faceStyle и очищенный текст
                }

                // Устанавливаем лицо, если оно найдено
                switch (faceStyle)
                {
                    case "Смущаться":
                        //Mita.FaceColorUpdate();
                        Mita.FaceLayer(1);
                        break;
                    case "Маска грусти":
                        //Mita.FaceColorUpdate();
                        Mita.FaceLayer(2);
                        break;
                    default:
                        //Mita.FaceColorUpdate();
                        Mita.FaceLayer(0);
                        break;
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Problem with FaceStyle: {ex.Message}");
            }

            // Возвращаем кортеж: лицо и очищенный текст
            return cleanedResponse;
        }

        
       
      
        public override void OnUpdate()
        {
            try
            {
                if (isAllLoadeed()){
                    Interactions.Update();
                    InputControl.processInpute();
                    PlayerMovement.onUpdate();
                    CharacterControl.Update();
                    characterLogic?.Update(); // добавляем для метода update в characterlogic
                    UINeuroMita.CheckPauseMenu(); // Добавляем проверку состояния меню паузы
                }



            }
            catch (Exception e)
            {

                MelonLogger.Msg(e);
            }
            
        }

        public static Color GetCharacterTextColor(MitaAI.character character)
        {
            switch (character)
            {
                case MitaAI.character.Crazy:
                    return new Color(1f, 0.4f, 0.8f); // розовый
                case MitaAI.character.Cappy:
                    return new Color(1f, 1f, 0.1f); // мягкий оранжевый 
                case MitaAI.character.Kind:
                    return new Color(0.80f, 0.9f, 1f); // Бирюзовый
                    
                case MitaAI.character.ShortHair:
                    return new Color(1f, 0.9f, 0.4f); // мягкий желтый
                case MitaAI.character.Mila:
                    return new Color(0.4f, 0.6f, 1f); // голубой
                case MitaAI.character.Sleepy:
                    return new Color(1f, 1f, 1f); // мягкий розовый
                case MitaAI.character.Creepy:
                    return new Color(1f, 0f, 0f); // красный
                case MitaAI.character.GameMaster:
                    return Color.black;
                default:
                    return Color.white;
            }
        }

        public void GlassesObj()
        {
            MitaPersonObject.transform.Find("World/Acts/Mita/MitaPerson/Head/Mita'sGlasses").gameObject.SetActive(true);
        }

        public void GlassesObj(bool state)
        {
            try 
            {
                var glasses = MitaPersonObject.transform.Find("World/Acts/Mita/MitaPerson/Head/Mita'sGlasses").gameObject;
                glasses.SetActive(state);
                CharacterMessages.sendSystemInfo(state ? "Очки надеты" : "Очки сняты");
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Ошибка при работе с очками: {ex.Message}");
            }
        }


                public void setCharacterState(MitaAI.character targetChar, MitaAI.character newState) // не доделано, будет отрубать персонажа
                {
            try
            {
                if (targetChar == MitaAI.character.None) return;
                
                GameObject charObj = getMitaByEnum(targetChar);
                if (charObj == null) return;
                
                var navMesh = charObj.GetComponent<NavMeshAgent>();
                if (navMesh != null) navMesh.enabled = false;
                
                var animator = charObj.GetComponent<Animator>();
                if (animator != null) animator.enabled = false;
                
                charObj.SetActive(false);
                
                if (newState == MitaAI.character.None)
                {
                    MelonLogger.Msg($"Fully deactivated character: {targetChar}");
                    currentCharacter = MitaAI.character.None;
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Error in setCharacterState: {ex.Message}");
            }
        }

        public void removeMita(GameObject mitaObject, MitaAI.character character)
        {
            try
            {
                if (mitaObject != null)
                {
                    mitaObject.SetActive(false);
                    
                    var navMesh = mitaObject.GetComponent<NavMeshAgent>();
                    if (navMesh != null) navMesh.enabled = false;
                    
                    var animator = mitaObject.GetComponent<Animator>();
                    if (animator != null) animator.enabled = false;
                    
                    MelonLogger.Msg($"Character {character} removed");
                }
                currentCharacter = MitaAI.character.None;
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Error removing character: {ex.Message}");
            }
        }

        public void sendSystemMessage(string message, MitaAI.character character)
        {
            MelonLogger.Msg($"[System] {message} for {character}");
        }

        public void sendInfoListeners(string message, GameObject sender, MitaAI.character character, string listener)
        {
            MelonLogger.Msg($"[Info] {message} from {sender?.name} to {listener} for {character}");
        }
    }
}
