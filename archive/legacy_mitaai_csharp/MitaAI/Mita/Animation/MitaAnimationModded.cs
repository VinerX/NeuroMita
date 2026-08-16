using Il2Cpp;

using MelonLoader;
using System.Collections;
using UnityEngine;
using System.Text.RegularExpressions;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine.Playables;
using UnityEngine.AI;
using Il2CppRootMotion.FinalIK;
using UnityEngine.Events;
using Harmony;
using System.Linq;
using System.ComponentModel.Design;
namespace MitaAI.Mita
{


    public class MitaAnimationModded
    {
       
        static private Il2CppAssetBundle bundle;
        static AnimationClip idleAnimation;
        static AnimationClip idleWalkAnimation;

        static Dictionary<Character,MitaAnimationModded> allMitaAnimationModded = new Dictionary<Character, MitaAnimationModded> { };
        public static MitaAnimationModded getMitaAnimationModded(Character character) {
             
            if (!allMitaAnimationModded.ContainsKey(character))
            {
                MitaAnimationModded mitaAnimationModded = new MitaAnimationModded();
                allMitaAnimationModded[character] = mitaAnimationModded;
            }

            return allMitaAnimationModded[character];


        }
        public static MitaAnimationModded getMitaAnimationModded(characterType character)
        {
            foreach (var item in Component.FindObjectsOfType<Character>())
            {
                if (item.characterType == character) return getMitaAnimationModded(item);
            }

            return null;

        }



        static private LinkedList<MitaActionAnimation> animationList = new LinkedList<MitaActionAnimation>();
        private bool isPlaying = false;
        public Animator_FunctionsOverride mitaAnimatorFunctions;
        public Location34_Communication location34_Communication;

        // Основной метод для добавления анимации в очередь
        public RuntimeAnimatorController runtimeAnimatorController;
        public AnimatorOverrideController overrideController;
        public Animator animator;
        public NavMeshAgent mitaNavMeshAgent;
        public characterType mitaCharacter;
        public Character_Look mitaLook;
        public MitaPerson mitaPerson;
        ///public static LookAtIK = 

        static public GameObject bat;
        static public GameObject pipe;

        string initIdle = "Mita Idle_2";
        string initWalk = "Mita Walk_1";
        public string currentIdleAnim = "Mita Idle_2";
        public string currentWalkAnim = "Mita Walk_1";



        public static void init(Character character,Animator_FunctionsOverride _mitaAnimatorFunctions, Location34_Communication _location34_Communication, Character_Look _mitaLook,MitaPerson _mitaPerson, bool changeAnimationController = true, bool changeAnimation = true)
        {
            //MitaAnimationModded mitaAnimationModded = new MitaAnimationModded();
            //allMitaAnimationModded[character] = mitaAnimationModded;
            var mitaAnimationModded = getMitaAnimationModded(character);

            // Получаем компонент Animator_FunctionsOverride из текущего объекта
            mitaAnimationModded.mitaCharacter = character.characterType;
            mitaAnimationModded.mitaAnimatorFunctions = _mitaAnimatorFunctions;
            mitaAnimationModded.location34_Communication = _location34_Communication;
            mitaAnimationModded.mitaLook = _mitaLook;
            mitaAnimationModded.mitaPerson = _mitaPerson;
            if (bundle == null)
            {
                bundle = MitaCore.bundle; //AssetBundleLoader.LoadAssetBundle("assetbundle");
            }
            
            if (mitaAnimationModded.mitaAnimatorFunctions == null)
            {
                MelonLogger.Msg("Animator_FunctionsOverride component not found on this object!");
            }


            try
            {
              
                if (changeAnimationController)
                {
                    mitaAnimationModded.runtimeAnimatorController = AssetBundleLoader.LoadAnimatorControllerByName(bundle, "Mita_1.controller");
                    mitaAnimationModded.overrideController = new AnimatorOverrideController(mitaAnimationModded.runtimeAnimatorController);

                    mitaAnimationModded.mitaAnimatorFunctions.animOver = mitaAnimationModded.overrideController;

                    MelonLogger.Msg("Change Animation controller");


                    mitaAnimationModded.animator = MitaCore.Instance.MitaPersonObject.GetComponent<Animator>();
                    mitaAnimationModded.animator.runtimeAnimatorController = mitaAnimationModded.overrideController;
                    mitaAnimationModded.animator.SetTrigger("NextLerp");
                    mitaAnimationModded.animator.Rebind();

                    try
                    {
                        MelonLogger.Msg("Change Look to blik and opem eyes ");
                        _mitaPerson.startEmotion = "None";
                        _mitaPerson.FaceEmotionOff();
                        _mitaLook.Activation(true);
                        _mitaLook.ActivationBlink(true);
                    }
                    catch (Exception ex)
                    {

                        MelonLogger.Warning(ex);
                    }

                    if (changeAnimation)
                    {
                        MelonLogger.Msg("changeAnimation Specific");
                        idleAnimation = mitaAnimationModded.FindAnimationClipInControllerByName(mitaAnimationModded.initIdle);
                        // Пока что так))
                        switch (character.characterType)
                        {

                            case characterType.Player:
                                break;
                            case characterType.None:
                                break;
                            case characterType.Crazy:
                                break;
                            case characterType.Cappy:
                                //idleAnimation = FindAnimationClipInControllerByName("Mita Hands Down Idle");
                                //idleWalkAnimation = FindAnimationClipInControllerByName("Mita Walk_7");
                                //setIdleAnimation("Mita Hands Down Idle");
                                //setIdleWalk("Mita Walk_7");
                                break;
                            case characterType.Kind:
                                break;
                            case characterType.Cart_portal:
                                break;
                            case characterType.ShortHair:
                                break;
                            case characterType.Cart_divan:
                                break;
                            case characterType.Mila:
                                //idleWalkAnimation = FindAnimationClipInControllerByName("MitaWalkMila");
                                //idleAnimation = FindAnimationClipInControllerByName("Mila Stay T");
                                //setIdleWalk("MitaWalkMila");
                                //setIdleAnimation("Mila Stay T");
                                break;
                            case characterType.Sleepy:
                                break;
                            case characterType.Creepy:
                                break;
                            case characterType.GameMaster:
                                break;
                            default:
                                break;
                        }

                    }

                }
                else
                {
                    MelonLogger.Msg("No Change Animation controller");
                    mitaAnimationModded.runtimeAnimatorController = mitaAnimationModded.animator.runtimeAnimatorController;
                }
               
                foreach (var item in mitaAnimationModded.runtimeAnimatorController.animationClips)
                {
                    setCustomAnimatiomEvents(item);
                }
                mitaAnimationModded.mitaNavMeshAgent = MitaCore.Instance.MitaPersonObject.GetComponent<NavMeshAgent>();

                if (changeAnimation){
                    mitaAnimationModded.animator.Rebind();
                    mitaAnimationModded.animator.Update(0);
                }

                mitaAnimationModded.checkCanMoveRotateLook(true);


            }
            catch (Exception ex)
            {

                MelonLogger.Msg("Error custom controller"+ex);
            }
            
            

        }

        

        static private void setCustomAnimatiomEvents(AnimationClip anim)
        { 
            if (anim.name.Contains("Click")){

                anim.events = new Il2CppReferenceArray<AnimationEvent>(0);
                MelonLogger.Msg("AddedAnimationEvent for" + anim.name);
                EventsProxy.AddAnimationEvent(MitaCore.Instance.MitaObject, anim, "Mita Click");
                return;
            }


            switch (anim.name)
            {
                case "Mita TakeMita":
                    MelonLogger.Msg("AddedAnimationEvent for" + anim.name);
                    EventsProxy.AddAnimationEvent(MitaCore.Instance.MitaObject, anim, "TakePlayer");
                    break;
                case "Mita Kick":
                    MelonLogger.Msg("AddedAnimationEvent for" + anim.name);
                    EventsProxy.AddAnimationEvent(MitaCore.Instance.MitaObject, anim, anim.name);
                    break;
                default:
                    anim.events = new Il2CppReferenceArray<AnimationEvent>(0);
                    break;
            }
            
        }


        public string setAnimation(string response)
        {
            // Если запрещено двигаться
            //ObjectAnimationMita.finishWorkingOAM();
            //resetToIdleAnimation(false);

            // Регулярное выражение для извлечения эмоций
            string pattern = @"<a>(.*?)</a>";
            Match match = Regex.Match(response, pattern);

            string cleanedResponse = Regex.Replace(response, @"<a>.*?</a>", ""); // Очищаем от всех тегов

            string animName = "";
            string param1 = "";
            string param2 = "";
            string param3 = "";


            if (match.Success)
            {
                // Если эмоция найдена, устанавливаем её в переменную faceStyle
                string[] parts = match.Groups[1].Value.Split(',');

                animName = parts[0];
                param1 = parts.Length > 1 ? parts[1] : "";
                param2 = parts.Length > 2 ? parts[2] : "";
                param3 = parts.Length > 3 ? parts[3] : "";

            }
            try
            {
                // Проверка на наличие объекта Mita перед применением эмоции
                if (MitaCore.Instance.Mita == null || MitaCore.Instance.Mita.gameObject == null)
                {
                    MelonLogger.Error("Mita object is null or Mita.gameObject is not active.");
                    return cleanedResponse; // Возвращаем faceStyle и очищенный текст
                }
                // Устанавливаем лицо, если оно найдено
                switch (animName)
                {
                    case "Щелчек":
                        int randomIndex = UnityEngine.Random.Range(0, 4); // Генерация числа от 0 до 3
                        string animationName;

                        if (randomIndex == 5)
                            animationName = "Mita Click_0"; // Не то
                        else if (randomIndex == 1)
                            animationName = "Mita Click 1";
                        else if (randomIndex == 6) // Будет
                            animationName = "Mita Click_2";
                        else
                            animationName = "Mita Click"; // Четвёртый кейс

                        EnqueueAnimation(animationName);
                        break;
                    case "Похлопать в ладоши":
                        EnqueueAnimation("Mita Cheerful");
                        break;
                    case "Помахать в приветствие":
                        EnqueueAnimation("Mita Hello");
                        break;
                    case "Указать направление":
                        EnqueueAnimation("Mita ShowTumb");
                        break;
                    case "Смотреть с презрением":
                        EnqueueAnimation("Mita IdleBat");
                        setIdleAnimation("Mita IdleBat");
                        break;
                    case "Показать усталость":
                        EnqueueAnimation("Mita Start Tired");
                        setIdleAnimation("Mita Tired");
                        break;
                    case "Притвориться отключенной и упасть":
                        MitaMovement.setMovementStyle(MitaCore.Instance.currentCharacter,MovementStyles.layingOnTheFloorAsDead);
                        EnqueueAnimation("Mita Fall Start");
                        setIdleAnimation("Mita Fall Idle");

                        break;
                    case "Взять предмет":
                        EnqueueAnimation("Mita TakeBat");
                        
                        break;
                    case "Жест пальцами":
                        mitaLook.LookOnPlayerAndRotate();
                        EnqueueAnimation("Mita FingersGesture");
                        break;
                    case "Кивнуть да":
                        mitaLook.Nod(true);
                        break;
                    case "Кивнуть нет":
                        mitaLook.Nod(false);
                        break;
                    case "Глянуть глазами в случайном направлении":
                        mitaLook.EyesLookOffsetRandom(90);
                        break;
                    case "Повернуться в случайном направлении":
                        mitaLook.LookRandom();
                        break;
                    case "Развести руки":
                        //EnqueueAnimation("Mita StartShow Knifes");
                        EnqueueAnimation("Mita Throw Knifes");
                        break;
                    case "Руки по бокам":
                        EnqueueAnimation("Mita Idle NoKnifes");
                        setIdleAnimation("Mita Idle NoKnifes");
                        break;
                    case "Руки сложены в ладони перед собой":
                        EnqueueAnimation("Mita Idle Cheerful");
                        setIdleAnimation("Mita Idle Cheerful");
                        break;
                    case "Одна рука прижата, вторая сзади":
                        EnqueueAnimation("Mita Hairbrash");
                        setIdleAnimation("Mita Hairbrash");
                        break;
                    case "Поднести палец к подбородку":
                        EnqueueAnimation("Mita TalkWithPlayer");
                        setIdleAnimation("Mita TalkWithPlayer");
                        break;
                    case "Поднять игрока одной рукой":
                       

                        EnqueueAnimation("Mita TakeMita"); 
                        
                        //EnqueueAnimation("Mita TakeMita Idle");
                        setIdleAnimation("Mita TakeMita Idle");
                        //EnqueueAnimation("Mita ThrowPlayer");
                        break;
                    case "Скинуть игрока":
                        PlayerAnimationModded.currentPlayerMovement = PlayerMovementType.normal;
                        EnqueueAnimation("Mita ThrowPlayer");
                        //EnqueueAnimation("Mita TakeMita Idle");

                        setIdleAnimation("Mita Idle_2");
                        //EnqueueAnimation("Mita ThrowPlayer");
                        break;
                    case "Руки вперед по бокам":
                        EnqueueAnimation("Mita Hands Down Idle");
                        setIdleAnimation("Mita Hands Down Idle");
                        break;
                    case "Сложить руки перед собой":
                        EnqueueAnimation("Mita Idle_2");
                        setIdleAnimation("Mita Idle_2");
                        break;
                    case "Показать предмет":
                        EnqueueAnimation("Mita Selfi");
                        break;
                    case "Стать разочарованной":
                        EnqueueAnimation("Mita StartDisappointment");
                        setIdleAnimation("Mita IdleDisappointment");
                        break;
                    case "Руки в кулаки":
                        EnqueueAnimation("Mita StartAngry");
                        setIdleAnimation("Mita IdleAngry");
                        break;
                    case "Сесть и плакать":
                        EnqueueAnimation("Mila CryNo");
                        setIdleAnimation("Mila CryNo");
                        
                        MitaMovement.setMovementStyle(MitaCore.Instance.currentCharacter,MovementStyles.cryingOnTheFloor);
                        break;
                    case "Дружески ударить":
                        EnqueueAnimation("Mila Kick");
                        break;
                    case "Посмотреть по сторонам":
                        EnqueueAnimation("Mita IdleCheck");
                        break;
                    case "Прикрыть глаза":
                        EnqueueAnimation("Mita Close Eyes");
                        //int randomIndex = UnityEngine.Random.Range(0, 4); // Генерация числа от 0 до 3
                        EnqueueAnimation("Mita Open Eyes");
                        //EnqueueAnimation("Mita Open Shar Eyes");
                        break;
                    case "Обнять":
                        EnqueueAnimation("Mita StartHug");
                        EnqueueAnimation("Mita HugIdle");
                        EnqueueAnimation("Mita StopHug");
                        break;
                    case "Удар":
                        // Проверяем, какой персонаж сейчас активен

                        try
                        {
                            if (mitaCharacter == characterType.Kind)
                            {
                                // Если активен Kind персонаж, используем трубу
                                if (pipe == null){
                                    pipe = MitaCore.worldBasement.Find("Mita Future/MitaPerson Future/RightItem/Tube Basement").gameObject;
                                }
                                pipe.active = true;
                                pipe.transform.SetParent(MitaCore.getMitaHand(MitaCore.Instance.MitaPersonObject));
                                pipe.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);

                            }
                            else
                            {
                                // Для других персонажей используем биту
                                bat.active = true;
                                pipe.transform.SetParent(MitaCore.getMitaHand(MitaCore.Instance.MitaPersonObject));
                                pipe.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);

                            }
                        }
                        catch (Exception ex)
                        {

                            MelonLogger.Error(ex);
                        }
                       
                        EnqueueAnimation("Mita Kick");
                        break;
                    case "Помахать перед лицом":
                        EnqueueAnimation("Hey");
                        break;
                    case "Помахать руками в стороны":
                        EnqueueAnimation("Mita HandsDance");
                        break;
                    case "Начать махать руками в стороны":
                        EnqueueAnimation("Mita HandsDance");
                        setIdleAnimation("Mita HandsDance");
                        break;

                    case "Круто протанцевать":
                        EnqueueAnimation("Mita HandsDance");
                        //EnqueueAnimation("DanceTest");
                        break;
                    case "Начать круто танцевать":
                        EnqueueAnimation("Mita HandsDance");
                        setIdleAnimation("Mita HandsDance");
                        //EnqueueAnimation("DanceTest");
                        //setIdleAnimation("DanceTest");
                        break;

                    case "Похвастаться предметом":
                        EnqueueAnimation("Mita Take Recorder");
                        break;
                    case "Прикрыть рот и помахать рукой":
                        EnqueueAnimation("Mita Oi");
                        //EnqueueAnimation("Mita Idle");
                        EnqueueAnimation("Mita Oi Heh");
                        break;
                    case "Стать уставшей":
                        EnqueueAnimation("Mita Start Tired");
                        //EnqueueAnimation("Mita Idle");
                        setIdleAnimation("Mita Tired");
                        break;

                    case "Случайная анимация":
                        EnqueueAnimation("");
                        break;


                    default:
                        if (animName != "")
                        {
                            MelonLogger.Warning($"Added to que defult case {animName}");
                            EnqueueAnimation(animName);
                        }

                        break;
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Problem with Animation: {ex.Message}");
            }

            // Возвращаем кортеж: лицо и очищенный текст
            return cleanedResponse;
        }
        
        // Даже головой не крутит
        private static readonly MovementStyles[] MovementStylesNoMovingAtAll =
        {
            MovementStyles.cryingOnTheFloor,
            MovementStyles.layingOnTheFloorAsDead

        };
        
        // Крутит головой
        private static readonly MovementStyles[] MovementStylesNoBodyLooking =
        {
            MovementStyles.sitting
        };

        // Крутит головой и телом, но не ходит
        private static readonly MovementStyles[] MovementStylesNoWalking =
        {
            //MovementStyles.sitting
        };

        // Отвечает за перемещение и поворот миты.
        public void checkCanMoveRotateLook(bool ignoreInteractionCondition = false)
        {
            if (MitaState.GetCurrentState(mitaCharacter) == MitaStateType.interaction && !ignoreInteractionCondition) return;

            var currentMovementStyle = MitaMovement.GetMovementStyle(MitaCore.Instance.currentCharacter);
            // Если запрещено двигаться
            if (MovementStylesNoMovingAtAll.Contains(currentMovementStyle))
            {
                mitaLook.activeBodyIK = false;
                mitaLook.canRotateBody = false;
                location34_Communication.ActivationCanWalk(false);
            }
            else if (MovementStylesNoBodyLooking.Contains(currentMovementStyle))
            {
                mitaLook.activeBodyIK = true;
                mitaLook.enabled = true;
                mitaLook.canRotateBody = false;
                location34_Communication.ActivationCanWalk(false);
            }
            else if (MovementStylesNoWalking.Contains(currentMovementStyle))
            {
                mitaLook.activeBodyIK = true;
                mitaLook.enabled = true;
                mitaLook.canRotateBody = true;
                location34_Communication.ActivationCanWalk(false);
            }
            else
            {
                mitaLook.activeBodyIK = true;
                mitaLook.canRotateBody = true;
                mitaLook.enabled = true;
                location34_Communication.ActivationCanWalk(true);

            }

        }

        public void EnqueueAnimation(string animName = "", float crossfadeLen = 0.25f,
                                   float timeBefore = 0, float timeAfter = 0, bool makeFirst = false,
                                   bool avoidStateSettings = false)
        {

            HandleAnimationEnqueue(() =>
                new MitaActionAnimation(
                    animName,
                    crossfadeLen,
                    crossfadeLen,
                    timeBefore,
                    timeAfter,
                    timeAfter,
                    avoidStateSettings
                ),
                animName,
                makeFirst,
                $"Start Que cor from {animName}"
            );
        }

        public static void EnqueueAnimationCurrent(string animName = "", float crossfadeLen = 0.25f,
                                           float delayBefore = 0, float delayAfter = 0, bool makeFirst = false,
                                           bool avoidStateSettings = false)
        {
            getMitaAnimationModded(MitaCore.Instance.currentCharacter).HandleAnimationEnqueue(() =>
                new MitaActionAnimation(
                    animName,
                    crossfadeLen,
                    crossfadeLen,
                    0,
                    delayBefore,
                    delayAfter,
                    avoidStateSettings
                ),
                animName,
                makeFirst,
                $"Start Que cor from {animName}"
            );
        }
        public static void EnqueueAnimationCurrent(ObjectAnimationMita objectAnimationMita,
                                           float crossfadeLen = 0.25f, float delayBefore = 0,
                                           float delayAfter = 0, bool makeFirst = false)
        {
            getMitaAnimationModded(MitaCore.Instance.currentCharacter).HandleAnimationEnqueue(() =>
                new MitaActionAnimation(
                    objectAnimationMita.mitaAmimatedName,
                    objectAnimationMita.AnimationTransitionDuration,
                    crossfadeLen,
                    0,
                    objectAnimationMita,
                    delayBefore,
                    delayAfter
                ),
                objectAnimationMita.mitaAmimatedName,
                makeFirst,
                $"Start Que cor from OAM {objectAnimationMita.mitaAmimatedName}",
                "objectAnimationMita "
            );
        }
        public void EnqueueAnimation(ObjectAnimationMita objectAnimationMita,
                                           float crossfadeLen = 0.25f, float time = 0,
                                           float delatBefore = 0, float delayAfter = 0, bool makeFirst = false)
        {
            HandleAnimationEnqueue(() =>
                new MitaActionAnimation(
                    objectAnimationMita.mitaAmimatedName,
                    objectAnimationMita.AnimationTransitionDuration,
                    crossfadeLen,
                    time,
                    objectAnimationMita,
                    delatBefore,
                    delayAfter
                ),
                objectAnimationMita.mitaAmimatedName,
                makeFirst,
                $"Start Que cor from OAM {objectAnimationMita.mitaAmimatedName}",
                "objectAnimationMita "
            );
        }

        private void HandleAnimationEnqueue(Func<MitaActionAnimation> animationFactory,
                                                  string animationName,
                                                  bool makeFirst,
                                                  string startMessage,
                                                  string logPrefix = "")
        {
            try
            {
                var animation = animationFactory();
                AddAnimationToList(animation, makeFirst);

                MelonLogger.Msg($"Added {logPrefix}to queue: {animationName}");

                StartQueueProcessingIfNeeded(startMessage);
            }
            catch (Exception e)
            {
                MelonLogger.Msg($"Animation error: {e}");
            }
        }

        private void AddAnimationToList(MitaActionAnimation animation, bool makeFirst)
        {
            if (makeFirst)
                animationList.AddFirst(animation);
            else
                animationList.AddLast(animation);
        }

        private void StartQueueProcessingIfNeeded(string startMessage)
        {
            if (isPlaying) return;

            MelonLogger.Msg(startMessage);
            MelonCoroutines.Start(ProcessQueue());
        }


        AnimationClip FindAnimationClipInControllerByName(string animationName)
        {
            if (runtimeAnimatorController == null) return null;

            AnimationClip[] clips = runtimeAnimatorController.animationClips;

            foreach (AnimationClip clip in clips)
            {
                if (clip.name == animationName)
                {
                    MelonLogger.Msg($"{animationName} found in runtimeAnimatorController");
                    return clip;
                }
            }

            return null;
        }
        
        
        // Корутина для последовательного проигрывания
        private IEnumerator ProcessQueue()
        {
            isPlaying = true;

            location34_Communication.ActivationCanWalk(false);

            while (animationList.Count > 0)
            {

                MitaActionAnimation animObject = animationList.First();
                animationList.RemoveFirst();

                MelonLogger.Msg($"ANIM LIST: count {animationList.Count} Now playing: {animObject.animName} {animObject.animationType} {animObject.ObjectAnimationMita}");

                if (animObject.ObjectAnimationMita != null)
                {
                    yield return MelonCoroutines.Start( processObjectAnimationMita(animObject) );
                }
                else
                {
                    yield return MelonCoroutines.Start( processAnimationMita(animObject) );

                }
                
                
                if (!animObject.avoidStateSettings) checkCanMoveRotateLook();
                
                yield return new WaitForSeconds(animObject.delay_after);

            }

            MitaMovement.ChoseStyle(MitaCore.Instance.currentCharacter,currentIdleAnim);
            checkCanMoveRotateLook();
            MelonLogger.Msg($"Ended quque currentIdleAnim {currentIdleAnim}");
            animator.CrossFade("Idle",0.25f);
            
            
            isPlaying = false;
        }
        
        
        IEnumerator processObjectAnimationMita(MitaActionAnimation animObject)
        {
            ObjectAnimationMita objectAnimationMita = animObject.ObjectAnimationMita;
            MelonLogger.Msg($"Now playing OAM: {objectAnimationMita.name} {objectAnimationMita.tip}");
            objectAnimationMita.Play(mitaPerson, mitaCharacter);


            float beforeWalk = Time.unscaledTime;

            yield return new WaitForSeconds(0.25f);
            while (objectAnimationMita.isWalking && Time.unscaledTime - beforeWalk < 20f) yield return new WaitForSeconds(0.25f);
            

            MelonLogger.Msg($"Now ended walking OAM: {objectAnimationMita.name} {objectAnimationMita.tip}");
        }
        IEnumerator processAnimationMita(MitaActionAnimation animObject)
        {

            string animName = animObject.animName;
            float crossfadeLen = animObject.begin_crossfade;
            float delayBefore = animObject.delay_before;
            float delayAfter = animObject.delay_after;
            bool avoidStateSettings = animObject.avoidStateSettings;
            var ObjectAnimationMita = animObject.ObjectAnimationMita;

            

            MelonLogger.Msg($"Crossfade");
            MelonLogger.Msg($"Now playing: {animName}");
            if (delayBefore > 0) yield return new WaitForSeconds(delayBefore);

            mitaAnimatorFunctions.anim.CrossFade(animName, crossfadeLen);
                    
            AnimationClip anim = FindAnimationClipInControllerByName(animName);

            if (anim != null)
            { 
                // Вот это надо донастроить
                if (anim.events.Count > 0)
                {
                    // yield return new WaitForSeconds(anim.events[0].floatParameter);
                    MitaCore.Instance.MitaObject.GetComponent<EventsProxy>().OnAnimationEvent(anim.events[0].stringParameter);
                }

                MelonLogger.Msg($"Before WaitForAnimationCompletion");

                yield return new WaitForSeconds(Math.Min(anim.length + 0.25f, 30f));

                MelonLogger.Msg($"After WaitForAnimationCompletion");
            }

            

            if (animName == "Mita Kick")
            {
                // После завершения анимации удара деактивируем оба объекта
                bat.active = false;
                pipe.active = false;
            }
            if (delayAfter > 0) yield return new WaitForSeconds(delayAfter);


        }

        public void resetToIdleAnimation(bool toInitAnim = true, bool total_clear = false,bool needEnque = false)
        {
            string anim = toInitAnim ? initIdle : currentIdleAnim;

            if (needEnque) EnqueueAnimation(anim);

            setIdleAnimation(anim);
            

            if (total_clear) ClearQueue();

            

        }
        public void setIdleAnimation(string animName)
        {
           
            if (!string.IsNullOrEmpty(animName))
            {
                try
                {
                    currentIdleAnim = animName;
                    AnimationClip anim = FindAnimationClipInControllerByName(animName);
                    location34_Communication.mitaAnimationIdle = anim;
                    MitaMovement.ChoseStyle(MitaCore.Instance.currentCharacter,animName);
                    checkCanMoveRotateLook();
                    mitaAnimatorFunctions.ReAnimationClip(initIdle, anim);

                }
                catch (Exception e)
                {

                    MelonLogger.Error($"setIdleAnimation: {e}");
                }

            }

        }   
        public void setIdleWalk(string animName)
        {

            if (string.IsNullOrEmpty(animName)) return;
            
            AnimationClip anim = FindAnimationClipInControllerByName(animName);

            if (anim == null)
            {
                MelonLogger.Error($"setIdleWalk {animName} is null");
            }
            else
            {
                currentWalkAnim = animName;
                location34_Communication.mitaAnimationWalk = anim;
                mitaAnimatorFunctions.ReAnimationClip(initWalk, anim);
                location34_Communication.AnimationReWalk(anim);
            }       


        }

        // Очистка очереди (опционально)
        public void ClearQueue()
        {
            animationList.Clear();
            isPlaying = false;
        }
    
    

    
    }

}
