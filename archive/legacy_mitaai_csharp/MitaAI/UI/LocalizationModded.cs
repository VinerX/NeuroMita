using Il2Cpp;
using MelonLoader;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine.Events;
using UnityEngine;
using UnityEngine.Playables;
using Microsoft.VisualBasic;
using UnityEngine.UI;
using MitaAI.PlayerControls;
using MitaAI;
using System.Diagnostics;
using System.ComponentModel.DataAnnotations;

namespace MitaAI
{


    public class LocalizationModded
    {
        public static string Language = "RU";

        public static void init()
        {
            //try
            //{
            //    switch (GlobalGame.Language){
            //        case "English":
            //            Language = "EN";
            //            break;
            //        case "Russian":
            //            Language = "RU";
            //            break;
            //        default:
            //            Language = Settings.Get<String>("Language");
            //            break;
            //    }
            //}
            //catch (Exception)
            //{
                Language = Settings.Get<String>("Language");
            //}

           

        }

        public static void setLanguage(string language)
        {

            if (string.IsNullOrEmpty(language)) return;

            if (language.ToUpper() != Language)
            {

                Language = language;
                Settings.Set("Language", Language);
            }


        }

    }

    public static class loc
    {
        public static string _(string ru = "", string en = "")
        {
            switch (LocalizationModded.Language)
            {
                case "RU":
                    return ru;
                case "EN":
                    if (string.IsNullOrEmpty(en)) return ru;
                    return en;
            }
            return ru;
        }
    }
}
