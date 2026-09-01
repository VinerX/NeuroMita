using System.Collections.Generic;
using UnityEngine;
using MelonLoader;

namespace MitaAI
{
    public static class ShaderReplacer
    {
        private static Dictionary<Material, Shader> originalShaders = new Dictionary<Material, Shader>();

        private static Shader standardShader;

        public static void init()
        {
            // Находим стандартный шейдер
            //standardShader = Shader.Find("Standard");
            standardShader = Shader.Find("Legacy Shaders/Diffuse");

            if (standardShader == null)
            {
                MelonLogger.Error("Standard Shader not found!");
            }
        }

        // Функция для замены шейдера на null
        public static void ReplaceShaders(GameObject root)
        {
            Renderer[] renderers = root.GetComponentsInChildren<Renderer>(true);
            foreach (Renderer renderer in renderers)
            {
                Material[] materials = renderer.materials;
                for (int i = 0; i < materials.Length; i++)
                {
                    Material material = materials[i];
                    if (material.shader != null &&
                        (material.shader.name == "Aihasto/DrawWorld" || material.shader.name == "RealToon/Version 5/Default/Default"))
                    {
                        // Сохраняем оригинальный шейдер
                        originalShaders[material] = material.shader;
                        // Заменяем шейдер на null
                        material.shader = standardShader;
                    }
                }
            }
        }

        // Функция для восстановления оригинального шейдера
        public static void RestoreShaders()
        {
            foreach (var kvp in originalShaders)
            {
                Material material = kvp.Key;
                Shader originalShader = kvp.Value;
                material.shader = originalShader;
            }
            originalShaders.Clear();
        }
    }
}