using MelonLoader;
using UnityEngine;

public static class PlayerHands
{
    static Transform RightItem;
    static Transform LeftItem;
    static Dictionary<int, (Transform, Vector3, Vector3)> OldParents = new Dictionary<int, (Transform, Vector3, Vector3)>();

    public static void Init(Transform playerObject)
    {
        RightItem = playerObject.Find("RightItem FixPosition");
        LeftItem = playerObject.Find("LeftItem FixPosition");
    }

    public static void TakeInHand(GameObject gameObject, bool right, Vector3 localPos, Vector3 localRot)
    {
        Transform hand = right ? RightItem : LeftItem;
        if (hand == null)
        {
            MelonLogger.Error("Hand is null!!!");
            return;
        }

        // Сохраняем оригинальные параметры объекта
        OldParents[gameObject.GetInstanceID()] = (
            gameObject.transform.parent,
            gameObject.transform.localPosition,
            gameObject.transform.localEulerAngles
        );

        // Присоединяем объект к руке
        gameObject.transform.SetParent(hand);
        gameObject.transform.localPosition = localPos;
        gameObject.transform.localEulerAngles = localRot;
    }

    public static void Free(GameObject gameObject, bool right)
    {
        if (OldParents.TryGetValue(gameObject.GetInstanceID(), out var oldData))
        {
            // Восстанавливаем оригинальные параметры объекта
            gameObject.transform.SetParent(oldData.Item1);
            gameObject.transform.localPosition = oldData.Item2;
            gameObject.transform.localEulerAngles = oldData.Item3;

            OldParents.Remove(gameObject.GetInstanceID());
        }
        else
        {
            MelonLogger.Error($"Object {gameObject.name} not found in OldParents!");
        }
    }

    // Перегруженный метод для явного указания нового родителя (если нужно)
    public static void Free(GameObject gameObject, bool right, Transform newParent, Vector3 localPos, Vector3 localRot)
    {
        gameObject.transform.SetParent(newParent);
        gameObject.transform.localPosition = localPos;
        gameObject.transform.localEulerAngles = localRot;

        // Удаляем запись, если объект был в OldParents
        if (OldParents.ContainsKey(gameObject.GetInstanceID()))
        {
            OldParents.Remove(gameObject.GetInstanceID());
        }
    }
}