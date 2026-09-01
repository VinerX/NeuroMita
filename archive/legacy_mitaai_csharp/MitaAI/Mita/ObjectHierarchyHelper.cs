using System.Text;
using System.Collections.Generic;
using UnityEngine;

public static class ObjectHierarchyHelper
{
    public static string GetObjectsInRadiusAsTree(GameObject origin, float radius, Transform requiredParent, List<string> excludedParentNames)
    {
        // Используем StringBuilder для построения строки
        StringBuilder treeBuilder = new StringBuilder();

        // Находим все объекты в радиусе
        Collider[] colliders = Physics.OverlapSphere(origin.transform.position, radius);

        // Итерация по объектам
        foreach (Collider collider in colliders)
        {
            Transform currentTransform = collider.transform;

            // Проверяем, имеет ли объект указанного родителя и не принадлежит ли исключенному
            if (IsChildOfParent(currentTransform, requiredParent) && !HasExcludedParent(currentTransform, excludedParentNames))
            {
                // Строим дерево имен
                AppendHierarchyToTree(currentTransform, treeBuilder, 0, origin.transform.position);
            }
        }

        string result = treeBuilder.ToString();
        if (result == "") result = "-";
        return result;
    }

    private static bool IsChildOfParent(Transform obj, Transform parent)
    {
        Transform current = obj;

        while (current != null)
        {
            if (current == parent)
                return true;

            current = current.parent;
        }

        return false;
    }

    private static bool HasExcludedParent(Transform obj, List<string> excludedParentNames)
    {
        Transform current = obj;

        while (current != null)
        {
            foreach (string excludedName in excludedParentNames)
            {
                if (current.name.Contains(excludedName))
                {
                    return true;
                }
            }

            current = current.parent;
        }

        return false;
    }

    private static void AppendHierarchyToTree(Transform current, StringBuilder builder, int depth, Vector3 from)
    {
        string distance = $" {Vector3.Distance(current.position, from):F2} м";

        // Добавляем текущий объект с отступами
        builder.AppendLine(new string('-', depth) + current.name + distance);

        // Рекурсивно добавляем всех детей, если текущий объект не исключен
        int childCount = current.childCount;
        for (int i = 0; i < childCount; i++)
        {
            Transform child = current.GetChild(i);
            AppendHierarchyToTree(child, builder, depth + 1, from);
        }
    }
}
