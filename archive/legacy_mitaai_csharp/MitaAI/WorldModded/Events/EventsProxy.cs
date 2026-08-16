using MelonLoader;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.NetworkInformation;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Events;
using Il2Cpp;

namespace MitaAI
{

    [RegisterTypeInIl2Cpp]
    public class EventsProxy : MonoBehaviour
    {



        // Функция, которая будет вызываться через AnimationEvent
        // В этом же классе (или на GameObject с анимацией):
        public void OnAnimationEvent(string eventName)
        {
            MelonLogger.Msg($"Animation event triggered: {eventName}");
            EventsModded.HandleAnimationEvent(eventName); // Передаём только имя
        }

        private void OnEventTriggered()
        {
            MelonLogger.Msg($"UnityEvent triggered! Event Name: {_eventName}");

            // Здесь можно вызвать функции основного класса
            EventsModded.HandleCustomEvent(_eventName);
        }



        public static void AddAnimationEvent(GameObject targetObject, AnimationClip animationClip, string Name)
        {
            MelonLogger.Msg("AddAnimationEvent start");
            // Добавляем прокси-компонент к объекту

            EventsProxy proxy = targetObject.GetComponent<EventsProxy>();
            if (proxy == null) proxy =  targetObject.AddComponent<EventsProxy>();

            MelonLogger.Msg("AddAnimationEvent added proxi");
            // Создаем AnimationEvent
            var animationEvent = new UnityEngine.AnimationEvent
            {
                functionName = "OnAnimationEvent", // Имя функции в прокси-классе
                //time = 0.05f, // Время срабатывания
                stringParameter = Name,
                //intParameter = 123,
                //floatParameter = 1.0f,
                //objectReferenceParameter = null
            };
            MelonLogger.Msg("AddAnimationEvent created anim event+"+ animationClip.name);
            animationClip.AddEvent(animationEvent);
            MelonLogger.Msg("AddAnimationEvent added anim event");
        }
        public static UnityEvent ChangeAnimationEvent(GameObject targetObject, string name)
        {
            if (targetObject == null)
            {
                MelonLogger.Msg("targetObject is null!");
                return null;
            }

            MelonLogger.Msg("ChangeAnimationEvent start");

            // Создаем UnityEvent
            var unityEvent = new UnityEvent();

            // Добавляем прокси-компонент к объекту
            var proxy = targetObject.AddComponent<EventsProxy>();
            if (proxy == null)
            {
                MelonLogger.Msg("Failed to add AnimationEventProxy!");
                return null;
            }

            // Настраиваем прокси для вызова функции основного класса
            proxy.SetupEvent(unityEvent, name);

            MelonLogger.Msg("ChangeAnimationEvent return UnityEvent");

            return unityEvent;
        }

        private UnityEvent _unityEvent;
        private string _eventName;

        // Настройка события
        public void SetupEvent(UnityEvent unityEvent, string eventName)
        {

            _unityEvent = unityEvent;
            _eventName = eventName;

            // Создаем делегат UnityAction и подписываемся на событие
            _unityEvent.AddListener((UnityAction)OnEventTriggered);
        }
        public UnityEvent SetupEvent(string eventName)
        {

            _unityEvent = new UnityEvent();
            _eventName = eventName;

            // Создаем делегат UnityAction и подписываемся на событие
            _unityEvent.AddListener((UnityAction)OnEventTriggered);

            return _unityEvent;
        }


        // Метод, который будет вызван при срабатывании UnityEvent

    }

}
