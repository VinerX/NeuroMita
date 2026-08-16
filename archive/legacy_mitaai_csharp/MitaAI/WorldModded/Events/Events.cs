using Il2Cpp;
using MelonLoader;
using System;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using System.Collections;
using MitaAI.Mita;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine.Events;

namespace MitaAI
{
    public class FloatEvent : UnityEvent<float> { } //empty class; just needs to exist
    public class BoolEvent : UnityEvent<bool> { } //empty class; just needs to exist

    public static class EventsModded
    {

        static bool DisableEvents = false;

        static float lastEventTime = 0f;
        static float timeBeetweenEvents = 40f;



        // Фиксирует, что что-то произошло, чтобы ивенты не наслаивались
        public static void registerLastEvent()
        {
            lastEventTime = Time.unscaledTime;
        }


        public static void HandleAnimationEvent(string eventName)
        {
            switch (eventName)
            {
                case "TakePlayer":
                    MelonCoroutines.Start(playerTaken());
                    break;
                case "Mita Kick":
                    MelonCoroutines.Start(MitaKickEnd());
                    break;
                case "Mita Click":
                    AudioControl.playFingerClick();
                    break;
            }
            //MelonLogger.Msg($"AnimationEvent triggered! Time: {evt.time}, String: {evt.stringParameter}, Int: {evt.intParameter}, Float: {evt.floatParameter}");
        }
        static IEnumerator playerTaken()
        {
            MelonLogger.Msg("Player taken!");
            PlayerAnimationModded.currentPlayerMovement = PlayerMovementType.taken;
            PlayerAnimationModded.playerMove.dontMove = true;
            MitaCore.Instance.playerObject.GetComponent<Rigidbody>().useGravity = false;
            MitaCore.Instance.playerObject.transform.SetParent(MitaCore.Instance.Mita.boneRightItem.transform, true);


            while (PlayerAnimationModded.currentPlayerMovement == PlayerMovementType.taken)
            {
                float playerSize = MitaCore.Instance.playerObject.transform.localScale.x;
                MitaCore.Instance.playerObject.transform.localPosition = new UnityEngine.Vector3(-0.7f, -1.2f, -0.7f) * playerSize; //-0,7 -1,2 -0,7
                yield return null;
            }
            MitaCore.Instance.playerObject.GetComponent<Rigidbody>().useGravity = true;
            PlayerAnimationModded.playerMove.dontMove = false;
            MitaCore.Instance.playerObject.transform.SetParent(MitaCore.Instance.playerControllerObject.transform);
            MelonLogger.Msg("Player throwned!");
            MitaAnimationModded.getMitaAnimationModded(MitaCore.Instance.currentCharacter).resetToIdleAnimation();
        }
        static IEnumerator MitaKickEnd()
        {
            MelonCoroutines.Start(PlayerEffectsModded.AddRemoveBloodEffect(5));
            yield return new WaitForSeconds(1.5667f);

            MitaAnimationModded.bat.active = false;
        }

        public static void HandleCustomEvent(string eventName)
        {
            MelonLogger.Msg($"HandleCustomEvent called with event: {eventName}");

            if (eventName.StartsWith("MENU|"))
            {
                UINeuroMita.MenuEventsCases(eventName);
            }


            switch (eventName)
            {
                case "ConsoleEnd":
                    PlayerAnimationModded.stopAnim();
                    break;
                case "SofaSit":

                    break;

                default:
                    break;
            }
        }


        #region EventsEnter
        // Место, где в теории смогу уловить все, что будет вызывать генерацию реакции миты

        static Dictionary<string, float> eventRepeatBlock = new Dictionary<string, float>();

        static bool TimeBlock(string name, float needed = 8)
        {
            float currentTime = Time.unscaledTime;

            if (currentTime - lastEventTime < timeBeetweenEvents)
            {
                return true;
            }


            // Если ключ существует и время еще не прошло
            if (eventRepeatBlock.TryGetValue(name, out float lastTime) && currentTime - lastTime < needed)
            {
                return true; // Блокируем выполнение
            }

            // Обновляем время последнего вызова
            eventRepeatBlock[name] = currentTime;
            lastEventTime = currentTime;
            return false; // Не блокируем выполнение
        }

        // Если долго на что-то смотрит
        public static void LongWatching(string objectName, float time)
        {
            if (DisableEvents) return;

            if (TimeBlock("LongWatching", 40f)) return;
            MelonLogger.Msg("Event LongWatching");


            CharacterMessages.sendSystem($"Игрок на протяжении {time} секунд смотрел на {objectName}", false);

        }

        #region Position
        // Отошел от Миты
        public static void leaveMita()
        {


        }
        // Отошел от Миты
        public static void enterMita()
        {


        }

        // Зашел в комнату
        public static void roomEnter(Rooms room, Rooms lastRoom)
        {
            if (DisableEvents) return;

            MelonLogger.Msg($"Event roomEnter {room}");

            if (room == Rooms.Unknown) return;

            bool isInfo = TimeBlock("roomEnter", 15f);

            Rooms mitaRoom = MitaCore.Instance.GetRoomID(MitaCore.Instance.MitaPersonObject.transform);
            string message = $"Игрок только что перешел комнаты в {room} из комнаты {lastRoom}, а ты сейчас находишься в комнате {mitaRoom}. " +
                $"Реагируй резко, только если это обоснованно, в общем случае можешь это не заметить или продолжить по теме разговора";

            //if (mitaRoom != room) message += $"";


            CharacterMessages.sendSystem(message, isInfo);

        }


        #endregion

        // Долго ничего не делал
        public static void boringTime()
        {

        }

        // Загрузился
        public static void sceneEnter(characterType character)
        {
            string HelloMessage = "Игрок только что загрузился в твой уровень";

            if (Utils.Random(1, 4)) HelloMessage += ", подбери музыку для его встречи";
            if (Utils.Random(1, 7)) HelloMessage += ", можешь удивить его новым костюмом";
            if (Utils.Random(1, 7)) HelloMessage += ", можешь удивить его новым цветом волос";


            CharacterMessages.sendSystemMessage(HelloMessage, character);
        }

        public static void playerKilled()
        {

            CharacterMessages.sendSystemMessage("Игрок был укушен манекеном. Манекен выключился (его можно перезапустить)");
            //playerPerson.transform.parent.position = GetRandomLoc().position;

            try
            {
                Component effectComponent = PlayerEffectsModded.playerEffectsObject.GetComponentByName("Glitch");
                if (effectComponent is Il2CppObjectBase il2cppComponent)
                {
                    // Если это Il2CppObjectBase
                    MelonLogger.Msg($"Il2Cpp component detected: {il2cppComponent.GetType().Name}");

                    // Проверяем, имеет ли компонент свойство enabled
                    var enabledProperty = il2cppComponent.GetType().GetProperty("enabled");
                    var behaviour = il2cppComponent.TryCast<Behaviour>();
                    behaviour.enabled = true;

                    // Запускаем корутину, передавая Il2Cpp-компонент
                    MelonCoroutines.Start(Utils.HandleIl2CppComponent(il2cppComponent, 5f));

                }


            }
            catch (Exception ex)
            {

                MelonLogger.Error(ex);
            }



        }



        #endregion



    }




    [HarmonyLib.HarmonyPatch]
    public static class Console
    {

    }

    [HarmonyLib.HarmonyPatch(typeof(Mob_Maneken), "StartKillPlayer")]
    public static class Maneken
    {
        private static void Postfix()
        {
            MelonLogger.Msg("TRYING TRYING");
            if (MitaCore.Instance != null)
            {
                MelonLogger.Msg("MitaCore.Instance is NOT  null.))");
                EventsModded.playerKilled(); // Вызов метода playerKilled из экземпляра MitaCore
            }
            else
            {
                MelonLogger.Msg("MitaCore.Instance is null.");
            }
        }
    }

    [HarmonyLib.HarmonyPatch]
    public static class Safe
    {
        [HarmonyLib.HarmonyPatch(typeof(Basement_Safe), "ClickButton", new Type[] { typeof(int) })]
        [HarmonyLib.HarmonyPostfix]
        private static void Postfix()
        {

            MitaCore.Instance?.playerClickSafe();

        }

        [HarmonyLib.HarmonyPatch(typeof(Basement_Safe), "RightPassword")]
        [HarmonyLib.HarmonyPostfix]
        private static void Postfix2()
        {

            CharacterMessages.sendSystemMessage("Игрок открыл сейф");

        }
    }


}
