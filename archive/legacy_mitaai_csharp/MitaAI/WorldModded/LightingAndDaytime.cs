using Il2Cpp;
using MelonLoader;
using System;
using System.Collections.Generic;
using UnityEngine;
using static Il2Cpp.Location21_World;

namespace MitaAI
{
    public static class LightingAndDaytime
    {
        private static GameObject newLightBedroom;
        private static GameObject newLightKitchen;
        public static Location21_World location21_World;
        public static LocationTimeDay TimeDay;
        public static Transform worldHouse;

        static Light sun;
        public static void Init(Location21_World _location21_World, Transform world)
        {
            worldHouse = world;
            location21_World = _location21_World;
            location21_World.timeDay = new LocationTimeDay();

            TimeDay = location21_World.timeDay;

            TimeDay.particlesDustRate = new AnimationCurve();
            TimeDay.particlesDustRate.AddKey(0, 0);
            TimeDay.particlesDustRate.AddKey(0.25f, 0);
            TimeDay.particlesDustRate.AddKey(0.375f, 1);
            TimeDay.particlesDustRate.AddKey(0.5f, 1);
            TimeDay.particlesDustRate.AddKey(0.625f, 1);
            TimeDay.particlesDustRate.AddKey(0.75f, 0);
            TimeDay.particlesDustRate.AddKey(1, 0);
            TimeDay.particlesDust = new UnityEngine.ParticleSystem[0];
            TimeDay.particleSunLight = new LocationTimeDayParticleLight[0];

            TimeDay.colorMorning = new Color(1, 0.7180627f, 0, 0.05f);
            TimeDay.colorSunMorning = new Color(1, 0.7180627f, 0, 0.05f);
            TimeDay.colorDay = new Color(1, 0.7631255f, 0.6367924f, 0.1490196f);
            TimeDay.colorSunDay = new Color(1, 0.7631255f, 0.6367924f, 0.1490196f);
            TimeDay.colorEvening = new Color(0.7877358f, 1, 0.9835733f, 0.05f);
            TimeDay.colorSunEvening = new Color(0.7877358f, 1, 0.9835733f, 0.05f);
            TimeDay.colorNight = new Color(0.130073f, 0.3779935f, 0.745283f, 0.01f);
            TimeDay.colorSunNight = new Color(0.130073f, 0.3779935f, 0.745283f, 0.01f);
            TimeDay.colorSunParticleNight = new Color(0, 0.3236856f, 0.3236856f, 0.1019608f);

            sun = worldHouse.Find("House/Sun").GetComponent<Light>();
            _location21_World.timeDay.sun = sun;





            //timeDay.colorNight = new UnityEngine.Color(0.0147073f, 1, 0.201f, 0.01f);
            //timeDay.colorSunNight = new UnityEngine.Color(0.0147073f, 1, 0.201f, 0.01f);
            //timeDay.colorNight = new UnityEngine.Color(0.02447287f, 0, 0.3207547f);
            //timeDay.colorSunNight = new UnityEngine.Color(0.02447287f, 0, 0.3207547f);

            TimeDay.colorNight = new Color(0.02447287f, 0, 0.3207547f);
            TimeDay.colorSunNight = new Color(0.02447287f, 0, 0.3207547f);

            //House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/
            try
            {
                mainLighting = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Main Lighting/").gameObject;
                toiletLighting = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Toilet Lighting/").gameObject;
            }
            catch (Exception)
            {
                MelonLogger.Msg("mainLighting or toiletLighting error ");
            }

            MelonLogger.Msg("End init lighting");
        }


        private static GameObject mainLighting;
        private static GameObject toiletLighting;
        private static GameObject bedroomLighting;
        private static GameObject kitchenLighting;

        public static void ChangeLight(bool on)
        {
            if (mainLighting != null) mainLighting.SetActive(on);
            if (toiletLighting != null) toiletLighting.SetActive(on);
            //if (bedroomLighting != null) bedroomLighting.SetActive(on);
            //if (newLightBedroom != null) newLightBedroom.SetActive(on);
            //if (kitchenLighting != null) kitchenLighting.SetActive(on);
            //if (newLightKitchen != null) newLightKitchen.SetActive(on);
        }
        public static void ChangeLightOld(bool on)
        {
            mainLighting = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Main Lighting/").gameObject;
            toiletLighting = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Toilet Lighting/").gameObject;
            //bedroomLighting = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Bedroom Lighting/PointLight Realtime").gameObject;
            //kitchenLighting = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Kitchen Lighting/PointLight Realtime").gameObject;


            var bedroom = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Bedroom Lighting/PointLight Realtime").gameObject;
            bedroom.SetActive(on);

            if (newLightBedroom == null)
            {
                newLightBedroom = UnityEngine.Object.Instantiate(bedroom, bedroom.transform.parent).gameObject;
                newLightBedroom.transform.position = new Vector3(bedroom.transform.position.x, bedroom.transform.position.z, 1);
            }
            newLightBedroom.SetActive(on);

            var kitchen = worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Kitchen Lighting/PointLight Realtime").gameObject;
            kitchen.SetActive(on);

            if (newLightKitchen == null)
            {
                newLightKitchen = UnityEngine.Object.Instantiate(kitchen, kitchen.transform.parent).gameObject;
                newLightKitchen.transform.position = new Vector3(kitchen.transform.position.x, kitchen.transform.position.z, 2.5f);
            }
            newLightKitchen.SetActive(on);
        }

        private static void ChangeMaterial(GameObject gameObject, Color color)
        {
            var mat = gameObject.GetComponent<MeshRenderer>().material;
            try
            {
                mat.SetColor("_Color", color);
                mat.SetColor("_EmissionColor", color);
            }
            catch (Exception e)
            {

                MelonLogger.Msg("ChangeMaterial error " + e);
            }

        }

        public static void ChangeQuadStreet(Color color)
        {
            try
            {
                ChangeMaterial(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom/QuadStreet 1").gameObject, color);
                ChangeMaterial(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/QuadStreet 2").gameObject, color);
                ChangeMaterial(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Kitchen/QuadStreet 1").gameObject, color);
                //ChangeMaterial(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Kitchen/QuadStreet 2").gameObject, color);
                //ChangeMaterial(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Kitchen/QuadStreet 3").gameObject, color);
                //ChangeMaterial(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Bedroom/QuadStreet 1").gameObject, color);
            }
            catch (Exception e)
            {

                MelonLogger.Msg(e);
            }

        }

        private static LocationTimeDayParticleLight InitParticleLight(ParticleSystem particleSystem)
        {
            return new LocationTimeDayParticleLight { particle = particleSystem };
        }

        public static void UpdateParticleDust()
        {
            //House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/
            try
            {
                var particleSystems = new List<LocationTimeDayParticleLight>
                {
                    //InitParticleLight(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Main Lighting/Sun Particles 1").gameObject.GetComponent<ParticleSystem>()),
                    //InitParticleLight(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Main Lighting/Sun Particles 2").gameObject.GetComponent<ParticleSystem>()),
                    InitParticleLight(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Bedroom Lighting/Sun Particles").gameObject.GetComponent<ParticleSystem>()),
                    InitParticleLight(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Kitchen Lighting/Sun Particles 1").gameObject.GetComponent<ParticleSystem>()),
                    InitParticleLight(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Kitchen Lighting/Sun Particles 2").gameObject.GetComponent<ParticleSystem>()),
                    InitParticleLight(worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Kitchen Lighting/Sun Particles 3").gameObject.GetComponent<ParticleSystem>())
                };
                TimeDay.particleSunLight = particleSystems.ToArray();
            }
            catch (Exception e)
            {

                MelonLogger.Msg("particleSystems" + e);
            }

            //House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/
            try
            {
                var dusts = new List<ParticleSystem>
            {
                worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Main Lighting/Particles Dust").gameObject.GetComponent<ParticleSystem>(),
                worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Bedroom Lighting/Particles Dust").gameObject.GetComponent<ParticleSystem>(),
                worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Kitchen Lighting/Particles Dust").gameObject.GetComponent<ParticleSystem>(),
                worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/Lighting/Toilet Lighting/Particles Dust").gameObject.GetComponent<ParticleSystem>()
            };

                TimeDay.particlesDust = dusts.ToArray();
            }
            catch (Exception e)
            {

                MelonLogger.Msg("dusts" + e);
            }



        }

        public static void CheckDay()
        {
            if (TimeDay == null || location21_World == null) return;

            try
            {
                if (TimeDay.particlesDust.Length <= 0)
                {
                    UpdateParticleDust();
                }
            }
            catch (Exception e)
            {

                MelonLogger.Msg("UpdateParticleDust error " + e);
            }


            try
            {
                if (true)
                {
                    foreach (var pd in TimeDay.particlesDust)
                    {
                        var emission = pd.emission;
                        emission.rateOverTime = TimeDay.particlesDustRate.Evaluate(location21_World.dayNow) * 100.0f;
                    }
                }

            }
            catch (Exception e)
            {

                MelonLogger.Msg("foreach error " + e);
            }



            try
            {

                HandleDayTransitions();
            }
            catch (Exception e)
            {

                MelonLogger.Msg("HandleDayTransitions error " + e);
            }



        }

        private static void HandleDayTransitions()
        {
            if (location21_World == null) return;

            if (location21_World.dayNow >= 0 && location21_World.dayNow < 0.25f)
            {
                TransitionDayPhase(TimeDay.colorNight, TimeDay.colorMorning, TimeDay.colorSunNight, TimeDay.colorSunMorning, 4f);
                ChangeLight(true);
            }
            else if (location21_World.dayNow < 0.5f)
            {
                TransitionDayPhase(TimeDay.colorMorning, TimeDay.colorDay, TimeDay.colorSunMorning, TimeDay.colorSunDay, 4f);
                ChangeLight(false);
            }
            else if (location21_World.dayNow < 0.75f)
            {
                TransitionDayPhase(TimeDay.colorDay, TimeDay.colorEvening, TimeDay.colorSunDay, TimeDay.colorSunEvening, 4f);
            }
            else
            {
                TransitionDayPhase(TimeDay.colorEvening, TimeDay.colorNight, TimeDay.colorSunEvening, TimeDay.colorSunNight, 4f);
                ChangeLight(true);
            }
        }

        private static void TransitionDayPhase(Color startColor, Color endColor, Color startSunColor, Color endSunColor, float multiplier)
        {
            var v6 = location21_World.dayNow % 0.25f * multiplier;
            var v12 = Mathf.Clamp01(v6);


            RenderSettings.ambientSkyColor = Color.Lerp(startColor, endColor, v12);


            // Логирование параметров
            MelonLogger.Msg($"Parameters: startColor={startColor}, endColor={endColor}, v12={v12}");

            if (sun == null) sun = worldHouse.Find("House/Sun").GetComponent<Light>();
            sun.color = Color.Lerp(startSunColor, endSunColor, v12);

            foreach (var psl in TimeDay.particleSunLight)
            {

                var main = psl.particle.main;
                main.startColor = Color.Lerp(startSunColor, endSunColor, v12);
            }


            ChangeQuadStreet(Color.Lerp(TimeDay.colorSunParticleNight, TimeDay.colorSunParticleMorning, v12));

        }

        public static void applyColor(Color c)
        {
            location21_World.timeDay.colorDay = c;
            location21_World.SetTimeDay(0.5f);
        }
        public static void resetDayColor()
        {
            if (location21_World.timeDay != null)
            {
                try
                {
                    location21_World.timeDay.colorDay = new Color(1, 0.7631255f, 0.6367924f, 0.1490196f);
                }
                catch (Exception)
                {


                }
            }


        }
        public static void setTimeDay(float time)
        {
            if (location21_World == null)
            {
                MelonLogger.Warning("NET TUT ETOGO OBJECTA!!!");
            }

            resetDayColor();
            location21_World.day = time;
            MelonLogger.Warning($"000 Time {time}");
            location21_World.SetTimeDay(time);

            CheckDay();
        }

    }
}