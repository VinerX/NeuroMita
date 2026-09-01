using Il2Cpp;
using Il2CppSteamworks;
using MelonLoader;
using MitaAI.Mita;
using System;
using System.Collections;
using System.ComponentModel;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.SocialPlatforms.Impl;
using static MitaAI.EventsModded;


namespace MitaAI
{
    public static class TVModded
    {

        public static MinigamesTelevisionController minigamesTelevisionController;
        static bool KeysActive = false;
        private static MinigamesTelevisionGame minigamesTelevisionGame;
        private static MT_GameCnowballs mT_GameCnowballs;
        private static Location4Fight mT_Location4Fight;
        static GameObject GamepadBlue;

        public static string getSnowsString()
        {
            string s = $"You are playing funny game third person game, where you try to collect as many snows ass possible as a pingunue";

            return s;
        }
        public static string getMilkString()
        {
            string s = $"You are playing funny fighter game with milk packadges as avatars";
            s += getMilkScoreString();

            return s;
        }

        public static void SetTVController()
        {

            MelonLogger.Msg("SetTVController");

            minigamesTelevisionController = MitaCore.worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/TV/GameTelevision").GetComponent<MinigamesTelevisionController>();
            minigamesTelevisionController.CanTalkAboutGame(false);
            minigamesTelevisionController.destroyAfter = false;
            

            var Menu = MitaCore.worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/TV/Interface Hint/Menu");
            
            
            var ExitEvent = Menu.transform.Find("Exit").GetComponent<Interface_KeyHint_Key>().eventKeyDown;
            Menu.transform.localPosition = new Vector3(0, 125, 0);
            ExitEvent.RemoveAllListeners();

            ExitEvent.AddListener((UnityAction)TurnControlKeys);
            //minigamesTelevisionController.keysMenu

            
            GamepadBlue = MitaCore.worldHouse.Find("House/HouseGameNormal Tamagotchi/HouseGame Tamagotchi/House/Main/GamepadBlue").gameObject;

            MelonLogger.Msg("Trying set PlayGame");
            minigamesTelevisionController.interfaceKeys.Find("Menu/Change").GetComponent<Interface_KeyHint_Key>().eventKeyDown.AddListener((UnityAction)PlayGame);
            minigamesTelevisionController.timeActivation = 0.1f;


        }

        public static void turnTV()
        {

            if (!minigamesTelevisionController.activation)
            {
                minigamesTelevisionController.StartTelevision();
                CharacterMessages.sendSystemMessage("Player turned on TV (for games), maybe you should sit on sofa using interaction.");
                //MelonCoroutines.Start(startKeysMenu());
            }
            else
            {
                minigamesTelevisionController.StopTelevision();
                CharacterMessages.sendSystemMessage("Player turned off TV (for games)");
            }

        }
        public static void TurnControlKeys()
        {
            KeysActive = !KeysActive;

            minigamesTelevisionController.KeysMenuActive(KeysActive);


            if (GamepadBlue == null)
            {
                MelonLogger.Warning("GamepadBlue was null");
                GamepadBlue = GameObject.Find("GamepadBlue").gameObject;
            }


            if (KeysActive)
            {
                PlayerHands.TakeInHand(GamepadBlue,true,new Vector3(0,0,-0.08f),Vector3.zero);
                CharacterMessages.sendSystemInfo("Player took gamepad in hand");
            }
            else
            {
                PlayerHands.Free(GamepadBlue, true);
                CharacterMessages.sendSystemInfo("Player returned gamepad to its place");
            }
            
        }

        static void PlayGame()
        {
            MelonLogger.Msg("Try PlayGame");
            MelonCoroutines.Start(startGame());
        }

        static IEnumerator startKeysMenu()
        {
            yield return new WaitForSeconds(1f);
            TurnControlKeys();
        }

        static IEnumerator startGame()
        {
           

            minigamesTelevisionGame = UnityEngine.Object.FindObjectOfType<MinigamesTelevisionGame>();
            
            CharacterMessages.sendSystemMessage($"TV game '{minigamesTelevisionController.textNeedNameGame}' is loading. Use <interaction> to sofa, if you want to play with him");

            while (minigamesTelevisionGame == null)
            {
                minigamesTelevisionGame = UnityEngine.Object.FindObjectOfType<MinigamesTelevisionGame>();
                
                yield return new WaitForSeconds(1);
            }
            mT_GameCnowballs = minigamesTelevisionGame.objectGame.GetComponent<MT_GameCnowballs>();
            mT_Location4Fight = minigamesTelevisionGame.objectGame.GetComponent<Location4Fight>();


            minigamesTelevisionController.PlayGame();

            while (minigamesTelevisionGame != null)
            {
                if (mT_GameCnowballs != null) yield return MelonCoroutines.Start(processSnowBalls());
                else if (mT_Location4Fight != null) yield return MelonCoroutines.Start(processMilk());

                yield return new WaitForSeconds(0.25f);
            }

        }

        static int GamesPlayed = 0;
        static bool isFinished()
        {
            if (GamesPlayed>=2) return true;
            else
            {
                GamesPlayed = GamesPlayed + 1;
                return false;
            }
        }

        static IEnumerator processSnowBalls()
        {
            MitaGames.currentGame = MitaGame.Snows;

            if (mT_GameCnowballs.resultShow)
            { 

                if (mT_GameCnowballs.scoreMita < mT_GameCnowballs.scorePlayer) CharacterMessages.sendSystemMessage($"Player (Score {mT_GameCnowballs.scorePlayer}) won round of game of Snow collecting (Your score {mT_GameCnowballs.scoreMita})");
                else CharacterMessages.sendSystemMessage($"You won (Score {mT_GameCnowballs.scoreMita}) round of game of Snow collecting (Player score {mT_GameCnowballs.scorePlayer})");

            
                if (mT_GameCnowballs.countPlayed == 4)
                {
                    CharacterMessages.sendSystemMessage("You and player finished game");

                    yield return new WaitForSeconds(5f);

                    mT_GameCnowballs.Continue();


                    if (isFinished()) turnTV();
                    else minigamesTelevisionController.KeysMenuActive(true);
                    
                    yield break;
                }

                yield return new WaitForSeconds(5f);

                mT_GameCnowballs.RestartWorld();
                mT_GameCnowballs.PlayTimeStart();
            }
        }

        static int scorePlayer = 0;
        static int scoreMita = 0;

        static IEnumerator processMilk()
        {
            MitaGames.currentGame = MitaGame.Milk;

            mT_Location4Fight.enemyComplexity = 11;

            if (mT_Location4Fight.win) {

                if (mT_Location4Fight.winG >= 4 || mT_Location4Fight.loseG >= 4)
                {
                    if (mT_Location4Fight.winG == 4) CharacterMessages.sendSystemMessage("You won game of Milk fight");
                    else CharacterMessages.sendSystemMessage($"Player won game of Milk fight"); 

                    yield return new WaitForSeconds(5f);

                    mT_Location4Fight.Continue();

                    if (isFinished()) turnTV();
                    else minigamesTelevisionController.KeysMenuActive(true);
                    
                    yield break;
                }


                if (mT_Location4Fight.winG == scorePlayer) CharacterMessages.sendSystemMessage($"You won round in the game of Milk fight.");
                else CharacterMessages.sendSystemMessage($"Player won round in the game of Milk fight."); 

                scorePlayer = mT_Location4Fight.winG;
                scoreMita = mT_Location4Fight.loseG;

                yield return new WaitForSeconds(5f);

                mT_Location4Fight.ResetGame();
                
            

            }
        }


        static string getMilkScoreString()
        {
            return $"Your score {mT_Location4Fight.loseG}/4, players {mT_Location4Fight.winG}/4.";
        }

    }

    //[HarmonyLib.HarmonyPatch]
    //public static class MinigamesTelevisionControllerModdded
    //{


    //    [HarmonyLib.HarmonyPatch(typeof(Il2Cpp.MinigamesTelevisionController), "Start")]
    //    [HarmonyLib.HarmonyPostfix]
    //    private static void Postfix2()
    //    {
    //        TVModded.minigamesTelevisionController.PlayGame();

    //    }
    //}
}
