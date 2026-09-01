using Il2Cpp;
using MelonLoader;
using MitaAI.Mita;
using MitaAI.PlayerControls;
using System;
using System.Collections;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.AI;
using static MelonLoader.MelonLogger;
using static MitaAI.MitaCore;

namespace MitaAI
{
    public static class CurrentInfoControl
    {
        public static string currentInfo = "";
        public static void prepareForSend()
        {

            if (MitaCore.Instance.currentCharacter == characterType.GameMaster)
            {
                currentInfo = formCurrentInfoGameMaster();
                return;
            }

            try
            {
                if (Vector3.Distance(MitaCore.Instance.Mita.transform.GetChild(0).position, MitaCore.Instance.lastPosition) > 2f)
                {

                    MitaCore.Instance.lastPosition = MitaCore.Instance.Mita.transform.GetChild(0).position;
                    List<string> excludedNames = new List<string> { "Hips", "Maneken" };
                    if (MitaCore.Instance.roomMita == Rooms.Basement) MitaCore.Instance.hierarchy = ObjectHierarchyHelper.GetObjectsInRadiusAsTree(MitaCore.Instance.Mita.gameObject, 10f, worldBasement.Find("House").transform, excludedNames);
                    else MitaCore.Instance.hierarchy = ObjectHierarchyHelper.GetObjectsInRadiusAsTree(MitaCore.Instance.Mita.gameObject, 10f, worldHouse.Find("House").transform, excludedNames);

                    //MelonLogger.Msg(hierarchy);


                }
                if (string.IsNullOrEmpty(MitaCore.Instance.hierarchy)) MitaCore.Instance.hierarchy = "-";

                MitaCore.Instance.distance = MitaCore.Instance.getDistanceToPlayer();
                MitaCore.Instance.roomPlayer = MitaCore.Instance.GetRoomID(MitaCore.Instance.playerPerson.transform);
                MitaCore.Instance.roomMita = MitaCore.Instance.GetRoomID(MitaCore.Instance.Mita.transform);

                try
                {
                    currentInfo = formCurrentInfo();
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"formCurrentInfo error {ex}");
                    currentInfo = "";
                }

            }
            catch (Exception ex)
            {

                MelonLogger.Error($"prepareForSend {ex}");
            }

        }


        public static string formCurrentInfo()
        {

            string info = "-";
            try
            {

                if (MitaCore.Instance.MitaPersonObject != null) info += $"Your game object name is <{MitaCore.Instance.MitaPersonObject.name}>\n";
                info += $"Current movement type: {MitaMovement.GetMovementStyle(MitaCore.Instance.currentCharacter).ToString()}\n";

                var mitaAnimationModded = MitaAnimationModded.getMitaAnimationModded(MitaCore.Instance.currentCharacter);

                if (mitaAnimationModded.currentIdleAnim != "") info += $"Current idle anim: {mitaAnimationModded.currentIdleAnim}\n";
                if (mitaAnimationModded.currentIdleAnim == "Mita Fall Idle") info += "You are fall, use another idle animation if want to end this animaton!\n";
                if (mitaAnimationModded.currentIdleAnim == "Mila CryNo") info += "You are sitting and crying, use another idle animation if want to end this animaton!\n";

                info += $"Current emotion anim: {DialogueControl.currentEmotion}\n";

                try
                {
                    var glasses = MitaCore.Instance.MitaPersonObject.transform.Find("World/Acts/Mita/MitaPerson/Head/Mita'sGlasses").gameObject;
                    info += $"Очки: {(glasses.activeSelf ? "надеты" : "сняты")}\n";
                    // хз что то попробовал ниже но не уверен
                    if (glasses.activeSelf)
                    {
                        info += "you put on glasses, if you want to take them off use the command remove glasses.\n";
                    }
                    else
                    {
                        info += "you took off glasses, if you want to put them on use the command put on glasses.\n";
                    }
                }
                catch (Exception) { }

                MelonLogger.Msg("CurrentInfo 2");


                if (MitaState.GetCurrentState(MitaCore.Instance.currentCharacter) == MitaStateType.hunt) info += $"You are hunting player with knife:\n";

                info += $"Your size: {MitaCore.Instance.MitaPersonObject.transform.localScale.x}\n";
                info += $"Your speed: {MitaCore.Instance.MitaPersonObject.GetComponent<NavMeshAgent>().speed}\n";

                if (MitaCore.Instance.getDistanceToPlayer() > 50f) info += $"You are outside game map, player dont hear you, you should teleport somewhere\n";

                info += $"Player size: {MitaCore.Instance.playerObject.transform.localScale.x}\n";
                info += $"Player speed: {MitaCore.Instance.playerObject.GetComponent<PlayerMove>().speedPlayer}\n";

                if (false)
                {
                    info += $"Game house time (%): {MitaCore.Instance.location21_World.dayNow}\n";
                    info += $"Current lighing color: {MitaCore.Instance.location21_World.timeDay.colorDay}\n";
                }

                if (MitaGames.activeMakens.Count > 0) info = info + $"Menekens count: {MitaGames.activeMakens.Count}\n";
                info += AudioControl.MusicInfo();
                info += $"Your clothes: {MitaClothesModded.currentClothes}\n";

                info += MitaClothesModded.getCurrentHairColor();
                if (PlayerAnimationModded.currentPlayerMovement == PlayerMovementType.sit) info += $"Player is sitting\n";
                else if (PlayerAnimationModded.currentPlayerMovement == PlayerMovementType.taken) info += $"Player is in your hand. you can throw him using <a>Скинуть игрока</a>\n";

                info += PlayerMovement.getPlayerDistance(true);

                try
                {
                    info += MitaCore.Instance.GetLocations();
                    info += Interactions.getObservedObjects();
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"CurrentInfo 6.5 {ex}");
                }



                if (HintText != null) info += $"Current player's hint text {HintText.text}";

                try
                {
                    info += CharacterControl.getSpeakersInfo(MitaCore.Instance.currentCharacter);
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"CurrentInfo getSpeakersInfo{ex}");
                }


                try
                {
                    info += ObjectAnimationMita.interactionGetCurrentInfo(MitaCore.Instance.currentCharacter);
                    
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"interactionGetCurrentInfo {ex}");
                }
                try
                { 
                    info += MitaGames.getGameInfo();
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"MitaGames {ex}");
                }


                info += MitaFaceAnimationModded.getFaceInfo(MitaCore.Instance.MitaPersonObject);
            }
            catch (Exception ex)
            {

                MelonLogger.Error($"formCurrentInfo {ex}");
            }
            return info;
        }
        public static string formCurrentInfoGameMaster()
        {

            string info = "-";
            try
            {


                try
                {
                    info += CharacterControl.getSpeakersInfo(MitaCore.Instance.currentCharacter);
                }
                catch (Exception ex)
                {

                    MelonLogger.Error($"CurrentInfo getSpeakersInfo{ex}");
                }




            }
            catch (Exception ex)
            {

                MelonLogger.Error($"formCurrentInfo {ex}");
            }
            return info;
        }


    }
}
