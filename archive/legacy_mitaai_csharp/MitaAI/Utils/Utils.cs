using Il2Cpp;
using Il2CppInterop.Runtime.InteropTypes;
using MelonLoader;
using System;
using System.Collections;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using System.Text.RegularExpressions;
namespace MitaAI
{
    public static class Utils
    {

        /// <summary>
        /// Возвращает true с вероятностью a/b
        /// </summary>
        /// <param name="a">Числитель (шанс успеха)</param>
        /// <param name="b">Знаменатель (общий диапазон)</param>
        /// <returns>True, если шанс произошел, иначе False</returns>
        public static bool Random(int a, int b)
        {
            // Проверка на корректность входных данных
            if (a < 0 || b <= 0 || a > b)
            {
                Debug.LogError("Некорректные значения a и b. Должно быть: 0 <= a <= b, b > 0");
                return false;
            }

            // Генерация случайного числа в диапазоне [0, b)
            int randomValue = UnityEngine.Random.Range(0, b);

            // Возвращаем true, если randomValue < a
            return randomValue < a;
        }

        public static string CleanFromTags(string text)
        {
            string textCleaned = Regex.Replace(text, @"<[^>]+>.*?</[^>]+>", ""); // Очищаем от всех тегов
            textCleaned = Regex.Replace(textCleaned, @"<[^>]+>", ""); // Очищаем от всех тегов

            return textCleaned;
        }

        public static void CopyComponentValues(ObjectInteractive source, ObjectInteractive destination)
        {
            if (source == null || destination == null)
            {
                MelonLogger.Msg("Source or destination is null!");
                return;
            }

            // Если нужно скопировать все поля автоматически, можно использовать рефлексию
            var fields = typeof(ObjectInteractive).GetFields();
            foreach (var field in fields)
            {
                field.SetValue(destination, field.GetValue(source));
            }

            MelonLogger.Msg("Component values copied!");
        }

        public static float getDistanceBetweenObjects(GameObject a, GameObject b)
        {
            return Vector3.Distance(a.transform.position, b.transform.position);
        }

        static public IEnumerator DestroyObjecteAfterTime(GameObject obj, float delay)
        {
            // Проверяем, не null ли объект
            if (obj == null)
            {
                MelonLogger.Msg("GameObject is null. Cannot toggle.");
                yield break;
            }

            // Ждём заданное время
            yield return new WaitForSeconds(delay);

            GameObject.Destroy(obj);
        }



        public static IEnumerator ToggleObjectActiveAfterTime(GameObject obj, float delay = 5f)
        {
            // Проверяем, не null ли объект
            if (obj == null)
            {
                MelonLogger.Msg("GameObject is null. Cannot toggle.");
                yield break;
            }

            // Ждём заданное время
            yield return new WaitForSeconds(delay);

            // Переключаем активность объекта
            obj.SetActive(!obj.activeSelf);
            MelonLogger.Msg($"GameObject {obj.name} is now {(obj.activeSelf ? "active" : "inactive")}");
        }
        public static IEnumerator OnOffObjectActiveAfterTime(GameObject obj,bool on, float delay = 5f)
        {
            // Проверяем, не null ли объект
            if (obj == null)
            {
                MelonLogger.Msg("GameObject is null. Cannot toggle.");
                yield break;
            }

            // Ждём заданное время
            yield return new WaitForSeconds(delay);

            // Переключаем активность объекта
            obj.SetActive(on);
            MelonLogger.Msg($"GameObject {obj.name} is now {(obj.activeSelf ? "active" : "inactive")}");
        }

        public static GameObject TryfindChild(Transform parent, string path)
        {
            try
            {
                return parent.Find(path).gameObject;
            }
            catch (Exception e)
            {

                MelonLogger.Msg($"Tried found {path} but {e}");
                return null;
            }
        }
        public static void TryTurnChild(Transform parent, string path, bool on)
        {
            try
            {
                TryfindChild(parent, path).gameObject.SetActive(on);
            }
            catch (Exception e)
            {

                MelonLogger.Msg("Tried turn " + path + " " + e);
                return;
            }
        }
        public static void DestroyAfterTime(GameObject gameObject, float delay = 5f)
        {
            MelonCoroutines.Start(DestroyAfterTimeCorutine(gameObject, delay));
        }

        public static IEnumerator DestroyAfterTimeCorutine(GameObject gameObject, float delay = 5f)
        {
            yield return new WaitForSeconds(delay);
            GameObject.Destroy(gameObject);

            while (gameObject != null)
            {
                yield return new WaitForSeconds(delay);
                GameObject.Destroy(gameObject);
            }
        }

        // Корутинa для переключения активности компоненты
        public static IEnumerator ToggleComponentAfterTime(Component component, float delay)
        {
            MelonLogger.Msg($"Starting ToggleComponentAfterTime for {component?.GetType().Name} with delay {delay}...");

            if (component == null)
            {
                MelonLogger.Msg("Component is null. Cannot toggle.");
                yield break;
            }

            if (component is MonoBehaviour monoBehaviourComponent)
            {
                yield return new WaitForSeconds(delay);

                monoBehaviourComponent.enabled = !monoBehaviourComponent.enabled;
                MelonLogger.Msg($"{monoBehaviourComponent.GetType().Name} is now {(monoBehaviourComponent.enabled ? "enabled" : "disabled")}");
            }
            else if (component is Il2CppObjectBase il2cppComponent)
            {
                MelonLogger.Msg($"Detected Il2Cpp component: {il2cppComponent.GetType().Name}");

                // Проверяем, есть ли у компонента свойство enabled
                var enabledProperty = il2cppComponent.GetType().GetProperty("enabled");
                if (enabledProperty != null && enabledProperty.PropertyType == typeof(bool))
                {
                    // Читаем текущее значение свойства
                    bool isEnabled = (bool)enabledProperty.GetValue(il2cppComponent);
                    MelonLogger.Msg($"Current enabled state of {il2cppComponent.GetType().Name}: {isEnabled}");

                    yield return new WaitForSeconds(delay);

                    // Переключаем значение
                    enabledProperty.SetValue(il2cppComponent, !isEnabled);
                    MelonLogger.Msg($"{il2cppComponent.GetType().Name} is now {(!isEnabled ? "enabled" : "disabled")}");
                }
                else
                {
                    MelonLogger.Warning($"The component {il2cppComponent.GetType().Name} does not have an 'enabled' property.");
                }
            }
            else
            {
                MelonLogger.Warning($"Component {component?.GetType().Name} is not a MonoBehaviour or Il2CppObjectBase. Cannot toggle.");
            }

            MelonLogger.Msg($"Finished ToggleComponentAfterTime for {component?.GetType().Name}.");
        }

        public static IEnumerator HandleIl2CppComponent(Il2CppObjectBase il2cppComponent, float delay)
        {
            MelonLogger.Msg($"Starting HandleIl2CppComponent for {il2cppComponent?.GetType().Name} with delay {delay}...");

            if (il2cppComponent == null)
            {
                MelonLogger.Msg("Il2CppComponent is null. Cannot toggle.");
                yield break;
            }

            // Пробуем преобразовать объект в Behaviour
            var behaviour = il2cppComponent.TryCast<Behaviour>();
            if (behaviour != null)
            {
                MelonLogger.Msg($"Il2Cpp Behaviour detected: {behaviour.GetType().Name}");

                // Читаем текущее состояние и переключаем
                bool currentState = behaviour.enabled;
                MelonLogger.Msg($"Current enabled state of {behaviour.GetType().Name}: {currentState}");

                yield return new WaitForSeconds(delay);

                behaviour.enabled = !currentState;
                MelonLogger.Msg($"{behaviour.GetType().Name} is now {(behaviour.enabled ? "enabled" : "disabled")}");
            }
            else
            {
                MelonLogger.Warning($"The Il2Cpp component {il2cppComponent.GetType().Name} is not a Behaviour or does not support 'enabled' property.");
            }

            MelonLogger.Msg($"Finished HandleIl2CppComponent for {il2cppComponent?.GetType().Name}.");
        }

        private static Dictionary<Transform, object> activeAnimations = new Dictionary<Transform, object>();
        private static Dictionary<Transform, Queue<AnimationRequest>> pendingAnimations = new Dictionary<Transform, Queue<AnimationRequest>>();

        private struct AnimationRequest
        {
            public Vector3 position;
            public Vector3 rotation;
            public float duration;
            public bool delta;
        }

        public static void StartObjectAnimation(GameObject targetObject, Vector3 position, Vector3 rotation, float duration, bool delta = true)
        {
            if (targetObject == null) return;

            Transform targetTransform = targetObject.transform;
            var request = new AnimationRequest { position = position, rotation = rotation, duration = duration, delta = delta };

            // Если для этого объекта уже есть активная анимация
            if (activeAnimations.ContainsKey(targetTransform))
            {
                // Добавляем в очередь вместо прерывания
                if (!pendingAnimations.TryGetValue(targetTransform, out Queue<AnimationRequest> queue))
                {
                    queue = new Queue<AnimationRequest>();
                    pendingAnimations[targetTransform] = queue;
                }
                queue.Enqueue(request);
            }
            else
            {
                // Нет активной анимации - запускаем сразу
                StartNewAnimation(targetTransform, request);
            }
        }

        private static void StartNewAnimation(Transform targetTransform, AnimationRequest request)
        {
            object newCoroutine = request.delta ?
                MelonCoroutines.Start(AnimateObjectByDelta(targetTransform, request.position, request.rotation, request.duration)) :
                MelonCoroutines.Start(AnimateObjectToFinalPos(targetTransform, request.position, request.rotation, request.duration));

            activeAnimations[targetTransform] = newCoroutine;
        }

        private static IEnumerator AnimateObjectByDelta(Transform targetTransform,
                                        Vector3 positionOffset,
                                        Vector3 rotationOffset,
                                        float animationTime)
        {
            if (targetTransform == null) yield break;

            Vector3 startPosition = targetTransform.localPosition;
            Quaternion startRotation = targetTransform.localRotation;

            Vector3 targetPosition = startPosition + positionOffset;
            Quaternion targetRotation = startRotation * Quaternion.Euler(rotationOffset);

            float elapsed = 0f;

            while (elapsed < animationTime)
            {
                float t = elapsed / animationTime;
                targetTransform.localPosition = Vector3.Lerp(startPosition, targetPosition, t);
                targetTransform.localRotation = Quaternion.Slerp(startRotation, targetRotation, t);

                elapsed += Time.deltaTime;
                yield return null;
            }

            // Finalize position and rotation
            targetTransform.localPosition = targetPosition;
            targetTransform.localRotation = targetRotation;

            OnAnimationComplete(targetTransform);
        }

        private static IEnumerator AnimateObjectToFinalPos(Transform targetTransform,
                                        Vector3 positionFinal,
                                        Vector3 rotationFinal,
                                        float animationTime)
        {
            if (targetTransform == null) yield break;

            Vector3 startPosition = targetTransform.localPosition;
            Quaternion startRotation = targetTransform.localRotation;

            Vector3 targetPosition = positionFinal;
            Quaternion targetRotation = Quaternion.Euler(rotationFinal);

            float elapsed = 0f;

            while (elapsed < animationTime)
            {
                float t = elapsed / animationTime;
                targetTransform.localPosition = Vector3.Lerp(startPosition, targetPosition, t);
                targetTransform.localRotation = Quaternion.Slerp(startRotation, targetRotation, t);

                elapsed += Time.deltaTime;
                yield return null;
            }

            // Finalize position and rotation
            targetTransform.localPosition = targetPosition;
            targetTransform.localRotation = targetRotation;

            OnAnimationComplete(targetTransform);
        }

        private static void OnAnimationComplete(Transform targetTransform)
        {
            // Удаляем из активных анимаций
            activeAnimations.Remove(targetTransform);

            // Проверяем очередь ожидающих анимаций
            if (pendingAnimations.TryGetValue(targetTransform, out Queue<AnimationRequest> queue) && queue.Count > 0)
            {
                var nextRequest = queue.Dequeue();
                StartNewAnimation(targetTransform, nextRequest);

                // Если очередь пуста, удаляем её
                if (queue.Count == 0)
                {
                    pendingAnimations.Remove(targetTransform);
                }
            }
        }

        // Метод для очистки всех анимаций (опционально)
        public static void ClearAllAnimations()
        {
            foreach (var coroutine in activeAnimations.Values)
            {
                MelonCoroutines.Stop(coroutine);
            }
            activeAnimations.Clear();
            pendingAnimations.Clear();
        }
    

    public static void setTextTimed(UnityEngine.UI.Text text,string content,float time = 2f)
        {
            text.text = content;
            text.m_Text = content;
            MelonCoroutines.Start(setTextTimedCorutine(text,content,time));
        }
        static IEnumerator setTextTimedCorutine(UnityEngine.UI.Text text, string content, float time = 2f)
        {
            yield return new WaitForSeconds(time);
            text.text = content;
            text.m_Text = content;

        }

    }


}
