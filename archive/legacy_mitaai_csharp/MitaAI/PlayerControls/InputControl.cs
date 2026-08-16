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


        public static bool instantSend = false;
        private static float lastSendTime = 0f;
        private static float timeBeforeInstantSend = 8f;
        

        public static void UpdateInput(string userInput)
        {
            if (InputFieldComponent == null || inputField == null || string.IsNullOrEmpty(userInput)) return;

            // Сохраняем текущие позиции
            int caretPos = inputField.caretPosition;

            // Вставляем текст в позицию курсора
            inputField.text = inputField.text.Insert(caretPos, userInput);
            lastSendTime = Time.unscaledTime;
            InputFieldComponent.SetActive(true);
            // Обновляем позиции курсора и выделения
            int newCaretPos = caretPos + userInput.Length;
            inputField.caretPosition = newCaretPos;
            


        }

        // Метод для блокировки/разблокировки поля ввода
        public static void BlockInputField(bool blocked)
        {
            isInputBlocked = blocked; // Устанавливаем блокировку
           // if (InputFieldComponent != null && wasInputActive)
            //{
              //  InputFieldComponent.SetActive(!blocked); // Отключаем поле ввода, если оно активно
           // }
        }

        public static void processInpute()
        {
            if (!MitaCore.isRequiredScene()) return;


            if (!InputFieldExists()) return;

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
                        PlayerAnimationModded.currentPlayerMovement = PlayerMovementType.normal;
                    }
                }
                wasInputActive = isInputActive; // Обновляем флаг предыдущего состояния
            }

            // Обработка нажатия Enter для открытия/закрытия чата и отправки текста
            if (Input.GetKeyDown(KeyCode.Tab) )
            {
                


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
                
        

                if (isInputBlocked) return; // Если поле ввода заблокировано, ничего не делаем

                // Если поле ввода активно и текст не пустой, отправляем текст и скрываем поле
                if (isInputActive)
                {

                    if (inputField != null && !string.IsNullOrEmpty(inputField.text)){

                        sendMessagePlayer();
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

            // Автоотправка через сколько-то секунд
            if (instantSend)
            {

                if (Time.unscaledTime - lastSendTime > timeBeforeInstantSend )
                {
                    

                    sendMessagePlayer();
                    lastSendTime = Time.unscaledTime;
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
                    if (PlayerAnimationModded.playerMove != null && Hints.exitButton.active)
                    {
                        PlayerAnimationModded.currentPlayerMovement = PlayerMovementType.normal;
                        PlayerAnimationModded.stopAnim();
                        CommonInteractableObject.endLastPlayersCIAs();
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
                        
                        MitaCore.Instance.Mita.AiShraplyStop();
                        ObjectAnimationMita.freeAOM(MitaCore.Instance.currentCharacter);
                        MitaCore.Instance.Mita.magnetTarget = null;
                        MitaCore.Instance.Mita.MitaTeleport(MitaCore.Instance.playerObject.transform);
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

                    PlayerAnimationModded.UnstackPlayer();


                }
                catch (Exception e)
                {

                    MelonLogger.Msg(e);
                }

            }
            //else if (Input.GetKeyDown(KeyCode.J) )
            //{
              //  ChangeMitaButtons();
            //}


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
        private static readonly TimeSpan _cooldown = TimeSpan.FromSeconds(2f); // Задержка в 5 секунд

        static void ChangeMitaButtons()
        {
            // Если ctlr не зажата - выходим
            if (!Input.GetKey(KeyCode.LeftControl))
                return;

            if (DateTime.Now - _lastChangeTime < _cooldown)
                return;

            MelonLogger.Msg("Try change to Mita");

            bool dontrTurnOfOld = Input.GetKeyDown(KeyCode.LeftShift);

            // Словарь для хранения соответствия клавиш и параметров изменения
            var keyActions = new Dictionary<KeyCode, (GameObject MitaObject, characterType Character)>
            {
                { KeyCode.I, (MitaCore.KindObject, characterType.Kind) },
                { KeyCode.K, (MitaCore.CappyObject, characterType.Cappy) },
                { KeyCode.M, (MitaCore.CrazyObject, characterType.Crazy) },
                { KeyCode.U, (MitaCore.ShortHairObject, characterType.ShortHair) },
                { KeyCode.H, (MitaCore.MilaObject, characterType.Mila) },
                { KeyCode.N, (MitaCore.SleepyObject, characterType.Sleepy) },
                { KeyCode.B, (MitaCore.CreepyObject, characterType.Creepy) }
            };

            // Проверяем нажатие клавиш
            foreach (var keyAction in keyActions)
            {
                if (Input.GetKeyDown(keyAction.Key) )
                {
                    MelonLogger.Msg($"INPUT CONTROL: Try change to {keyAction.Value.Character}");
                    MitaCore.Instance.addChangeMita(keyAction.Value.MitaObject, keyAction.Value.Character,true,dontrTurnOfOld);
                    _lastChangeTime = DateTime.Now; // Обновляем время последнего изменения
                    CharacterControl.resetOrders(true);
                    CharacterMessages.sendSystemMessage("Ты только что прогрузилась на уровень.", keyAction.Value.Character);
                    CharacterMessages.sendInfoListeners($"{keyAction.Value.Character} только что прогрузилась на уровень",null, keyAction.Value.Character,"Nobody");
                    break; // Выходим из цикла после первого совпадения
                    
                }
            }
        }

        static bool checkInput()
        {
            return InputFieldComponent != null && InputFieldComponent.activeSelf;
        }

        private static void CreateInputComponent()
        {
            // Создаем объект InputField

            var _interface = GameObject.Find("Interface");
            if (_interface == null)
            {
                MelonLogger.Msg("Interface not found!");
                return;
            }
            InputFieldComponent = new GameObject("InputFieldComponent");
            inputField = InputFieldComponent.AddComponent<InputField>();
            InputFieldComponent.transform.parent = _interface.transform;

            var rect = InputFieldComponent.AddComponent<RectTransform>();
            rect.anchoredPosition = Vector2.zero;

            rect.anchorMin = new Vector2(0.5f, 0);
            rect.anchorMax = new Vector2(0.5f, 0);
            rect.pivot = new Vector2(0.5f, 0);

            var image = InputFieldComponent.AddComponent<UnityEngine.UI.Image>();
            //Sprite blackSprite = CreateBlackSprite(100, 100);
            try
            {
                
                var gamecontrolle = GameObject.Find("GameController").transform;
                MelonLogger.Msg(1);
                var SubtitlesFrame = gamecontrolle.Find("Interface/SubtitlesFrame");
                MelonLogger.Msg(2);
                var sprite =SubtitlesFrame.GetComponent<Image>().sprite;
                MelonLogger.Msg(3);
                image.sprite = sprite;
                
                image.color = new Color(0f, 0f, 0f, 0.7f);
            }
            catch (Exception)
            {
                image.color = new Color(0f, 0f, 0f, 0.3f);
            }


            
            inputField.image = image;
            inputField.onValueChanged.AddListener(new Action<string>(OnInputValueChanged));
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
            inputField.text = loc._("Введи текст","Enter text");
            inputField.textComponent.color = Color.yellow;
            inputField.textComponent.alignment = TextAnchor.MiddleCenter;

            RectTransform parentRect = _interface.GetComponent<RectTransform>();
            float parentWidth = parentRect.rect.width;
            rect.sizeDelta = new Vector2(parentWidth * 0.7f, rect.sizeDelta.y);
            rectText.sizeDelta = rect.sizeDelta;
            inputField.Select();
            inputField.ActivateInputField();


            
            // Меню действий игрока
            var radMenu = new GameObject("RadialMenu").AddComponent<RadialMenu>();
            radMenu.transform.SetParent(MitaCore.Instance.playerController.transform.Find("Interface"));
            radMenu.radialCanvas = MitaCore.Instance.playerController.GetComponentInChildren<Canvas>();
            radMenu.transform.localPosition = Vector3.zero;

            

        }


        public static void sendMessagePlayer()
        {

            ProcessInput(inputField.text); // Обрабатываем введенный текст
            inputField.text = "";
            InputFieldComponent.SetActive(false);
            isInputActive = false;  // Ввод завершен, восстанавливаем движение
            isInputLocked = false; // Разблокируем поле ввода
        }

        // Пустышка для обработки ввода
        private static void ProcessInput(string inputText)
        {
            if (string.IsNullOrEmpty(inputText)) return;

            EventsModded.registerLastEvent();
            MelonLogger.Msg("Input received: " + inputText);
            MelonCoroutines.Start(DialogueControl.PlayerTalk(inputText));
            MitaCore.Instance.playerMessage += $"{inputText}\n";

            //MitaCore.playerMessages.Enqueue(inputText);

            


        }
        // В методе CreateInputComponent после создания InputField добавьте:
        private static void OnInputValueChanged(string text)
        {
            // Вызывается при каждом изменении текста
            lastSendTime = Time.unscaledTime; // Обновляем таймер для instantSend
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
