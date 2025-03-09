using Il2Cpp;
using MelonLoader;
using System;
using System.Collections;
using UnityEngine.UI;
using UnityEngine;


namespace MitaAI.PlayerControls
{
    public static class InputControl
    {
        public static bool isInputBlocked = false; // Флаг для блокировки
        public static bool isInputActive = false; // Флаг для отслеживания активности ввода текста
        public static bool isInputLocked = false; // Флаг для блокировки закрытия поля ввода

        static GameObject InputFieldComponent;
        static InputField inputField; // Ссылка на компонент InputField

        private static bool wasInputActive = false; // Флаг для отслеживания предыдущего состояния ввода
        private static float savedPlayerSpeed = 1f; // Сохранённая скорость персонажа

        public static void UpdateInput(string userInput)
        {
            if (InputFieldComponent == null || inputField == null || string.IsNullOrEmpty(userInput)) return;

            // Сохраняем текущие позиции
            int caretPos = inputField.caretPosition;
            //int selectionAnchor = inputField.selectionAnchorPosition;
            //int selectionFocus = inputField.selectionFocusPosition;

            // Вставляем текст в позицию курсора
            inputField.text = inputField.text.Insert(caretPos, userInput);

            // Обновляем позиции курсора и выделения
            int newCaretPos = caretPos + userInput.Length;
            inputField.caretPosition = newCaretPos;
            //inputField.selectionAnchorPosition = newCaretPos;
            //inputField.selectionFocusPosition = newCaretPos;           
        }

        // Метод для блокировки/разблокировки поля ввода
        public static void BlockInputField(bool blocked)
        {
            isInputBlocked = blocked; // Устанавливаем блокировку
            if (InputFieldComponent != null && wasInputActive)
            {
                InputFieldComponent.SetActive(!blocked); // Отключаем поле ввода, если оно активно
            }
        }

        public static void processInpute()
        {
            if (!MitaCore.isRequiredScene()) return;

            // Обработка блокировки движения при активном вводе
            if (isInputActive != wasInputActive) // Проверяем, изменилось ли состояние ввода
            {
                if (PlayerAnimationModded.playerMove != null)
                {
                    if (isInputActive)
                    {
                        // Сохраняем текущую скорость перед установкой в 0
                        savedPlayerSpeed = PlayerAnimationModded.playerMove.speedPlayer;
                        PlayerAnimationModded.playerMove.speedPlayer = 0f;
                        PlayerAnimationModded.UpdateSpeedAnimation(0f);
                        PlayerAnimationModded.StopPlayerAnimation();
                        PlayerAnimationModded.playerMove.dontMove = true;
                        Animator playerAnimator = PlayerAnimationModded.playerMove.GetComponent<Animator>();
                        if (playerAnimator != null) playerAnimator.SetFloat("Speed", 0f);
                    }
                    else
                    {
                        // Восстанавливаем сохранённую скорость
                        PlayerAnimationModded.playerMove.speedPlayer = savedPlayerSpeed;
                        PlayerAnimationModded.UpdateSpeedAnimation(savedPlayerSpeed);
                        PlayerAnimationModded.playerMove.dontMove = false;
                        Animator playerAnimator = PlayerAnimationModded.playerMove.GetComponent<Animator>();
                        if (playerAnimator != null) playerAnimator.SetFloat("Speed", savedPlayerSpeed);
                        PlayerAnimationModded.currentPlayerMovement = PlayerAnimationModded.PlayerMovement.normal;
                    }
                }
                wasInputActive = isInputActive; // Обновляем флаг предыдущего состояния
            }

            // Обработка нажатия Enter для открытия/закрытия чата и отправки текста
            if (Input.GetKeyDown(KeyCode.Tab) )
            {
                if (!InputFieldExists()) return;


                // Переключаем видимость InputField
                bool isActive = InputFieldComponent != null && InputFieldComponent.activeSelf;
                if (InputFieldComponent != null)
                {
                    InputFieldComponent.SetActive(!isActive);

                    // Если объект стал активным, активируем InputField
                    if (InputFieldComponent.activeSelf)
                    {
                        inputField.Select();
                        inputField.ActivateInputField();
                        isInputActive = true;  // Ввод активен
                        isInputLocked = true;  // Блокируем закрытие поля ввода
                    }
                    else
                    {
                        isInputActive = false;  // Ввод не активен
                        isInputLocked = false; // Разблокируем поле ввода
                    }
                }
            }




            else if (Input.GetKeyDown(KeyCode.Return))
            {
                if (!InputFieldExists()) return;
        

                if (isInputBlocked) return; // Если поле ввода заблокировано, ничего не делаем

                // Если поле ввода активно и текст не пустой, отправляем текст и скрываем поле
                if (isInputActive)
                {

                    if (inputField != null && !string.IsNullOrEmpty(inputField.text)){

                        ProcessInput(inputField.text); // Обрабатываем введенный текст
                        inputField.text = "";
                        InputFieldComponent.SetActive(false);
                        isInputActive = false;  // Ввод завершен, восстанавливаем движение
                        isInputLocked = false; // Разблокируем поле ввода
                    }


                }
                else // Активирую ентером
                {

                    if (InputFieldComponent != null)
                    {
                        if (!InputFieldComponent.active) InputFieldComponent.SetActive(true);
                    }
                        
                    inputField.Select();
                    inputField.ActivateInputField();

                }
               

            }

            // Дополнительная обработка нажатия клавиш
            if (Input.GetKeyDown(KeyCode.C) && !checkInput())
            {
                if (PlayerAnimationModded.playerMove != null)
                {
                    PlayerAnimationModded.playerMove.canSit = true;
                }
            }
            else if (Input.GetKeyUp(KeyCode.C))
            {
                if (PlayerAnimationModded.playerMove != null)
                {
                    PlayerAnimationModded.playerMove.canSit = false;
                }
            }
            else if (Input.GetKeyDown(KeyCode.Space) && !checkInput())
            {
                try
                {
                    MelonLogger.Msg("Space pressed");
                    if (PlayerAnimationModded.playerMove != null)
                    {
                        PlayerAnimationModded.currentPlayerMovement = PlayerAnimationModded.PlayerMovement.normal;
                    }
                }
                catch (Exception e)
                {
                    MelonLogger.Msg(e);
                }
            }
            // unstack 
            else if (Input.GetKeyDown(KeyCode.O) && Input.GetKeyDown(KeyCode.P))
                {
                    try
                    {
                        MelonLogger.Msg("Teleport mita to player");
                        MitaCore.Instance.Mita.MitaTeleport(MitaCore.Instance.playerObject.transform);
                        MitaCore.Instance.Mita.AiShraplyStop();
                    }
                    catch (Exception e)
                    {

                        MelonLogger.Msg(e);
                    }

                }
            // unstack player anim
            else if (Input.GetKeyDown(KeyCode.O) && (Input.GetKeyDown(KeyCode.L)))
            {
                try
                {
                    MelonLogger.Msg("Teleport player to 0 0 0");
                    PlayerAnimationModded.stopAnim();
                    MitaCore.Instance.playerObject.transform.position = Vector3.zero;

                }
                catch (Exception e)
                {

                    MelonLogger.Msg(e);
                }

            }
            else if (Input.GetKeyDown(KeyCode.J) )
            {
                changeMitaButtons();
            }
            else if (Input.GetKeyDown(KeyCode.Insert))
            {
                try
                {
                    // Находим игрока
                    GameObject player = GameObject.Find("GameController/Player");
                    if (player != null)
                    {
                        // Телепортируем на указанные координаты
                        player.transform.position = new Vector3(10.8995f, -2.9825f, -10.6286f);
                        
                        // Деактивируем FixPosition так как в клетку не пустит
                        Transform rightWrist = player.transform.Find("RightWrist FixPosition");
                        if (rightWrist != null)
                        {
                            rightWrist.gameObject.SetActive(false);
                        }
                        
                        Transform leftWrist = player.transform.Find("LeftWrist FixPosition");
                        if (leftWrist != null)
                        {
                            leftWrist.gameObject.SetActive(false);
                        }
                        
                        MelonLogger.Msg("Player teleported and wrist positions deactivated");
                    }
                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error during Insert key handling: {ex}");
                }
            }
            else if (Input.GetKeyDown(KeyCode.Delete))
            {
                try
                {
                    // Находим игрока
                    GameObject player = GameObject.Find("GameController/Player");
                    if (player != null)
                    {
                        // Телепортируем на новые координаты
                        player.transform.position = new Vector3(12.532f, -2.9825f, -10.612f);
                        
                        // Активируем FixPosition
                        Transform rightWrist = player.transform.Find("RightWrist FixPosition");
                        if (rightWrist != null)
                        {
                            rightWrist.gameObject.SetActive(true);
                        }
                        
                        Transform leftWrist = player.transform.Find("LeftWrist FixPosition");
                        if (leftWrist != null)
                        {
                            leftWrist.gameObject.SetActive(true);
                        }
                        
                        MelonLogger.Msg("Player teleported and wrist positions activated");
                    }
                }
                catch (Exception ex)
                {
                    MelonLogger.Error($"Error during Delete key handling: {ex}");
                }
            }

            // Постоянно возвращаем фокус на поле ввода, если оно активно
            if (isInputActive && inputField != null)
            {
                if (!inputField.isFocused)
                {
                    inputField.Select();
                    inputField.ActivateInputField();
                }
            }
        }
        
        static bool InputFieldExists()
        {
            if (InputFieldComponent == null)
            {
                try
                {
                    CreateInputComponent();
                    return true;
                }
                catch (Exception ex)
                {
                    MelonLogger.Msg("CreateInputComponent ex:" + ex);
                    return false; // Прекращаем выполнение, если создание компонента не удалось
                }
            }
            return true;
        }
        
        
        private static DateTime _lastChangeTime = DateTime.MinValue; // Время последнего изменения
        private static readonly TimeSpan _cooldown = TimeSpan.FromSeconds(4); // Задержка в 5 секунд

        static void changeMitaButtons()
        {

            // Проверяем нажатие клавиш
            if (Input.GetKeyDown(KeyCode.I))
            {
                MelonLogger.Msg("Try change to Kind");
                MitaCore.Instance.changeMita(MitaCore.KindObject, MitaCore.character.Kind);
                _lastChangeTime = DateTime.Now; // Обновляем время последнего изменения


                MitaCore.Instance.sendSystemMessage("Тебя только что заменили");

            }
            else if (Input.GetKeyDown(KeyCode.K))
            {
                MelonLogger.Msg("Try change to Cappy");
                MitaCore.Instance.changeMita(MitaCore.CappyObject, MitaCore.character.Cappy);
                _lastChangeTime = DateTime.Now;


                MitaCore.Instance.sendSystemMessage("Тебя только что заменили");

            }
            else if (Input.GetKeyDown(KeyCode.M))
            {
                MelonLogger.Msg("Try change to Crazy");
                MitaCore.Instance.changeMita(MitaCore.CrazyObject, MitaCore.character.Crazy);
                _lastChangeTime = DateTime.Now;


                MitaCore.Instance.sendSystemMessage("Тебя только что заменили");

            }
            else if (Input.GetKeyDown(KeyCode.U))
            {
                MelonLogger.Msg("Try change to ShortHair");
                MitaCore.Instance.changeMita(MitaCore.ShortHairObject, MitaCore.character.ShortHair);
                _lastChangeTime = DateTime.Now;


                MitaCore.Instance.sendSystemMessage("Тебя только что заменили");

            }


        }

        static bool checkInput()
        {
            return InputFieldComponent != null && InputFieldComponent.activeSelf;
        }

        private static void CreateInputComponent()
        {
            // Создаем объект InputField
            InputFieldComponent = new GameObject("InputFieldComponent");

            inputField = InputFieldComponent.AddComponent<InputField>();
            var _interface = GameObject.Find("Interface");
            if (_interface == null)
            {
                MelonLogger.Msg("Interface not found!");
                return;
            }

            InputFieldComponent.transform.parent = _interface.transform;

            var rect = InputFieldComponent.AddComponent<RectTransform>();
            rect.anchoredPosition = Vector2.zero;

            rect.anchorMin = new Vector2(0.5f, 0);
            rect.anchorMax = new Vector2(0.5f, 0);
            rect.pivot = new Vector2(0.5f, 0);

            var image = InputFieldComponent.AddComponent<UnityEngine.UI.Image>();
            Sprite blackSprite = CreateBlackSprite(100, 100);
            image.sprite = blackSprite;

            image.color = new Color(0f, 0f, 0f, 0.7f);
            inputField.image = image;

            var TextLegacy = new GameObject("TextLegacy");
            var textComponent = TextLegacy.AddComponent<Text>();
            TextLegacy.transform.parent = InputFieldComponent.transform;
            var rectText = TextLegacy.GetComponent<RectTransform>();
            rectText.sizeDelta = new Vector2(500, 100);
            rectText.anchoredPosition = Vector2.zero;
            var texts = GameObject.FindObjectsOfType<Text>();

            foreach (var text in texts)
            {
                textComponent.font = text.font;
                textComponent.fontStyle = text.fontStyle;
                textComponent.fontSize = 35;
                if (textComponent.font != null) break;
            }

            inputField.textComponent = TextLegacy.GetComponent<Text>();
            inputField.text = "Введи текст";
            inputField.textComponent.color = Color.yellow;
            inputField.textComponent.alignment = TextAnchor.MiddleCenter;

            RectTransform parentRect = _interface.GetComponent<RectTransform>();
            float parentWidth = parentRect.rect.width;
            rect.sizeDelta = new Vector2(parentWidth * 0.7f, rect.sizeDelta.y);
            rectText.sizeDelta = rect.sizeDelta;
            inputField.Select();
            inputField.ActivateInputField();
        }

        // Пустышка для обработки ввода
        private static void ProcessInput(string inputText)
        {
            MelonLogger.Msg("Input received: " + inputText);
            MelonCoroutines.Start(MitaCore.Instance.PlayerTalk(inputText));
            MitaCore.Instance.playerMessage += $"{inputText}\n";
            MitaCore.Instance.playerMessageCharacter = Characters.ChooseCharacterToAsnwer();
        }

        public static Sprite CreateBlackSprite(int width, int height)
        {
            Texture2D texture = new Texture2D(width, height);
            Color darkColor = new Color(0f, 0f, 0f, 0f);
            for (int x = 0; x < width; x++)
            {
                for (int y = 0; y < height; y++)
                {
                    texture.SetPixel(x, y, darkColor);
                }
            }

            texture.Apply();

            return Sprite.Create(texture, new Rect(0, 0, width, height), new Vector2(0.5f, 0.5f));
        }
    }
}
