using Il2Cpp;

using MelonLoader;
using UnityEngine;
using System.Collections;
using UnityEngine.Events;
using UnityEngine.UIElements;
using Il2CppColorful;
using static Il2CppRootMotion.FinalIK.GenericPoser;

namespace MitaAI
{
    public enum PlayerMovementType
    {
        normal,
        sit,
        taken
    }


    public static class PlayerAnimationModded
    {

        public static PlayerMovementType currentPlayerMovement = PlayerMovementType.normal;

        static ObjectAnimationPlayer objectAnimationPlayer;
        static private Queue<AnimationClip> animationQueue = new Queue<AnimationClip>();
        static private bool isPlaying = false;
        static public PlayerMove playerMove;
        static public PlayerPersonIK playerPersonIK;
        public static Dictionary<string, AnimationClip> PlayerAnimations { get; private set; } = new Dictionary<string, AnimationClip>();

        public static Dictionary<string, ObjectAnimationPlayer> ObjectsAnimationPlayer = new Dictionary<string, ObjectAnimationPlayer>();

        public static AnimationClip getPlayerAnimationClip(string name)
        {

            if (PlayerAnimations.ContainsKey(name)) return PlayerAnimations[name];
            else return null;
        }

        public static void UpdateSpeedAnimation(float speed)
        {
            // Получаем аниматор игрока
            Animator playerAnimator = PlayerAnimationModded.playerMove.GetComponent<Animator>();

            if (playerAnimator != null)
            {
                // Устанавливаем параметр скорости для анимаций
                playerAnimator.SetFloat("Speed", speed);  // Здесь "Speed" — это имя параметра в аниматоре
            }

        }
        public static void StopPlayerAnimation()
        {
            // Получаем аниматор игрока
            Animator playerAnimator = PlayerAnimationModded.playerMove.GetComponent<Animator>();

            if (playerAnimator != null)
            {
                // Останавливаем анимации
                playerAnimator.SetFloat("Speed", 0f);  // Ставим скорость в 0 для остановки анимации
                playerAnimator.speed = 0f;  // Останавливаем проигрывание анимации
            }
        }
        public static void ResumePlayerAnimation()
        {
            // Получаем аниматор игрока
            Animator playerAnimator = PlayerAnimationModded.playerMove.GetComponent<Animator>();

            if (playerAnimator != null)
            {
                // Возобновляем анимации
                playerAnimator.SetFloat("Speed", 1f);  // Возвращаем скорость к нормальному значению
                playerAnimator.speed = 1f;  // Возвращаем нормальную скорость воспроизведения
            }
        }



        public static void Init(GameObject player, Transform worldHouse, PlayerMove _playerMove)
        {
            objectAnimationPlayer = player.AddComponent<ObjectAnimationPlayer>();
            playerPersonIK = MitaCore.Instance.playerPersonObject.GetComponent<PlayerPersonIK>();

            playerMove = _playerMove;
            FindPlayerAnimationsRecursive(worldHouse);
            //FindPlayerAnimationsRecursive(MitaCore.worldTogether);
            // Ищем анимации в DontDestroyOnLoad

            FindPlayerAnimationsInDontDestroyOnLoad();
            //foreach (var el in PlayerAnimations) MelonLogger.Msg($"Player clip {el.Key}");

        }

        public static void Check()
        {
            foreach (var el in PlayerAnimations) MelonLogger.Msg($"Player clip {el.Key}");
        }

        private static void FindPlayerAnimationsInDontDestroyOnLoad()
        {
            // Получаем корневой объект сцены DontDestroyOnLoad
            GameObject[] dontDestroyOnLoadObjects = GameObject.FindObjectsOfType<GameObject>();
            foreach (var obj in dontDestroyOnLoadObjects)
            {
                // Проверяем, что объект находится в сцене DontDestroyOnLoad
                if (obj.hideFlags == HideFlags.None && obj.scene.name == "DontDestroyOnLoad")
                {
                    // Рекурсивно ищем анимации
                    FindPlayerAnimationsRecursive(obj.transform);
                }
            }
        }

        #region objectAnimationPlayer
        
        private static GameObject ObjectAnimationContainer;



        public static void copyAllObjectAnimationPlayerFromParent(Transform parent)
        {
            if (parent == null) return;

            for (int i = 0; i < parent.childCount; i++)
            {
                Transform child = parent.GetChild(i);
                if (child == null) continue;

                copyAllObjectAnimationPlayerFromParent(child); // Рекурсивный вызов для вложенных объектов

                ObjectAnimationPlayer oap = child.GetComponent<ObjectAnimationPlayer>();
                if (oap == null) continue;

                if ( !ObjectsAnimationPlayer.ContainsKey(oap.name))
                {

                    ObjectsAnimationPlayer[oap.name] = GameObject.Instantiate(oap.gameObject).GetComponent<ObjectAnimationPlayer>();
                    

                    if (ObjectAnimationContainer == null)
                    {
                        ObjectAnimationContainer = new GameObject("ObjectAnimationContainer");
                        GameObject.DontDestroyOnLoad(ObjectAnimationContainer);
                    }
                    ObjectsAnimationPlayer[oap.name].name = oap.name;
                    ObjectsAnimationPlayer[oap.name].transform.SetParent(ObjectAnimationContainer.transform);
                    ObjectsAnimationPlayer[oap.name].gameObject.SetActive(false);
                }
            }
        }

        public static ObjectAnimationPlayer CopyObjectAmimationPlayerTo(Transform parent,string name, string position="center",float rotation = 60,UnityAction freeCase = null)
        {

            if (ObjectsAnimationPlayer.ContainsKey(name))
            {
                var OAPobj = GameObject.Instantiate(ObjectsAnimationPlayer[name].gameObject, parent);
                var OI = OAPobj.GetComponent<ObjectInteractive>();
                OAPobj.transform.localPosition = Vector3.zero;
                var CIA = CommonInteractableObject.CheckCreate(parent.gameObject, position, freeCase);
                if (OI != null)
                {
                    
                    OI.objectInteractive = parent.gameObject;
                    OI.active = true;


                    //switch (position.ToLower())
                    //{
                    //    case "center":
                    //        OI.eventClick.AddListener((UnityAction)CIA.setTakenPlayer);
                    //        break;
                    //    case "left":
                    //        OI.eventClick.AddListener((UnityAction)CIA.setTakenPlayerLeft);
                    //        break;
                    //    case "right":
                    //        OI.eventClick.AddListener((UnityAction)CIA.setTakenPlayerRight);
                    //        break;
                    //    default:
                    //        OI.eventClick.AddListener((UnityAction)CIA.setTakenPlayer);
                    //        break;
                    //}



                }
                OAPobj.active = true;
                
               

                var OAP = OAPobj.GetComponent<ObjectAnimationPlayer>();
                OAP.angleHeadRotate = rotation;


               
                if (PlayerAnimations.ContainsKey("Player Stand")) OAP.animationStop = PlayerAnimations["Player Stand"];
                return OAP;
            }


            return null;
        }



        // Для теста всех анимок
        public static void playObjectAnimationOnPlayerRandom()
        {
            if (ObjectsAnimationPlayer == null || ObjectsAnimationPlayer.Count == 0)
            {
                MelonLogger.Msg("No animations available in ObjectsAnimationPlayer");
                return;
            }

            // Получаем список всех ключей
            var keys = new List<string>(ObjectsAnimationPlayer.Keys);

            // Выбираем случайный индекс
            int randomIndex = UnityEngine.Random.Range(0, keys.Count);

            // Получаем случайный ключ
            string randomKey = keys[randomIndex];

            // Вызываем анимацию
            playObjectAnimationOnPlayer(randomKey);
        }

        public static void playObjectAnimationOnPlayer(string objectAnimationName)
        {
            MelonLogger.Msg("playObjectAnimationOnPlayer");
 
            if (ObjectsAnimationPlayer.ContainsKey(objectAnimationName)){
                try
                {
                    try
                    {
                        endLastCIAs();
                    }
                    catch (Exception Ex2)
                    {

                        MelonLogger.Error(Ex2); 
                    }
                    

                    var obj = ObjectsAnimationPlayer[objectAnimationName];

                    

                    //lastCOA.Add(obj);
                    obj.eventFinish = new UnityEngine.Events.UnityEvent();
                    obj.eventFinish.AddListener((UnityAction)obj.AnimationStop);
                    obj.AnimationPlayOnPlayer();

                    

                }
                catch (Exception Ex)
                {

                    MelonLogger.Error(Ex);
                }
                
            }
        }

        private static void endLastCIAs()
        {

            CommonInteractableObject.endLastPlayersCIAs();


        }

        // -0,4194 0,3125 -0,0256  60,0001 91,5637 89,5765 Кресло

        public static void playObjectAnimation(string objectAnimationName, Transform Object, Vector3 localCoords,Quaternion localRotate)
        {
            MelonLogger.Msg("playObjectAnimation");

            if (ObjectsAnimationPlayer.ContainsKey(objectAnimationName))
            {

                try
                {
                    var obj = ObjectsAnimationPlayer[objectAnimationName];
                    obj.transform.SetParent(Object);
                    obj.transform.SetPositionAndRotation(localCoords, localRotate);

                    obj.eventFinish = new UnityEngine.Events.UnityEvent();
                    obj.eventFinish.AddListener((UnityAction)obj.AnimationStop);
                    obj.AnimationPlay();
                   
                    var CIA = obj.GetComponent<CommonInteractableObject>();
                    if ( CIA == null) CIA = obj.transform.parent.GetComponent<CommonInteractableObject>();
                    if (CIA != null)
                    {
                        CIA.setTaken(characterType.Player);
                    }
                    //lastCOA.Add(obj);
                }
                catch (Exception Ex)
                {

                    MelonLogger.Error(Ex);
                }
            }
        }

        #endregion

        public static void FindPlayerAnimationsRecursive(Transform parent)
        {
            if (parent == null) return;

            for (int i = 0; i < parent.childCount; i++)
            {
                Transform child = parent.GetChild(i);
                if (child == null) continue;

                var animator = child.GetComponent<Animator>();
                if (animator != null && animator.runtimeAnimatorController != null)
                {
                    var clips = animator.runtimeAnimatorController.animationClips;
                    if (clips != null)
                    {
                        foreach (var clip in clips)
                        {
                            //MelonLogger.Msg($"Some clip {clip.name}");
                            if (clip != null && clip.name.Contains("Player", StringComparison.OrdinalIgnoreCase) && !PlayerAnimations.ContainsKey(clip.name))
                            {
                                if (!PlayerAnimations.ContainsKey(clip.name)) PlayerAnimations[clip.name] = clip;
                                else if (clip != PlayerAnimations[clip.name]) PlayerAnimations[clip.name + "1"] = clip;
                            }
                        }
                    }
                }
                ObjectAnimationPlayer oap = child.GetComponent<ObjectAnimationPlayer>();
                if (oap != null)
                {
                    if (oap.animationStart != null)
                    {
                        if (!PlayerAnimations.ContainsKey(oap.animationStart.name)) PlayerAnimations[oap.animationStart.name] = oap.animationStart;
                        else if (oap.animationStart != PlayerAnimations[oap.animationStart.name]) PlayerAnimations[oap.animationStart.name + "1"] = oap.animationStart;
                    }
                    if (oap.animationLoop != null)
                    {
                        if (!PlayerAnimations.ContainsKey(oap.animationLoop.name)) PlayerAnimations[oap.animationLoop.name] = oap.animationLoop;
                        else if (oap.animationLoop != PlayerAnimations[oap.animationLoop.name]) PlayerAnimations[oap.animationLoop.name + "1"] = oap.animationLoop;
                    }
                    if (oap.animationStop != null)
                    {
                        if (!PlayerAnimations.ContainsKey(oap.animationStop.name)) PlayerAnimations[oap.animationStop.name] = oap.animationStop;
                        else if (oap.animationStop != PlayerAnimations[oap.animationStop.name]) PlayerAnimations[oap.animationStop.name + "1"] = oap.animationStop;
                    }

                    
                }

                FindPlayerAnimationsRecursive(child); // Рекурсивный вызов для вложенных объектов
            }
        }
        static public void EnqueueAnimation(string animName)
        {
            MelonLogger.Msg("EnqueueAnimation start");
            if (!PlayerAnimations.ContainsKey(animName)) return;
            AnimationClip anim = PlayerAnimations[animName];

            MelonLogger.Msg($"Found {anim.name}");

            try
            {


                if (anim != null)
                {
                    anim.events = Array.Empty<AnimationEvent>();
                    animationQueue.Enqueue(anim);
                    MelonLogger.Msg($"Added to queue: {anim.name}");

                    if (!isPlaying)
                    {
                        MelonCoroutines.Start(ProcessQueue());
                    }
                }
            }
            catch (Exception e)
            {
                MelonLogger.Msg("Animation error: " + e);
            }
        }

        // Корутина для последовательного проигрывания
        static private IEnumerator ProcessQueue()
        {
            isPlaying = true;
            while (animationQueue.Count > 0)
            {
                AnimationClip currentAnim = animationQueue.Dequeue();

                if (currentAnim != null)
                {
                    MelonLogger.Msg($"Now playing: {currentAnim.name} ({currentAnim.length}s)");
                    playAnim(currentAnim);

                    // Ждем завершения анимации
                    yield return new WaitForSeconds(currentAnim.length);
                }
            }
            isPlaying = false;

            yield return new WaitForSeconds(0.5f);
            MelonLogger.Msg($"animationQueue ended");
            try
            {

                playerMove.AnimationStop();
                MelonLogger.Msg($"AnimationStop stopped");
            }
            catch (Exception ex)
            {
                MelonLogger.Msg($"Problem with AnimationStop {ex}");

            }


        }


        public static void playAnim(AnimationClip animStart, AnimationClip animLoop = null, AnimationClip animEnd = null)
        {
            try
            {
                objectAnimationPlayer.animationStart = animStart;
                objectAnimationPlayer.animationLoop = animLoop;
                objectAnimationPlayer.animationStop = animEnd;

                objectAnimationPlayer.AnimationPlay();
            }
            catch (Exception ex)
            {

                MelonLogger.Msg($"Problem with playAnim {ex}");
            }

        }
        public static void playAnimObject(GameObject gameObject)
        {
            ObjectAnimationPlayer animPlayer = gameObject.GetComponent<ObjectAnimationPlayer>() ?? gameObject.transform.Find("OI")?.GetComponent<ObjectAnimationPlayer>();
            try
            {

                if (animPlayer != null)
                {
                    animPlayer.AnimationPlay();

                }

            }
            catch (Exception ex)
            {

                MelonLogger.Msg($"Problem with playAnimObject {ex}");
            }
            if (animPlayer != null)
            {
                MelonCoroutines.Start(endWhenAnotherState(animPlayer));

            }

        }


        public static void TurnHandAnim()
        {
            // Пока так
            playerPersonIK.RemoveItem();
            //playerPersonIK.AnimationHandsFace(true);
            //playerPersonIK.IkZero();
        }

        public static IEnumerator endWhenAnotherState(ObjectAnimationPlayer objectAnimationPlayer)
        {
            MelonLogger.Msg("Begin endWhenAnotherState");
            while (PlayerAnimationModded.currentPlayerMovement == PlayerMovementType.sit)
            {

                yield return new WaitForSeconds(0.25f);
            }
            MelonLogger.Msg("End endWhenAnotherState");
            objectAnimationPlayer.AnimationStop();


            while (!objectAnimationPlayer.firstEventFinishReady)
            {

                yield return null;
            }
            objectAnimationPlayer.AnimationStop();

        }

        public static void stopAnim()
        {
            
            try
            {
                Hints.freeExitButton();
                endLastCIAs();
            }
            catch (Exception Ex)
            {

                MelonLogger.Error(Ex);
            }
            if (PlayerAnimations.ContainsKey("Player Stand")) playerMove.animationStop = PlayerAnimations["Player Stand"]; 
            playerMove.AnimationStop(); 
        }
        public static void UnstackPlayer(bool teleportToZero = true)
        {
            stopAnim();
            
            if (teleportToZero) MitaCore.Instance.playerObject.transform.position = Vector3.zero;
        }

    }
}