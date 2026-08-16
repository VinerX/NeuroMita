using Il2Cpp;
using MelonLoader;
using UnityEngine;


namespace MitaAI
{

    [HarmonyLib.HarmonyPatch]
    public static class ObjectInteractiveModded
    {
        [HarmonyLib.HarmonyPatch(typeof(ObjectInteractive), "Click")]
        [HarmonyLib.HarmonyPrefix]
        private static bool Prefix(ObjectInteractive __instance)
        {
            MelonLogger.Msg($"Prefix ObjectInteractiveModded {__instance.name}");
            // Получаем GameObject, к которому прикреплён ObjectInteractive
            GameObject targetObject = __instance.gameObject;

            var c = targetObject.GetComponentInParent<CommonInteractableObject>();

            if (c != null) {
                if (c.isTaken()){
                    return false;
                }
            }
            return true;

        }
    }

   

 

}
