using UnityEngine;
using System;
using System.Reflection;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

public static class ComponentCopier
{
    public static T CopyComponent<T>(T original, GameObject target, Transform originalRoot, Transform newRoot)
        where T : Component
    {
        // Создание компонента на целевом объекте
        T newComp = target.AddComponent<T>();

        // Копирование полей
        foreach (FieldInfo field in typeof(T).GetFields(
            BindingFlags.Public |
            BindingFlags.NonPublic |
            BindingFlags.Instance))
        {
            object value = field.GetValue(original);
            field.SetValue(newComp, ProcessValue(value, originalRoot, newRoot));
        }

        return newComp;
    }

    private static object ProcessValue(object value, Transform oldRoot, Transform newRoot)
    {
        if (value is UnityEngine.Object unityObj)
        {
            return HandleUnityObject(unityObj, oldRoot, newRoot);
        }
        else if (value is Il2CppReferenceArray<UnityEngine.Object> arr)
        {
            return ProcessArray(arr, oldRoot, newRoot);
        }
        return value;
    }

    private static object ProcessArray(Il2CppReferenceArray<UnityEngine.Object> arr, Transform oldRoot, Transform newRoot)
    {
        UnityEngine.Object[] newArr = new UnityEngine.Object[arr.Length];
        for (int i = 0; i < arr.Length; i++)
        {
            newArr[i] = HandleUnityObject(arr[i], oldRoot, newRoot);
        }
        return newArr;
    }

    private static UnityEngine.Object HandleUnityObject(UnityEngine.Object obj, Transform oldRoot, Transform newRoot)
    {
        if (obj == null) return null;

        // Для компонентов получаем Transform
        Transform objTransform = (obj is Component comp) ? comp.transform : null;

        if (objTransform != null && IsChildOfRoot(objTransform, oldRoot))
        {
            string relativePath = GetRelativePath(objTransform, oldRoot);
            return FindInNewHierarchy(newRoot, relativePath, obj.GetType());
        }

        return obj; // Возвращаем оригинал, если не в иерархии
    }

    private static bool IsChildOfRoot(Transform obj, Transform root)
    {
        while (obj != null)
        {
            if (obj == root) return true;
            obj = obj.parent;
        }
        return false;
    }

    private static string GetRelativePath(Transform target, Transform root)
    {
        if (target == root) return "";

        System.Collections.Generic.List<string> path = new();
        Transform current = target;
        while (current != null && current != root)
        {
            path.Add(current.name);
            current = current.parent;
        }
        path.Reverse();
        return string.Join("/", path);
    }

    private static UnityEngine.Object FindInNewHierarchy(Transform newRoot, string relativePath, Type type)
    {
        // Конвертируем System.Type в Il2CppSystem.Type
        Il2CppSystem.Type il2cppType = Il2CppType.From(type);

        if (string.IsNullOrEmpty(relativePath))
            return il2cppType == Il2CppType.Of<Transform>()
                ? newRoot
                : newRoot.GetComponent(il2cppType);

        Transform current = newRoot;
        foreach (string part in relativePath.Split('/'))
        {
            current = current.Find(part);
            if (current == null) break;
        }

        if (current == null) return null;

        return il2cppType == Il2CppType.Of<Transform>()
            ? current
            : current.GetComponent(il2cppType);
    }
}