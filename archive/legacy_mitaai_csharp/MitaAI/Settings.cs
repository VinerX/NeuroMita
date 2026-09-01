using MelonLoader;

namespace MitaAI
{
    public static class Settings
    {
        private static MelonPreferences_Category category;

        /* // Примеры настроек
        public static MelonPreferences_Entry<bool> AutoResponseEnabled;
        public static MelonPreferences_Entry<float> ResponseDelay;
        public static MelonPreferences_Entry<string> AiModelVersion;
        */

        public static MelonPreferences_Entry<characterType> MitaType;

        public static MelonPreferences_Entry<int> DaysInGame;
        public static MelonPreferences_Entry<string> Language;
        public static void Initialize()
        {
            MelonLogger.Msg($"Init settings");
            // Создаем категорию настроек
            category = MelonPreferences.CreateCategory("NeuroMita", "NeuroMita Settings");

            MitaType = category.CreateEntry("MitaType", characterType.Crazy);
            DaysInGame = category.CreateEntry("DaysInGame", 0);
            Language = category.CreateEntry("Language", "Ru");
            // Добавляем нового персонажа как опцию
            // category.CreateEntry("MilaType", character.Mila);

            /* // Инициализируем настройки со значениями по умолчанию
             AutoResponseEnabled = category.CreateEntry(
                 "AutoResponseEnabled",
                 true,
                 "Enable Automatic Responses",
                 "Whether the AI should respond automatically");

             ResponseDelay = category.CreateEntry(
                 "ResponseDelay",
                 0.5f,
                 "Response Delay (seconds)",
                 "Delay before sending AI response");

             AiModelVersion = category.CreateEntry(
                 "AiModelVersion",
                 "v2.1.5",
                 "AI Model Version",
                 "Version of the AI model to use");*/
        }

        // Метод для быстрого получения значения
        public static T Get<T>(string entryName)
        {
            var entry = category.GetEntry<T>(entryName);
            return entry != null ? entry.Value : default(T);
        }

        // Метод для быстрой установки значения
        public static void Set<T>(string entryName, T value)
        {
            var entry = category.GetEntry<T>(entryName);
            if (entry != null)
            {
                entry.Value = value;
                Save();
            }
        }

        // Сохранение настроек
        public static void Save()
        {
            MelonLogger.Msg($"Saving settings");
            MelonPreferences.Save();
        }
    }
}
