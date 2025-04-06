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

namespace MitaAI
{
    public static class UINeuroMita
    {
        static bool InludeNewMita_TEST = true;

        // Добавляем переменную для отслеживания состояния меню паузы
        static bool isPauseMenu = false;

        static GameObject MenuObject;
        static Menu MainMenu;
        static GameObject StartMenuObject;
        static MenuLocation StartMenu;

        static MenuLocation MainMenuLocation;
        static GameObject FrameMenuObject;

        static GameObject NeuroMitaButton;

        public static void init()
        {
            MenuObject = GameObject.Find("MenuGame");
            MainMenu = MenuObject.GetComponent<Menu>();
            FrameMenuObject = MenuObject.transform.Find("Canvas/FrameMenu").gameObject;
            //makeButtonTemplate();

            ButtonNeuroMita();

            MenuNeuroMita();
        }

        // Добавляем метод для проверки состояния меню паузы
        public static void CheckPauseMenu()
        {
            // Запоминаем предыдущее состояние
            bool wasPauseMenu = isPauseMenu;

            // Ищем объект меню паузы
            GameObject pauseMenuObject = GameObject.Find("GameController/Interface/FastMenu(Clone)");
            isPauseMenu = pauseMenuObject != null;

            // Если состояние изменилось, выводим сообщение
            if (wasPauseMenu != isPauseMenu)
            {
                if (CustomUI.Instance != null)
                {
                    CustomUI.Instance.SetMenuVisible(isPauseMenu);
                }
            }
        }

        static void makeButtonTemplate()
        {

        }

        public static void ButtonNeuroMita()
        {
            #region ButtonLoading

            MelonLogger.Msg("Start SceneMenu");
            // Кнопки мода
            GameObject Menu = GameObject.Find("MenuGame/Canvas/FrameMenu/Location Menu").gameObject;
            MainMenuLocation = Menu.GetComponent<MenuLocation>();
            Menu.transform.localPosition = new Vector3(250f, 355f, 0);
            Menu.transform.Find("Text").localPosition = new Vector3(-250, 15, 0);

            NeuroMitaButton = GameObject.Instantiate(Menu.transform.Find("Button Continue").gameObject);
            MainMenuLocation.objects.Add(NeuroMitaButton.GetComponent<RectTransform>());
            NeuroMitaButton.name = "NeuroMitaStartButton";

            NeuroMitaButton.transform.SetParent(GameObject.Find("MenuGame/Canvas/FrameMenu/Location Menu").transform);
            NeuroMitaButton.transform.localPosition = new Vector3(-250, -45, 0);
            NeuroMitaButton.transform.localScale = new Vector3(1, 1, 1);
            NeuroMitaButton.transform.rotation = new Quaternion(0, 0, 0, 0);


            GameObject NeuroMitaButtonText = NeuroMitaButton.transform.Find("Text").gameObject;
            MelonCoroutines.Start(changeName(NeuroMitaButtonText, "ИГРАТЬ С NEUROMITA"));

            UI_Colors uI_Colors = NeuroMitaButton.GetComponent<UI_Colors>();

            // Цвет фона
            uI_Colors.SetColorImage(0, new Color(0.5f, 1f, 0.5f, 0.5f));

            CharacterMessages.sendSystemInfo("Игрок в меню");

            try
            {
                ButtonMouseClick buttonMouseClick = NeuroMitaButton.GetComponent<ButtonMouseClick>();
                buttonMouseClick.eventClick = setupMenuEvent(buttonMouseClick.gameObject, "ButtonLoad");
            }
            catch (Exception e)
            {
                MelonLogger.Error(e);
            }

            #endregion
        }

        private static GameObject makeButton()
        {
            return null;
        }

        public static void MenuNeuroMita()
        {

            StartMenuObject = GameObject.Instantiate(FrameMenuObject.transform.Find("Location MainOptions").gameObject, FrameMenuObject.transform);
            StartMenuObject.active = false;
            StartMenu = StartMenuObject.GetComponent<MenuLocation>();
            MelonLogger.Msg(2);
            try
            {
                MelonCoroutines.Start(changeName(StartMenuObject.transform.Find("Text").gameObject, "Настройки NeuroMita"));

                // Split the text into lines
                string fullText = "Помните, все что пишет ИИ - выдуманно, не выполняйте и не повторяйте действия сказанные им!";
                string[] lines = new string[] { "Помните, все что пишет", "ИИ - выдуманно", "не выполняйте", "и не повторяйте", "действия сказанные", "им!" };
                float yOffset = -20f; // Initial offset

                for (int i = 0; i < lines.Length; i++)
                {
                    GameObject newTextObject = GameObject.Instantiate(StartMenuObject.transform.Find("Text").gameObject, StartMenuObject.transform);
                    newTextObject.name = "TextMod_" + i;
                    newTextObject.transform.localPosition = new Vector3(0, -550 + yOffset, 0); // Adjust position
                    MelonCoroutines.Start(changeName(newTextObject, lines[i]));
                    yOffset -= 35f; // Decrease offset for the next line
                }
            }
            catch (Exception e) { MelonLogger.Error(e); }

            // Button Option Graphics
            // Button Option Game

            try
            {
                GameObject MitaCrazyButton = StartMenuObject.transform.Find("Button Full Clear").gameObject;
                MitaCrazyButton.active = false;
                MitaCrazyButton = GameObject.Instantiate(NeuroMitaButton, MitaCrazyButton.transform.position, MitaCrazyButton.transform.rotation, MitaCrazyButton.transform.parent);
                MitaCrazyButton.name = "MitaCrazyButton";
                MitaCrazyButton.active = true;

                MelonCoroutines.Start(changeName(MitaCrazyButton.transform.Find("Text").gameObject, "Безумная Мита"));
                MitaCrazyButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(MitaCrazyButton, MitaCrazyButton.name);

            }
            catch (Exception e) { MelonLogger.Error(e); }

            try
            {
                GameObject MitaKindButton = StartMenuObject.transform.Find("Button Option Graphics").gameObject;
                MitaKindButton.active = false;
                MitaKindButton = GameObject.Instantiate(NeuroMitaButton, MitaKindButton.transform.position, MitaKindButton.transform.rotation, MitaKindButton.transform.parent);
                MitaKindButton.name = "MitaKindButton";
                MitaKindButton.active = true;

                MelonCoroutines.Start(changeName(MitaKindButton.transform.Find("Text").gameObject, "Добрая Мита"));
                MitaKindButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(MitaKindButton, MitaKindButton.name);

            }
            catch (Exception e) { MelonLogger.Error(e); }

            try
            {
                GameObject MitaShorthairButton = StartMenuObject.transform.Find("Button Option Game").gameObject;
                MitaShorthairButton.active = false;
                MitaShorthairButton = GameObject.Instantiate(NeuroMitaButton, MitaShorthairButton.transform.position, MitaShorthairButton.transform.rotation, MitaShorthairButton.transform.parent);
                MitaShorthairButton.name = "MitaShortButton";
                MitaShorthairButton.active = true;

                MelonCoroutines.Start(changeName(MitaShorthairButton.transform.Find("Text").gameObject, "Коротковолосая Мита"));
                MitaShorthairButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(MitaShorthairButton, MitaShorthairButton.name);

            }
            catch (Exception e) { MelonLogger.Error(e); }

            try
            {
                MelonLogger.Msg("Cappy");
                GameObject MitaCappyButton = StartMenuObject.transform.Find("Button Volume").gameObject;
                MitaCappyButton.active = false;
                MitaCappyButton = GameObject.Instantiate(NeuroMitaButton, MitaCappyButton.transform.position, MitaCappyButton.transform.rotation, MitaCappyButton.transform.parent);
                MitaCappyButton.name = "MitaCappyButton";
                MitaCappyButton.active = true;

                MelonCoroutines.Start(changeName(MitaCappyButton.transform.Find("Text").gameObject, "Кепочка"));
                MitaCappyButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(MitaCappyButton, MitaCappyButton.name);



            }
            catch (Exception e) { MelonLogger.Error(e); }

            if (InludeNewMita_TEST)
            {
                try
                {

                    // Новая кнопка MitaMilaButton
                    GameObject MilaButton = StartMenuObject.transform.Find("Button Volume").gameObject;
                    MilaButton.active = false;
                    MilaButton = GameObject.Instantiate(NeuroMitaButton, MilaButton.transform.position, MilaButton.transform.rotation, MilaButton.transform.parent);
                    MilaButton.name = "MilaButton";
                    MilaButton.active = true;
                    MilaButton.transform.localPosition += new Vector3(0, -55);
                    MelonCoroutines.Start(changeName(MilaButton.transform.Find("Text").gameObject, "Мила (TODO)"));
                    MilaButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(MilaButton, MilaButton.name);
                }
                catch (Exception e) { MelonLogger.Error(e); }


                try
                {
                    // Новая кнопка SleepyMitaButton
                    GameObject SleepyMitaButton = StartMenuObject.transform.Find("Button Volume").gameObject;
                    SleepyMitaButton.active = false;
                    SleepyMitaButton = GameObject.Instantiate(NeuroMitaButton, SleepyMitaButton.transform.position, SleepyMitaButton.transform.rotation, SleepyMitaButton.transform.parent);
                    SleepyMitaButton.name = "SleepyMitaButton";
                    SleepyMitaButton.active = true;
                    SleepyMitaButton.transform.localPosition += new Vector3(0, -110);
                    MelonCoroutines.Start(changeName(SleepyMitaButton.transform.Find("Text").gameObject, "Сонная Мита (TODO 2X)"));
                    SleepyMitaButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(SleepyMitaButton, SleepyMitaButton.name);
                }
                catch (Exception e) { MelonLogger.Error(e); }

                try
                {
                    // Новая кнопка CreepyMitaButton
                    GameObject CreepyMitaButton = StartMenuObject.transform.Find("Button Volume").gameObject;
                    CreepyMitaButton.active = false;
                    CreepyMitaButton = GameObject.Instantiate(NeuroMitaButton, CreepyMitaButton.transform.position, CreepyMitaButton.transform.rotation, CreepyMitaButton.transform.parent);
                    CreepyMitaButton.name = "CreepyMitaButton";
                    CreepyMitaButton.active = true;
                    CreepyMitaButton.transform.localPosition += new Vector3(0, -165);
                    MelonCoroutines.Start(changeName(CreepyMitaButton.transform.Find("Text").gameObject, "Уродливая Мита (TODO X3)"));
                    CreepyMitaButton.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(CreepyMitaButton, CreepyMitaButton.name);
                }
                catch (Exception e) { MelonLogger.Error(e); }

            }


            Il2CppSystem.Collections.Generic.List<RectTransform> list = new Il2CppSystem.Collections.Generic.List<RectTransform>();
            for (int i = 0; i < StartMenuObject.transform.childCount; i++)
            {
                try
                {
                    list.Add(StartMenuObject.transform.GetChild(i).GetComponent<RectTransform>());
                }
                catch { }

            }
            StartMenu.objects = list;

            GameObject Back = StartMenuObject.transform.Find("Button Back").gameObject;
            Back.name = "ButtonReturn";
            Back.transform.localPosition += new Vector3(0, -165);
            Back.GetComponent<ButtonMouseClick>().eventClick = setupMenuEvent(Back, Back.name);

        }

        static void ReplaceButtonWithInputField(GameObject buttonToReplace, string inputFieldName, Vector3 positionOffset)
        {
            try
            {
                // Деактивируем кнопку
                buttonToReplace.SetActive(false);

                // Создаем новый InputField
                GameObject inputFieldObject = new GameObject(inputFieldName);
                inputFieldObject.transform.SetParent(buttonToReplace.transform.parent);
                inputFieldObject.transform.position = buttonToReplace.transform.position;
                inputFieldObject.transform.rotation = buttonToReplace.transform.rotation;
                inputFieldObject.transform.localPosition += positionOffset;

                // Добавляем компонент InputField
                InputField inputField = inputFieldObject.AddComponent<InputField>();

                // Создаем Text для отображения текста в InputField
                GameObject textObject = new GameObject("Text");
                textObject.transform.SetParent(inputFieldObject.transform);
                Text textComponent = textObject.AddComponent<Text>();
                textComponent.text = "Введите текст...";
                textComponent.font = Resources.GetBuiltinResource<Font>("Arial.ttf");
                textComponent.color = Color.black;
                textComponent.alignment = TextAnchor.MiddleLeft;

                // Настраиваем RectTransform для Text
                RectTransform textRectTransform = textObject.GetComponent<RectTransform>();
                textRectTransform.anchorMin = Vector2.zero;
                textRectTransform.anchorMax = Vector2.one;
                textRectTransform.offsetMin = new Vector2(10, 0);
                textRectTransform.offsetMax = new Vector2(-10, 0);

                // Настраиваем InputField
                inputField.textComponent = textComponent;
                inputField.placeholder = textComponent; // Можно создать отдельный Text для placeholder, если нужно

                // Настраиваем RectTransform для InputField
                RectTransform inputFieldRectTransform = inputFieldObject.GetComponent<RectTransform>();
                inputFieldRectTransform.sizeDelta = new Vector2(160, 30); // Размер поля ввода

                // Настраиваем событие, если нужно
                //inputField.onValueChanged.AddListener((UnityAction)OnEventTriggered));
            }
            catch (Exception e)
            {
                MelonLogger.Error(e);
            }
        }



        static public void MenuEventsCases(string eventName)
        {
            MelonLogger.Msg($"MenuEventsCases: {eventName}");

            eventName = eventName.Substring(MenuPrefix.Length);
            switch (eventName)
            {
                case "ButtonLoad":
                    StartMenu.Active(true);
                    //MitaCore.MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "MitaShortButton":
                    Settings.MitaType.Value = character.ShortHair;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "MitaCrazyButton":
                    Settings.MitaType.Value = character.Crazy;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "MitaKindButton":
                    Settings.MitaType.Value = character.Kind;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "MitaCappyButton":
                    Settings.MitaType.Value = character.Cappy;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "MilaButton":
                    Settings.MitaType.Value = character.Mila;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "ButtonReturn":
                    StartMenu.Active(false);
                    MainMenuLocation.Active(true);
                    break;
                case "SleepyMitaButton":
                    Settings.MitaType.Value = character.Sleepy;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                case "CreepyMitaButton":
                    Settings.MitaType.Value = character.Creepy;
                    Settings.Save();
                    StartMenu.Active(false);
                    MainMenu.ButtonLoadScene(MitaCore.Instance.requiredSave);
                    break;
                default:
                    MelonLogger.Warning($"Unhandled button {eventName}");
                    break;
            }
        }

        static IEnumerator changeName(GameObject NeuroMitaButtonText, string text)
        {
            /* Я хз когда там локализация подгружается, которая все ломает. Если отследим момент, то можно будет сделать лучше
             
            */

            Font original_font = NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().font;
            NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().text = text;
            NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().m_Text = text;

            float time = 0f;
            while (NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().font == original_font)
            {
                if (MitaCore.isRequiredScene())
                {
                    break;
                }
                NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().text = text;
                NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().m_Text = text;
                time += Time.unscaledDeltaTime;
                yield return null;
            }
            NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().text = text;
            NeuroMitaButtonText.GetComponent<UnityEngine.UI.Text>().m_Text = text;
        }

        public static string MenuPrefix = "MENU|";

        static private UnityEvent setupMenuEvent(GameObject gameObject, string eventName)
        {
            EventsProxy eventsProxy = gameObject.GetComponent<EventsProxy>();
            if (eventsProxy == null)
            {
                eventsProxy = gameObject.AddComponent<EventsProxy>();
            }

            return eventsProxy.SetupEvent($"{MenuPrefix}{eventName}");
        }
    }
}
