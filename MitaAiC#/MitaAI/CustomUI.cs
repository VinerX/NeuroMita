using Il2Cpp;
using MelonLoader;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine.Events;
using UnityEngine;
using UnityEngine.Playables;
using Microsoft.VisualBasic;
using UnityEngine.UI;
using MitaAI.PlayerControls;
using MitaAI;

namespace MitaAI
{
    public class CustomUI
    {
        public static CustomUI Instance;
        private Dictionary<character, bool> characterStates = new Dictionary<character, bool>();
        private bool isManualControl = false;
        private const int menuWidth = 400;
        private const int menuHeight = 600;
        private const int padding = 10;
        private const int buttonHeight = 30;

        public CustomUI()
        {
            Instance = this;
            foreach (character character in Enum.GetValues(typeof(character)))
            {
                characterStates[character] = false;
            }
        }
        public void StartCustomUI()
        {
            MelonEvents.OnGUI.Subscribe(OnDrawMenu, 100);
            MelonLogger.Msg("Custom UI Инициализировано.");
        }

        private bool isMenuVisible = false;
        private bool isCrazyMode = false;
        private Rect crazyToggleRect = new Rect(10, 30, 200, 20);

        private void OnDrawMenu()
        {
            if (!isMenuVisible) 
            {
                return;
            }

            GUI.Box(new Rect(0, 0, menuWidth, menuHeight), "Mita AI Settings");

            Event currentEvent = Event.current;
            if (currentEvent.type == EventType.MouseDown && currentEvent.button == 0)
            {
                Vector2 mousePosition = new Vector2(currentEvent.mousePosition.x, currentEvent.mousePosition.y);

                int yOffset = 30;
                yOffset = ProcessCharacterToggle("Безумная", character.Crazy, yOffset, mousePosition);
                yOffset = ProcessCharacterToggle("Добрая", character.Kind, yOffset, mousePosition);
                yOffset = ProcessCharacterToggle("Коротковолосая", character.ShortHair, yOffset, mousePosition);
                yOffset = ProcessCharacterToggle("Кепка", character.Cappy, yOffset, mousePosition);
            }

            int drawYOffset = 30;
            drawYOffset = DrawToggle("Безумная", character.Crazy, drawYOffset);
            drawYOffset = DrawToggle("Добрая", character.Kind, drawYOffset);
            drawYOffset = DrawToggle("Коротковолосая", character.ShortHair, drawYOffset);
            drawYOffset = DrawToggle("Кепка", character.Cappy, drawYOffset);
        }

        private int ProcessCharacterToggle(string label, character character, int yOffset, Vector2 mousePosition)
        {
            Rect toggleRect = new Rect(padding, yOffset, 200, buttonHeight);
            if (toggleRect.Contains(mousePosition))
            {
                MelonLogger.Msg($"Toggle clicked: {label}");
                
                isManualControl = true;
                
                bool newState = !characterStates[character];
                characterStates[character] = newState;
                
                GameObject mitaObject = MitaCore.getMitaByEnum(character);
                if (mitaObject == null)
                {
                    MelonLogger.Error($"Failed to find character object for {character}");
                    return yOffset + buttonHeight + padding;
                }

                try
                {
                    if (newState)
                    {
                        if (character == character.Crazy)
                        {
                            MelonLogger.Msg($"Attempting to activate {label} character");
                            GameObject crazyChar = MitaCore.getMitaByEnum(character.Crazy);
                            if (crazyChar != null)
                            {
                                MelonLogger.Msg($"Found Crazy character object: {crazyChar.name}");
                                MitaCore.Instance?.addChangeMita(crazyChar, character.Crazy, true, false);
                                crazyChar.SetActive(true);
                                MelonLogger.Msg($"{label} activation complete");
                            }
                            else
                            {
                                MelonLogger.Error($"Crazy character object not found");
                            }
                        }
                        else
                        {
                            MitaCore.Instance?.addChangeMita(mitaObject, character, true, false);
                            MitaCore.Instance?.sendSystemMessage($"{label} активирована", character);
                            MitaCore.Instance?.sendInfoListeners($"{label} появилась на уровне", null, character, "Nobody");
                            MelonLogger.Msg($"{label} successfully activated");
                        }
                    }
                    else
                    {
                        MitaCore.Instance?.setCharacterState(character, character.None);
                        MitaCore.Instance?.removeMita(mitaObject, character);
                        MitaCore.Instance?.sendSystemMessage($"{label} полностью деактивирована", character);
                        MitaCore.Instance?.sendInfoListeners($"{label} удалена с уровня", null, character, "Nobody");
                        MelonLogger.Msg($"{label} fully deactivated");
                    }
                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error handling {label} toggle: {ex}");
                }
                
                MelonCoroutines.Start(DisableManualControl());
            }
            return yOffset + buttonHeight + padding;
        }

        private int DrawToggle(string label, character character, int yOffset)
        {
            bool state = characterStates[character];
            bool newState = GUI.Toggle(new Rect(padding, yOffset, 200, buttonHeight), state, label);
            if (newState != state)
            {
                MelonLogger.Msg($"Toggle {label} state changed to {newState}");
                characterStates[character] = newState;
                ProcessCharacterToggle(label, character, yOffset, Event.current.mousePosition);
            }
            return yOffset + buttonHeight + padding;
        }

        private System.Collections.IEnumerator DisableManualControl()
        {
            yield return new WaitForSeconds(3f);
            isManualControl = false;
        }

        public void SetMenuVisible(bool visible)
        {
            isMenuVisible = visible;
            
            if (visible)
            {
                MelonLogger.Msg("CustomMenu Активировано");
            }
            else
            {
                MelonLogger.Msg("CustomMenu Деактивировано");
            }
        }
    }
}
