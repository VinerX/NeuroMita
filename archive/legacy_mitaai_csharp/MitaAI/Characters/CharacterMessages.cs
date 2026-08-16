using Il2Cpp;
using MelonLoader;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.AccessControl;
using System.Text;
using System.Threading.Tasks;
using System.Xml.Serialization;
using UnityEngine;
using static Il2CppRootMotion.FinalIK.InteractionObject;

using UnityEngine.UI;
using UnityEngine.Device;
namespace MitaAI
{
    
    public static class CharacterMessages
    {
        public static Queue<(string, characterType)> systemMessages = new Queue<(string, characterType)>();
        public static LinkedList<(string, characterType)> systemInfos = new LinkedList<(string, characterType)>();

        public static void sendSystem(string m, bool info, characterType character = characterType.None)
        {
            if (info) sendSystemInfo(m, character);
            else sendSystemMessage(m, character);

        }
        public static void sendSystemMessage(string m, characterType character = characterType.None)
        {
            if (character == characterType.None) character = MitaCore.Instance.currentCharacter;
            systemMessages.Enqueue((m, character));

            EventsModded.registerLastEvent();
        }
        public static void sendSystemInfo(string m, characterType character = characterType.None)
        {

            if (character == characterType.None) character = MitaCore.Instance.currentCharacter;
            systemInfos.AddLast((m, character));
        }

        public static void sendInfoListeners(string message, List<characterType> characters = null, characterType exluding = characterType.None, string from = "Player")
        {
            MelonLogger.Msg($"sendInfoListeners {message} exluding {exluding} from {from}");

            if (characters == null) characters = CharacterControl.GetCharactersToAnswer(false);

            if (exluding == characterType.None) exluding = MitaCore.Instance.currentCharacter;


            string charName = CharacterControl.extendCharsString(exluding);

            if (CharacterControl.gameMaster != null) characters.Add(characterType.GameMaster);


            foreach (characterType character in characters)
            {
                MelonLogger.Msg($"sendInfoListeners {character}");
                string speakersText = CharacterControl.getSpeakersInfo(character);

                if (character != exluding)
                {
                    MelonLogger.Msg($"sendInfoListeners actually send {character}");
                    string messageToListener = "";
                    messageToListener += speakersText;

                    messageToListener += $"[SPEAKER] : {from} said: '{message}' and was answered by {charName}";
                    sendSystemInfo(messageToListener, character);
                }
            }


        }
        public static void sendInfoListenersFromGm(string message, List<characterType> characters = null, characterType exluding = characterType.None)
        {
            if (characters == null) characters = CharacterControl.GetCharactersToAnswer();

            if (exluding == characterType.None) exluding = MitaCore.Instance.currentCharacter;
            characterType from = characterType.GameMaster;

            string charName = CharacterControl.extendCharsString(exluding);




            foreach (characterType character in characters)
            {
                string speakersText = CharacterControl.getSpeakersInfo(character);

                if (character != exluding)
                {
                    string messageToListener = "";
                    messageToListener += speakersText;

                    messageToListener += $"[GAME_MASTER] : {from} said: {message}";


                    CharacterMessages.sendSystemInfo(messageToListener, character);
                }
            }
        }
    }
}
