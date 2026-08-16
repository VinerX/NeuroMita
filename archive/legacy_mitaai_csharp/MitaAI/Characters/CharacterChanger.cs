//using Il2Cpp;
//using MelonLoader;
//using System;
//using System.Collections.Generic;
//using System.Linq;
//using System.Security.AccessControl;
//using System.Text;
//using System.Threading.Tasks;
//using System.Xml.Serialization;
//using UnityEngine;
//using static Il2CppRootMotion.FinalIK.InteractionObject;

//using UnityEngine.UI;
//using UnityEngine.Device;
//using MitaAI.Mita;
//namespace MitaAI
//{
    
//    public static class CharacterChanger
//    {
//        public statvoid addChangeMita(GameObject NewMitaObject = null, character character = character.Crazy, bool ChangeAnimationControler = true, bool turnOfOld = true, bool changePosition = true, bool changeAnimation = true)
//        {
//            if (NewMitaObject == null)
//            {
//                NewMitaObject = getMitaByEnum(character);

//            }

//            MelonLogger.Msg($"Change Mita {currentCharacter} to {character} Begin");

//            try
//            {


//                if (NewMitaObject == null)
//                {
//                    MelonLogger.Msg("New Mita Object is null!!!");
//                    return;
//                }

//                if (turnOfOld)
//                {
//                    MitaObject.active = false;
//                }

//                currentCharacter = character;
//                NewMitaObject.SetActive(true);
//                MelonLogger.Msg("Change Mita activated her");
//                MitaObject = NewMitaObject;

//                MitaPersonObject = findMitaPersonObject(MitaObject);



//                if (MitaPersonObject == null)
//                {
//                    MelonLogger.Msg("Mita (Mita Person comp) is null");
//                    MitaPersonObject = MitaObject.transform.Find("MitaPerson Future").gameObject;
//                };

//                if (changePosition) MitaPersonObject.transform.position = Vector3.zero;

//                if (MitaPersonObject.GetComponent<Character>() == null)
//                {
//                    var comp = MitaPersonObject.AddComponent<Character>();
//                    comp.init(character);
//                }

//                // Интеграция CharacterLogic
//                Character characterComponent = MitaPersonObject.GetComponent<Character>();
//                if (characterComponent == null)
//                {
//                    characterComponent.init(character); // Предполагается, что init инициализирует персонажа
//                }

//                MitaLook = MitaPersonObject.transform.Find("IKLifeCharacter").GetComponent<Character_Look>();

//                if (MitaLook.forwardPerson == null)
//                {
//                    MitaLook.forwardPerson = MitaPersonObject.transform;
//                }
//                if (character == character.Creepy)
//                {
//                    LogicCharacter.Instance.Initialize(MitaPersonObject, character);
//                }
//                if (character == character.Creepy)
//                {
//                    LogicCharacter.Instance.Initialize(MitaPersonObject, character);
//                }

//                MelonLogger.Msg("333");

//                MitaAnimatorFunctions = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
//                Mita = MitaObject.GetComponent<MitaPerson>();


//                if (Mita == null)
//                {

//                    MelonLogger.Msg("MitaPersonObject is null");
//                };
//                MitaAnimationModded.mitaAnimatorFunctions = MitaAnimatorFunctions;
//                var animator = MitaPersonObject.GetComponent<Animator>();
//                MitaAnimationModded.animator = animator;


//                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");

//                try
//                {

//                    var audioSource = MitaPersonObject.transform.Find("Armature/Hips/Spine/Chest/Neck2/Neck1/Head").GetComponent<AudioSource>();
//                    AudioControl.dataValues_Sounds.audioSource = audioSource;
//                    if (audioSource == null) MelonLogger.Msg("Audiosourse is null(((");

//                    // Получаем тип компонента
//                    Type audioDialogueType = typeof(Il2Cpp.AudioDialogue);

//                    // Получаем поле audioVoice через Reflection
//                    FieldInfo audioVoiceField = audioDialogueType.GetField("audioVoice", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);

//                    if (audioVoiceField != null)
//                    {
//                        // Получаем компонент AudioDialogue
//                        var audioDialogue = AudioControl.MitaDualogueSpeak.GetComponent<Il2Cpp.AudioDialogue>();

//                        // Устанавливаем значение поля через Reflection
//                        audioVoiceField.SetValue(audioDialogue, audioSource);
//                    }
//                    else
//                    {
//                        Debug.LogError("Поле audioVoice не найдено!");
//                    }

//                }
//                catch (Exception ex)
//                {

//                    MelonLogger.Msg($"5a0 {ex}");
//                }
//                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");

//                if (ChangeAnimationControler)
//                {
//                    try
//                    {

//                        MitaAnimationModded.animator.runtimeAnimatorController = MitaAnimationModded.runtimeAnimatorController;
//                        //AnimatorOverrideController AOC = MitaAnimationModded.animator.runtimeAnimatorController as AnimatorOverrideController;
//                        //AOC.runtimeAnimatorController = MitaAnimationModded.runtimeAnimatorController;
//                    }
//                    catch (Exception ex)
//                    {

//                        MelonLogger.Msg($"5a {ex}");
//                    }
//                }

//                try
//                {


//                }
//                catch (Exception ex)
//                {

//                    MelonLogger.Error($"5a {ex}");
//                }


//                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");
//                MelonLogger.Msg("666");
//                //MitaAnimationModded.overrideController = MitaAnimationModded.runtimeAnimatorController;
//                //location21_World.mitaTransform = MitaPersonObject.transform;
//                //location21_World.
//                try
//                {
//                    location34_Communication = MitaObject.GetComponentInChildren<Location34_Communication>();


//                    if (location34_Communication == null) location34_Communication = GameObject.Instantiate(Loc34_Template, MitaObject.transform).GetComponent<Location34_Communication>();

//                    location34_Communication.gameObject.GetComponentInChildren<CapsuleCollider>().transform.localScale = new Vector3(0.01f, 0.01f, 0.01f);
//                }
//                catch (Exception ex)
//                {

//                    MelonLogger.Error($"Location34_Communication set error: {ex}");
//                }


//                try
//                {
//                    location34_Communication.play = true;
//                    location34_Communication.mitaAnimator = MitaPersonObject.GetComponent<Animator_FunctionsOverride>();
//                    location34_Communication.mita = Mita;

//                    MitaAnimationModded.location34_Communication = location34_Communication;
//                    MitaAnimationModded.location34_Communication.mita = Mita;
//                    MitaAnimationModded.location34_Communication.mitaCanWalk = true;
//                }
//                catch (Exception ex)
//                {

//                    MelonLogger.Error($"Loc setting set error: {ex}");
//                }


//                Settings.MitaType.Value = character;
//                Settings.Save();
//                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");

//                if (!changeAnimation) MelonCoroutines.Start(walkingFix());


//                MitaAnimationModded.init(MitaAnimatorFunctions, location34_Communication, ChangeAnimationControler, changeAnimation);






//                if (!changeAnimation) MitaAnimationModded.resetToIdleAnimation();

//                MitaClothesModded.init_hair();
//                MelonLogger.Msg($"AnimContr Status name {animator.runtimeAnimatorController.name}  count {animator.runtimeAnimatorController.animationClips.Length} ");




//                Rigidbody rigidbody = MitaPersonObject.GetComponent<Rigidbody>();
//                if (rigidbody == null)
//                {
//                    rigidbody = MitaPersonObject.AddComponent<Rigidbody>();
//                    rigidbody.freezeRotation = true;
//                    rigidbody.useGravity = false;
//                    rigidbody.centerOfMass = new Vector3(0, 0.65f, 0);
//                    rigidbody.mass = 2f;
//                    rigidbody.maxAngularVelocity = 0.3f; //0.3 как и было
//                    rigidbody.maxDepenetrationVelocity = 7f;//0.3f; //было до этого = 0.9f когда пробовал влад;
//                    rigidbody.drag = 15;
//                    rigidbody.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic; //ContinuousDynamic вместо Continuous для обработки динамических обьектов
//                    rigidbody.interpolation = RigidbodyInterpolation.Interpolate;
//                }
//;

//            }
//            catch (Exception ex)
//            {

//                MelonLogger.Error("Mita change: ", ex);
//            }

//            MelonLogger.Msg("Change Mita Final");
//        }
//    }
//}
