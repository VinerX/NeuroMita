using MelonLoader;
using UnityEngine;

// Пока что оно не рабоатет, как я хотел.
public class EyeGlowModifier
{
    private GameObject eyeObject;
    private Material eyeMaterial;
    private Renderer eyeRenderer;

    public EyeGlowModifier(GameObject parent)
    {
        // Создаем новый дочерний объект для свечения
        eyeObject = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        eyeObject.name = "EyeGlow";
        eyeObject.transform.SetParent(parent.transform);
        eyeObject.transform.localPosition = Vector3.zero;
        eyeObject.transform.localScale = Vector3.one * 0.05f; // Примерный размер

        // Настраиваем рендерер и материал
        eyeRenderer = eyeObject.GetComponent<Renderer>();
        GameObject.Destroy(eyeObject.GetComponent<Collider>()); // Удаляем ненужный коллайдер

        Shader standardShader = Shader.Find("Standard");
        if (standardShader == null)
        {
            MelonLogger.Error("Standard shader not found!");
            return;
        }

        eyeMaterial = new Material(standardShader)
        {
            enableInstancing = true
        };

        // Настройка материала для свечения
        eyeMaterial.EnableKeyword("_EMISSION");
        eyeMaterial.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
        eyeMaterial.renderQueue = 3000; // Прозрачная очередь рендеринга

        eyeRenderer.material = eyeMaterial;

        // Инициализируем базовый цвет
        SetGlow(Color.white);

        MelonLogger.Msg("Eye glow created successfully");
    }

    public void SetGlow(Color glowColor)
    {
        if (eyeMaterial == null)
        {
            MelonLogger.Error("Material not initialized!");
            return;
        }

        // Устанавливаем параметры свечения с HDR-интенсивностью
        float intensity = 5f; // Можно регулировать интенсивность
        eyeMaterial.SetColor("_EmissionColor", glowColor * intensity);
        eyeMaterial.color = glowColor;

        // Обновляем глобальное освещение в реальном времени
        DynamicGI.UpdateEnvironment();
    }
    public void OnUpdateTest()
    {
        try
        {
            if (Input.GetKeyDown(KeyCode.Alpha1))
            {
                // Изменяем цвет на случайный
                Color glowColor = Color.HSVToRGB(UnityEngine.Random.value, UnityEngine.Random.value, UnityEngine.Random.value);
                SetGlow(glowColor);
                MelonLogger.Msg($"Random glow color applied: {glowColor}");
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Error($"Error in OnUpdateTest: {ex.Message}");
        }
    }
}
