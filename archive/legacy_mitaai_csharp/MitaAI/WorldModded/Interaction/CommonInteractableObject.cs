
using Il2Cpp;
using MelonLoader;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Events;

namespace MitaAI
{
    [RegisterTypeInIl2Cpp]
    public class CommonInteractableObject : MonoBehaviour
    {
        /*
         *  Компонента для отслеживания, занято место кем-то или нет 
         *  А также логике на выходе из интеракции
         */

        public Dictionary<string,characterType> taker = new Dictionary<string, characterType> { {"center",characterType.None } };        
        public UnityEvent eventEnd = new UnityEvent();


        static List<(CommonInteractableObject,string)> lastPlayerCIAs = new List<(CommonInteractableObject, string)>();

        public static void addCIA(CommonInteractableObject CIA,string position = "center")
        {
            MelonLogger.Msg($"AddCia { CIA.gameObject.name}");
            lastPlayerCIAs.Add( (CIA,position) );
        }

        public static void endLastPlayersCIAs()
        {
            try
            {
                foreach (var item in lastPlayerCIAs)
                {
                    if (item.Item1 == null) continue;

                    if (item.Item1.gameObject == null) continue;
                    MelonLogger.Msg($"freee {item.Item1.gameObject.name}");
                    item.Item1.free(item.Item2);
                }
            }
            catch (Exception Ex)
            {

                MelonLogger.Error(Ex);
            }

            lastPlayerCIAs.Clear();
        }

        public static CommonInteractableObject CheckCreate(GameObject gameObject,string position="center",UnityAction freeCase = null)
        {
            var CIO = gameObject.GetComponent<CommonInteractableObject>();
            if (CIO  == null)
            {
                CIO = gameObject.AddComponent<CommonInteractableObject>();
                
            }
            CIO.setTaken(characterType.None, position);
            
            if (freeCase != null)
            {
                CIO.eventEnd.AddListener(freeCase);
            }

            return CIO;

        }

        public bool isTaken(string position = "center")
        {

            if (taker.ContainsKey(position)) {
                taker[position.ToLower()] = characterType.None; 
            }

            return taker[position.ToLower()] != characterType.None;


        }
        public void setTakenPlayer()
        {
            setTaken(characterType.Player, "center");
        }
        public void setTakenPlayerRight()
        {
            setTaken(characterType.Player, "right");
        }
        public void setTakenPlayerLeft()
        {
            setTaken(characterType.Player, "left");
        }


        public void setTaken(characterType character = characterType.Player,string position = "center")
        {
            MelonLogger.Msg($"Set Taken CIA {gameObject.name} by {character}");

            taker[position.ToLower()] = character;

            if (character == characterType.Player)
            {
                endLastPlayersCIAs();
                addCIA(this);
            }

            var obj = GetComponentsInChildren<ObjectInteractive>();
            foreach (var objectInteractive in obj)
            {
                MelonLogger.Msg($"Deactivate {objectInteractive.name}");
                if (objectInteractive.name.ToLower().Contains(position)) objectInteractive.active = false;
            }



        }


        public void free(string position = "center")
        {
            MelonLogger.Msg($"Free CIO {this.gameObject.name} from {taker[position]}");

            taker[position] = characterType.None;

            var obj = GetComponents<ObjectInteractive>();
            foreach (var objectInteractive in obj)
            {
                MelonLogger.Msg($"Acivate {objectInteractive.name}");
                if (objectInteractive.name.ToLower().Contains(position)) objectInteractive.active = true;
            }


            if (eventEnd == null) return;

            try
            { 
                eventEnd.Invoke();
            }
            catch (Exception ex)
            { 
                MelonLogger.Error(ex);
            }
            
        }


        #region

        /// <summary>
        /// Настраивает анимацию сидения на объекте (например, диване)
        /// </summary>
        /// <param name="targetObject">Целевой объект, к которому добавляется анимация</param>
        /// <param name="animationName">Имя анимации (по умолчанию "AnimationPlayer Sit")</param>
        /// <param name="side">Сторона ("left", "right" и т.д.)</param>
        /// <param name="rotation">Локальный поворот (Euler angles)</param>
        /// <param name="position">Локальная позиция</param>
        /// <param name="interactionText">Текст подсказки при взаимодействии</param>
        /// <param name="interactionDistance">Дистанция взаимодействия</param>
        /// <param name="useParent">Использовать родительский объект для взаимодействия</param>
        public static void TestSetupAnimation(
            GameObject targetObject,
            string animationName = "AnimationPlayer Sit",
            string side = "center",
            Vector3? rotation = null,
            Vector3? position = null,
            string interactionText = "Сесть",
            float interactionDistance = 2f,
            bool useParent = true)
            {

            if (string.IsNullOrEmpty(animationName)) animationName = "AnimationPlayer Sit";

            var animationPlayer = PlayerAnimationModded.CopyObjectAmimationPlayerTo(
                    targetObject.transform,
                    animationName,
                    side);

                if (animationPlayer != null)
                {
                    // Устанавливаем поворот и позицию (значения по умолчанию, если не заданы)
                    animationPlayer.transform.localEulerAngles = rotation ?? new Vector3(90, 0, 0);
                    animationPlayer.transform.localPosition = position ?? new Vector3(0.8f, 1.4f, 0);

                    // Создаем интерактивный объект
                    var interactable = Interactions.FindOrCreateObjectInteractable(
                        animationPlayer.gameObject,
                        false,
                        interactionDistance,
                        interactionText,
                        false,
                        useParent: useParent);

                    // Назначаем анимацию по клику
                    interactable.eventClick.AddListener((UnityAction)animationPlayer.AnimationPlay);

                    interactable.Click();
                }
                else
                {
                    MelonLogger.Error($"Failed to create: {targetObject.name}");
                }
        }

    #endregion

}
}
