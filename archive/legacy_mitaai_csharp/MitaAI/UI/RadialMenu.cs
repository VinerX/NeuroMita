using MelonLoader;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;


namespace MitaAI
{

    [RegisterTypeInIl2Cpp]
    public class RadialMenu : MonoBehaviour
    {
        public static bool isAllowed = false;

        public Canvas radialCanvas;
        public GameObject itemPrefab;
        public float radius = 250f;
        public float selectionThreshold = 200f; // Макс. расстояние для выбора


        // Название функций барть из DontDestroyOnLoad ObjectAnimationContainer
        // Описание надо доделать
        public List<MenuItemData> menuItemsData = new List<MenuItemData>
        {
            new MenuItemData("Удар", "Нанести удар", "AnimationPlayer Kick 1"),
            new MenuItemData("Принять объятия", "Обнять персонажа","AnimationPlayer Hug"),
            new MenuItemData("Отказ", "Спросить что-то", "AnimationPlayer Nope Juice"),
            new MenuItemData("Остановить анимацию")
        };
        private List<GameObject> menuItems = new List<GameObject>();

        private Vector2 center;
        private bool Showed = false;
        private MenuItemData selectedItem;
        
        private int lastSelectedIndex = -1;

        public GameObject Container = new GameObject("Container");

        private void Start()
        {
            // Создаем префаб если он не задан
            if (itemPrefab == null)
            {
                itemPrefab = RadialMenuItem.CreatePrefab();
                DontDestroyOnLoad(itemPrefab); // Сохраняем префаб между сценами
            }

            center = new Vector2(Screen.width / 2, Screen.height / 2);

            Container.transform.SetParent(transform, false);
            Container.transform.localPosition = Vector3.zero;
            Container.active = false;

            GenerateItems();
        }

        void Update()
        {
            if (!MitaCore.isRequiredScene() || !isAllowed) return;

            // Если правая кнопка мыши только что нажата
            if (Input.GetMouseButtonDown(1))
            {
                if (!Showed && !UINeuroMita.isPauseMenu)
                {
                    ShowMenu();
                    Showed = true;
                }
            }
            // Если правая кнопка мыши отпущена и меню было показано
            else if (Input.GetMouseButtonUp(1) && Showed)
            {
                ExecuteSelectedAction();
                HideMenu();
                Showed = false;
            }

            // Если меню показано, обновляем выбор
            if (Showed && !UINeuroMita.isPauseMenu)
            {
                UpdateSelection();


            }
        }

        void ShowMenu()
        {
            Showed = true;
            Container.active = true;
            //radialCanvas.enabled = true;
            //Cursor.lockState = CursorLockMode.None;
            center = new Vector2(Screen.width / 2, Screen.height / 2);
            try
            {
                PlayerAnimationModded.playerMove.stopMouseMove = true;
                MitaCore.Instance.playerController.ShowCursor(true);
               
            }
            catch (Exception ex)
            {

                MelonLogger.Error(ex);
            }

            
        }

        void HideMenu()
        {
            Showed = false;
            Container.active = false;

            try
            {
                PlayerAnimationModded.playerMove.stopMouseMove = false;
                MitaCore.Instance.playerController.ShowCursor(false);
                
            }
            catch (Exception ex)
            {

                MelonLogger.Error(ex);
            }

        }

        void UpdateSelection()
        {
            Vector2 mousePos = Input.mousePosition;
            int closestIndex = -1;
            float minDistance = float.MaxValue;

            // Находим ближайший элемент
            for (int i = 0; i < menuItems.Count; i++)
            {
                float dist = Vector2.Distance(mousePos, menuItems[i].transform.position);
                if (dist < minDistance && dist < selectionThreshold)
                {
                    minDistance = dist;
                    closestIndex = i;
                }
            }

            // Обновляем выделение
            if (closestIndex != lastSelectedIndex)
            {
                // Снимаем выделение с предыдущего
                if (lastSelectedIndex != -1)
                {
                    menuItems[lastSelectedIndex].GetComponent<Image>().color = normalColor;
                }

                // Выделяем новый
                if (closestIndex != -1)
                {
                    menuItems[closestIndex].GetComponent<Image>().color = hoverColor;
                    selectedItem = menuItemsData[closestIndex];
                }
                else { 
                    selectedItem = null;
                }

                lastSelectedIndex = closestIndex;
            }
        }

        void ExecuteSelectedAction()
        {
            if (selectedItem != null )
            {
                MelonLogger.Msg($"!!! CHOSE: {selectedItem.title}");
                switch (selectedItem.title)
                {
                    //Если нужна кастомная логика то тут можно что-то поменять
                    case "Отказ":
                        PlayerAnimationModded.playObjectAnimationOnPlayer("AnimationPlayer Nope Juice");
                        break;
                    case "Остановить анимацию":
                        PlayerAnimationModded.stopAnim();
                        break;
                    default:
                        PlayerAnimationModded.playObjectAnimationOnPlayer(selectedItem.animationName);
                        break;
                }
            }
        }

        void GenerateItems()
        {
            // Очистка старых элементов
            foreach (var item in menuItems)
            {
                Destroy(item);
            }
            menuItems.Clear();

            float angleStep = 360f / menuItemsData.Count;

            for (int i = 0; i < menuItemsData.Count; i++)
            {
                // Создаем элемент меню
                GameObject item = Instantiate(itemPrefab, Container.transform);
                menuItems.Add(item);


                // Позиционирование по кругу
                float angle = angleStep * i * Mathf.Deg2Rad;
                Vector2 pos = new Vector2(
                    Mathf.Cos(angle) * radius,
                    Mathf.Sin(angle) * radius
                );
                item.GetComponent<RectTransform>().anchoredPosition = pos;

                // Настройка внешнего вида
                var menuItem = item.GetComponent<RadialMenuItem>();
                if (menuItem != null)
                {
                    menuItem.Setup(menuItemsData[i].title, i < menuItemsData.Count ? menuItemsData[i].description : "");
                }
            }
        }

        // Цвета для удобства
        private Color normalColor = new Color(0.2f, 0.2f, 0.2f, 0.8f);
        private Color hoverColor = new Color(0.3f, 0.5f, 0.8f, 1f);
    }

    [RegisterTypeInIl2Cpp]
    public class RadialMenuItem : MonoBehaviour
    {
        public static GameObject CreatePrefab()
        {
            // Создаем корневой объект
            var item = new GameObject("RadialMenuItem");
            var rectTransform = item.AddComponent<RectTransform>();
            rectTransform.sizeDelta = new Vector2(125, 125);

            // Добавляем компоненты
            var image = item.AddComponent<Image>();
            image.color = new Color(0.2f, 0.2f, 0.2f, 0.8f);

            // Создаем дочерний объект для текста
            var textObj = new GameObject("Text");
            textObj.transform.SetParent(item.transform);

            var text = textObj.AddComponent<Text>();
            text.text = "Item";
            text.font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            text.fontSize = 20;
            text.color = Color.white;
            text.alignment = TextAnchor.MiddleCenter;

            // Настраиваем RectTransform для текста
            var textRect = textObj.GetComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero;
            textRect.anchorMax = Vector2.one;
            textRect.offsetMin = Vector2.zero;
            textRect.offsetMax = Vector2.zero;

            // Добавляем компонент RadialMenuItem
            var menuItem = item.AddComponent<RadialMenuItem>();
            menuItem.label = text;
            menuItem.background = image;

            return item;
        }

        public Image background;
        public Text label;
        public GameObject descriptionPanel;
        public Text descriptionText;

        public void Setup(string itemName, string description)
        {
            // Гарантируем, что компоненты найдены
            if (label == null) label = GetComponentInChildren<Text>();

            label.text = itemName;

            // Опционально для описания
            if (descriptionText == null && descriptionPanel != null)
                descriptionText = descriptionPanel.GetComponentInChildren<Text>();

            if (descriptionText != null)
                descriptionText.text = description;
        }

        private void Awake()
        {
            if (label == null) label = GetComponentInChildren<Text>();
            if (background == null) background = GetComponent<Image>();
        }
    }

    [System.Serializable]
    public class MenuItemData
    {
        public string title;
        public string description;
        public string animationName; // Дополнительные параметры можно легко добавлять
        public Color highlightColor = new Color(0.3f, 0.5f, 0.8f, 1f);

        public MenuItemData(string title, string description = null, string animationName = null)
        {
            this.title = title;
            this.description = description;
            this.animationName = animationName;
        }
    }
}
