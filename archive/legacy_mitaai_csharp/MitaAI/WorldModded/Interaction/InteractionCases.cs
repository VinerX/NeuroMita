using System;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Collections;
using MelonLoader;
using UnityEngine;
using Il2Cpp;
namespace MitaAI.WorldModded
{
    public static class InteractionCases
    {
        static bool ConsoleStarted = false;
        public static void caseConsoleStart(GameObject console)
        {
            if (ConsoleStarted) return;
            
            console.GetComponent<ObjectInteractive>().enabled = false;
            MelonCoroutines.Start(caseConsoleAct(console));
            ConsoleStarted = true;

        }
        public static void caseConsoleStart()
        {
            GameObject console = GameObject.Find("Console");
            if (ConsoleStarted) return;

            console.GetComponent<ObjectInteractive>().enabled = false;
            MelonCoroutines.Start(caseConsoleAct(console));
            ConsoleStarted = true;

        }

        public static void sofaStart(GameObject gameObject)
        {
            
            MelonLogger.Msg($"SofaSit");

            gameObject.GetComponent<ObjectInteractive>().enabled = false;

            if (PlayerAnimationModded.currentPlayerMovement != PlayerMovementType.sit)
            {
                PlayerAnimationModded.currentPlayerMovement = PlayerMovementType.sit;
                PlayerAnimationModded.playAnimObject(gameObject);
            }         
           
        }


        public static IEnumerator caseConsoleAct(GameObject console)
        {

            MelonLogger.Msg("caseConsoleAct");
            try
            {
                MitaCore.Instance.playerObject.transform.Find("LeftItem FixPosition/Console/ConsoleCup/ScreenWork").gameObject.active = false;
            }
            catch (Exception e)
            {

                MelonLogger.Error(e);
            }
            
            
            yield return new WaitForSeconds(1.5f);

            try
            {
                CharacterMessages.sendSystemMessage("Твою консоль только что открыли.", CharacterControl.get_cart());
            }
            catch (Exception e)
            {

                MelonLogger.Error(e);
            }
           

            var Button1 = Utils.TryfindChild(MitaCore.worldBasement, "Quests/Quest1 Start/3D HintKey FindButton");

            Button1.active = true;

            //var Button1_res = GameObject.Instantiate(Button1);
            //var Button2_res = GameObject.Instantiate(Button2);

            //Button1_res.active = false; Button2_res.active = false;




            while (Button1!=null)
            {
                yield return new WaitForSeconds(0.25f);
            }
            CharacterMessages.sendSystemMessage("Игрок ищет кнопку выключения консоли, если он выключит тебя, то сможет поговорить с тобой только при перезапуске.", CharacterControl.get_cart());
            
            var Button2 = Utils.TryfindChild(MitaCore.worldBasement, "Quests/Quest1 Start/3D HintKey Holding");
            while (Button2 != null)
            {
                yield return new WaitForSeconds(0.25f);
            }
            
            if (MitaCore.Instance.getDistanceToPlayer()<6f) CharacterMessages.sendSystemMessage("Игрок при тебе просмотрел твой картридж другого игрока в подвале. У него могут быть вопросы, надо как-то уйти от темы. Если он будет наставить, придется сбросить маску.");
            else CharacterMessages.sendSystemInfo("Игрок просмотрел твой картридж другого игрока в подвале пока ты была не рядом. У него могут быть вопросы, если он спросит надо как-то уйти от темы. Если он будет наставить, придется сбросить маску.");
            CharacterMessages.sendSystemInfo("Игрок выключил тебя", CharacterControl.get_cart());

            yield return new WaitForSeconds(1f);
            /*console.GetComponent<ObjectInteractive>().active = true;

            Button1.transform.SetParent(MitaCore.worldBasement.Find("Quests/Quest1 Start"));
            Button2_res.transform.SetParent(MitaCore.worldBasement.Find("Quests/Quest1 Start"));
            Button1_res.name = "3D HintKey FindButton";
            Button2_res.name = "3D HintKey Holding";

            Transform consoleParent = console.transform.parent;

            GameObject console_res = consoleParent.Find(console.name + "_res").gameObject;
            GameObject.Destroy(console);
            console_res.active = true;
*/

        }

    }
}
