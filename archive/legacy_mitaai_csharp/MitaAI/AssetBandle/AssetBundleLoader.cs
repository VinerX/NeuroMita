using Il2Cpp;
using MelonLoader;
using MelonLoader.Utils;
using System.IO;
using System.Reflection.Metadata;
using UnityEngine;
namespace MitaAI
{
    public static class AssetBundleLoader
    {

        public static Il2CppAssetBundle bundle = null;
        public static Il2CppAssetBundle bundleTestMita = null;

        public static Il2CppAssetBundle initBundle()
        {
            bundle = AssetBundleLoader.LoadAssetBundle("assetbundle");
            try
            {
                bundleTestMita = AssetBundleLoader.LoadAssetBundle("testmita");
            }
            catch (Exception ex)
            {

                MelonLogger.Error($"Second asset bundle error {ex}");
            }
            
            return bundle;
        }

        /// <summary>
        /// Загружает AssetBundle и возвращает его.
        /// </summary>
        /// <param name="bundleName">Имя файла AssetBundle (с расширением).</param>
        /// <returns>Загруженный AssetBundle или null, если загрузка не удалась.</returns>
        /// 
        public static Il2CppAssetBundle LoadAssetBundle(string bundleName)
        {
            // Путь к AssetBundle (например, рядом с файлом мода)
            string bundlePath = Path.Combine(MelonEnvironment.ModsDirectory, bundleName + ".test");

            if (!File.Exists(bundlePath))
            {
                MelonLoader.MelonLogger.Error($"Not found {bundleName}  {bundlePath}");
                return null;
            }

            MelonLoader.MelonLogger.Error("Before loading.");
            // Загрузка AssetBundle
            Il2CppAssetBundle bundle = Il2CppAssetBundleManager.LoadFromFile(bundlePath);

            if (bundle == null)
            {
                MelonLoader.MelonLogger.Error("Not loaded AssetBundle.");
                return null;
            }
            else { MelonLogger.Msg("Succesfully loaded AssetBundle."); }

            MitaCore.bundle = bundle;
            return bundle;
        }

        /// <summary>
        /// Загружает объект из указанного AssetBundle.
        /// </summary>
        /// <param name="bundle">Загруженный AssetBundle.</param>
        /// <param name="assetName">Имя объекта в AssetBundle.</param>
        /// <returns>Созданный объект или null, если загрузка не удалась.</returns>
        public static GameObject LoadAndInstantiateAsset(AssetBundle bundle, string assetName)
        {
            if (bundle == null)
            {
                MelonLoader.MelonLogger.Error("AssetBundle не задан.");
                return null;
            }

            GameObject prefab = bundle.LoadAsset<GameObject>(assetName);
            if (prefab != null)
            {
                GameObject instance = GameObject.Instantiate(prefab);
                MelonLoader.MelonLogger.Msg($"Успешно загружен и создан объект: {prefab.name}");
                return instance;
            }
            else
            {
                MelonLoader.MelonLogger.Error($"Не удалось найти объект с именем {assetName} в AssetBundle.");
                return null;
            }
        }
        public static List<AnimationClip> LoadAllAnimationClips(Il2CppAssetBundle bundle)
        {

            List<AnimationClip> animationClips = new List<AnimationClip>();

            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle not recieced!");
                return animationClips;
            }

            // Получаем список всех имён ассетов в бандле
            string[] assetNames = bundle.GetAllAssetNames();

            foreach (string assetName in assetNames)
            {
                // Попытка загрузить ассет как AnimationClip
                AnimationClip clip = bundle.LoadAsset<AnimationClip>(assetName);
                if (clip != null)
                {
                    animationClips.Add(clip);
                    Debug.Log($"Loaded AnimationClip: {clip.name}");
                }
            }

            if (animationClips.Count == 0)
            {
                Debug.LogWarning("AssetBundle count = 0");
            }

            return animationClips;
        }
        public static RuntimeAnimatorController LoadAnimatorControllerByName(Il2CppAssetBundle bundle, string AnimatorName)
        {
            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle null!");
                return null;
            }

            if (string.IsNullOrEmpty(AnimatorName))
            {
                MelonLogger.Msg("name empty AnimationClip!");
                return null;
            }

            // Добавляем расширение .anim, если его нет
            if (!AnimatorName.EndsWith(".controller", StringComparison.OrdinalIgnoreCase))
            {
                AnimatorName += ".controller";
            }

            // Получаем список всех имён ассетов в бандле
            string[] assetNames = bundle.GetAllAssetNames();

            foreach (string assetName in assetNames)
            {
                // Проверка имени ассета без расширения и сравнение с искомым
                if (string.Equals(Path.GetFileName(assetName), AnimatorName, StringComparison.OrdinalIgnoreCase))
                {
                    // Загружаем ассет как AnimationClip
                    RuntimeAnimatorController controller = bundle.LoadAsset<RuntimeAnimatorController>(assetName);
                    if (controller != null)
                    {
                        MelonLogger.Msg($"Found and loaded Controller: {controller.name}");
                        return controller;
                    }
                }
            }

            MelonLogger.Msg($"Controller '{AnimatorName}' not found in AssetBundle.");
            return null;
        }


        public static AnimationClip LoadAnimationClipByName(Il2CppAssetBundle bundle, string clipName)
        {
            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle null!");
                return null;
            }

            if (string.IsNullOrEmpty(clipName))
            {
                MelonLogger.Msg("name empty AnimationClip!");
                return null;
            }

            // Добавляем расширение .anim, если его нет
            if (!clipName.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
            {
                clipName += ".anim";
            }

            // Получаем список всех имён ассетов в бандле
            string[] assetNames = bundle.GetAllAssetNames();

            foreach (string assetName in assetNames)
            {
                // Проверка имени ассета без расширения и сравнение с искомым
                if (string.Equals(Path.GetFileName(assetName), clipName, StringComparison.OrdinalIgnoreCase))
                {
                    // Загружаем ассет как AnimationClip
                    AnimationClip clip = bundle.LoadAsset<AnimationClip>(assetName);
                    if (clip != null)
                    {
                        MelonLogger.Msg($"Found and loaded AnimationClip: {clip.name}");
                        return clip;
                    }
                }
            }

            MelonLogger.Msg($"AnimationClip '{clipName}' not found in AssetBundle.");
            return null;
        }
        public static AudioClip LoadAudioClipByName(Il2CppAssetBundle bundle, string clipName)
        {
            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle null!");
                return null;
            }

            if (string.IsNullOrEmpty(clipName))
            {
                MelonLogger.Msg("name empty AudioClip!");
                return null;
            }

            // Добавляем расширение .anim, если его нет
            if (!clipName.EndsWith(".ogg", StringComparison.OrdinalIgnoreCase))
            {
                clipName += ".ogg";
            }

            // Получаем список всех имён ассетов в бандле
            string[] assetNames = bundle.GetAllAssetNames();

            foreach (string assetName in assetNames)
            {
                // Проверка имени ассета без расширения и сравнение с искомым
                if (string.Equals(Path.GetFileName(assetName), clipName, StringComparison.OrdinalIgnoreCase))
                {
                    // Загружаем ассет как AnimationClip
                    AudioClip clip = bundle.LoadAsset<AudioClip>(assetName);
                    if (clip != null)
                    {
                        MelonLogger.Msg($"Found and loaded AudioClip: {clip.name}");
                        return clip;
                    }
                }
            }

            MelonLogger.Msg($"AudioClip '{clipName}' not found in AssetBundle.");
            return null;
        }

        static List<string> animationClipNames = new List<string>();
        public static AnimationClip LoadRandomAnimationClip(Il2CppAssetBundle bundle)
        {
            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle is null!");
                return null;
            }

            if (animationClipNames == null || animationClipNames.Count == 0)
            {
                // Получаем список всех ресурсов в AssetBundle
                string[] allAssetNames = bundle.GetAllAssetNames();
                if (allAssetNames == null || allAssetNames.Length == 0)
                {
                    MelonLogger.Msg("No assets found in the AssetBundle.");
                    return null;
                }

                // Фильтруем только анимации

                animationClipNames = allAssetNames
                    .Where(name => name.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
                    .ToList();
            }


            if (animationClipNames.Count == 0)
            {
                MelonLogger.Msg("No AnimationClips found in the AssetBundle.");
                return null;
            }

            // Выбираем случайное имя анимации
            int randomIndex = new System.Random().Next(animationClipNames.Count);
            string randomClipName = animationClipNames[randomIndex];

            // Загружаем анимацию по имени
            AnimationClip randomClip = bundle.LoadAsset<AnimationClip>(randomClipName);

            if (randomClip != null)
            {
                MelonLogger.Msg($"Random AnimationClip selected: {randomClip.name}");
            }
            else
            {
                MelonLogger.Msg($"Failed to load AnimationClip: {randomClipName}");
            }

            return randomClip;
        }


        #region UniversalLoading
        public static List<T> LoadAllAssets<T>(Il2CppAssetBundle bundle) where T : UnityEngine.Object
        {
            List<T> assets = new List<T>();

            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle not received!");
                return assets;
            }

            string[] assetNames = bundle.GetAllAssetNames();

            foreach (string assetName in assetNames)
            {
                try
                {
                    T asset = bundle.LoadAsset<T>(assetName);
                    if (asset != null)
                    {
                        assets.Add(asset);
                        Debug.Log($"Loaded {typeof(T).Name}: {asset.name}");
                    }
                }
                catch (Exception e)
                {
                    Debug.LogError($"Failed to load asset {assetName} as {typeof(T).Name}: {e.Message}");
                }
            }

            if (assets.Count == 0)
            {
                Debug.LogWarning($"No assets of type {typeof(T).Name} found in AssetBundle");
            }

            return assets;
        }

        public static T LoadAssetByName<T>(Il2CppAssetBundle bundle, string assetName) where T : UnityEngine.Object
        {
            if (bundle == null)
            {
                MelonLogger.Msg("AssetBundle is null!");
                return null;
            }

            if (string.IsNullOrEmpty(assetName))
            {
                MelonLogger.Msg($"Asset name for type {typeof(T).Name} is empty!");
                return null;
            }

            string[] allAssetNames = bundle.GetAllAssetNames();

            foreach (string bundleAssetName in allAssetNames)
            {
                string fileName = Path.GetFileNameWithoutExtension(bundleAssetName);

                if (string.Equals(fileName, assetName, StringComparison.OrdinalIgnoreCase))
                {
                    T asset = bundle.LoadAsset<T>(bundleAssetName);

                    if (asset != null)
                    {
                        MelonLogger.Msg($"Successfully loaded {typeof(T).Name}: {asset.name}");
                        return asset;
                    }
                    else
                    {
                        MelonLogger.Msg($"Asset '{assetName}' exists but is not of type {typeof(T).Name}");
                        return null;
                    }
                }
            }

            MelonLogger.Msg($"Asset of type {typeof(T).Name} '{assetName}' not found in bundle");
            return null;
        }


        #endregion




    }
}