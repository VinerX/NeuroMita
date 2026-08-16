using Il2Cpp;
using UnityEngine;
using System.Reflection;
using System.Text.RegularExpressions;
using MelonLoader;


namespace MitaAI
{
    public static class MitaClothesModded
    {
        //MitaPerson MitaPerson;
        static Material hair_material;

        public enum Clothes

        {
            original,
            SchoolVariant1,
            SchoolVariant2,
            SchoolVariant3,
            Chirstmass,
            Vampire
        }
        public static Clothes currentClothes = Clothes.original;
        public static void init(HarmonyLib.Harmony harmony)
        {

            MethodInfo original = HarmonyLib.AccessTools.Method(typeof(GameController), "Update");
            MethodInfo original2 = HarmonyLib.AccessTools.Method(typeof(MitaClothes), name: "Start");
            MethodInfo patch = HarmonyLib.AccessTools.Method(typeof(MitaClothesModded), "UpdateTest");
            MethodInfo patch2 = HarmonyLib.AccessTools.Method(typeof(MitaClothesModded), "Start");
            //harmony.Patch(original, new HarmonyLib.HarmonyMethod(patch));
            harmony.Patch(original2, new HarmonyLib.HarmonyMethod(patch2));


        }
        public static string ProcessClothes(string response)
        {
            MelonLogger.Msg($"Inside ProcessClothes");
            List<string> clothes = new List<string>();
            string pattern = @"<clothes>(.*?)</clothes>";
            MatchCollection matches = Regex.Matches(response, pattern);

            foreach (Match match in matches)
            {
                if (match.Success)
                {
                    clothes.Add(match.Groups[1].Value);
                    MelonLogger.Msg($"Try Parse " + clothes[0]);
                    Enum.TryParse<Clothes>(clothes[0], true, out var form);

                    SetClothes(form);
                    break;
                }
            }

            string result = Regex.Replace(response, @"<clothes>.*?</clothes>", "");


            MelonLogger.Msg($"Inside ProcessClothes End");
            return result;

        }

        public static void Start(MitaClothes __instance)
        {
            __instance.dontDestroyStart = true;
        }
        public static void UpdateTest(GameController __instance)
        {
            if (Input.GetKeyInt(KeyCode.Alpha1))
            {
                SetClothes(Clothes.SchoolVariant1);
            }
            if (Input.GetKeyInt(KeyCode.Alpha2))
            {
                SetClothes(Clothes.SchoolVariant2);
            }
            if (Input.GetKeyInt(KeyCode.Alpha3))
            {
                SetClothes(Clothes.SchoolVariant3);
            }
            if (Input.GetKeyInt(KeyCode.Alpha4))
            {
                SetClothes(Clothes.Chirstmass);
            }
            if (Input.GetKeyInt(KeyCode.Alpha5))
            {
                SetClothes(Clothes.Vampire);
            }
        }
        static void SetClothes(Clothes cloth)
        {
            MelonLogger.Msg($"Try SetClothes");
            switch (cloth)
            {
                case Clothes.original:
                    GlobalGame.clothMita = "original";
                    GlobalGame.clothVariantMita = 0;
                    break;
                case Clothes.SchoolVariant1:
                    GlobalGame.clothMita = "FIIdClSchool";
                    GlobalGame.clothVariantMita = 0;
                    break;

                case Clothes.SchoolVariant2:
                    GlobalGame.clothMita = "FIIdClSchool";
                    GlobalGame.clothVariantMita = 1;
                    break;

                case Clothes.SchoolVariant3:
                    GlobalGame.clothMita = "FIIdClSchool";
                    GlobalGame.clothVariantMita = 2;
                    break;

                case Clothes.Chirstmass:
                    GlobalGame.clothMita = "Chirfns";
                    GlobalGame.clothVariantMita = 0;
                    break;

                case Clothes.Vampire:
                    GlobalGame.clothMita = "HellVamp";
                    GlobalGame.clothVariantMita = 0;
                    break;
            }

            currentClothes = cloth;
            ReCloth(MitaCore.Instance.MitaObject);
        }

        #region HairColor

        private static Shader originalShader;
        public static void init_hair()
        {
            try
            {
                hair_material = MitaCore.Instance.MitaPersonObject.transform.Find("Hair").GetComponent<Renderer>().material;
            }
            catch (Exception)
            {

                hair_material = MitaCore.Instance.MitaPersonObject.transform.Find("Hairs").GetComponent<Renderer>().material;
            }
            

            originalShader = hair_material.shader;
            hair_material.shader = Shader.Find("Legacy Shaders/Diffuse");
        }

        public static void setMitaHairColor(Color color)
        {
            try
            {
                if (hair_material == null) init_hair();

                hair_material.color = color;
               
            }

            catch (Exception e)
            {

                MelonLogger.Error(e);
            }
    

        }
        public static void resetMitaHairColor()
        {
            try
            {
                if (hair_material == null) init_hair();
                hair_material.shader = originalShader;
                hair_material.color = new Color(1,1,1,1);
            }

            catch (Exception e)
            {

                MelonLogger.Error(e);
            }


        }
        public static string getCurrentHairColor()
        {
            string result = "";
            if (hair_material == null) return null;
            if (hair_material.color == Color.white) return "hair_color normal";

            try
            {
                result = $"hair_color custom: r:{hair_material.color.r} g:{hair_material.color.g} b:{hair_material.color.b}";
            }
            catch (Exception ex)
            {
                MelonLogger.Error(ex);
                result = "";
                
            }

            return result;
        }

        #endregion

        private static void ReCloth(GameObject MitaObject)
        {
            try
            {
                var cloth = MitaObject.GetComponentInChildren<MitaClothes>();
                if (cloth != null) cloth.ReCloth();
            }
            catch (System.Exception globalEx)
            {
                MelonLogger.Error($": {globalEx.Message}");
            }
        }
    
    }

    
}
