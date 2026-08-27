using MelonLoader;
using Il2Cpp;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;


namespace MitaAI
{

    [RegisterTypeInIl2Cpp]
    public class Character : MonoBehaviour
    {
        public characterType characterType;
        public bool isCartdige;
        public int PointsOrder = 0;

        public void init(characterType character)
        {
            this.characterType = character;
            CharacterControl.Characters.Add(this);
        }
        public void init_cartridge()
        {

            this.isCartdige = true;
            init(CharacterControl.get_cart());

        }
        public void changeActivation()
        {
            enabled = !enabled;
            if (isCartdige) 
            {
                if (enabled)
                {
                    CharacterMessages.sendSystemMessage($"Тебя только что включили", characterType);
                }
                else
                {
                    CharacterMessages.sendSystemInfo($"Тебя выключили", characterType);
                }
            }
            

        }

        public void DecreseOrderPoints(int n = 25)
        {
            PointsOrder -= n;
        }

    }

    [RegisterTypeInIl2Cpp]
    public class GameMaster : Character
    {
        public void init_GameMaster()
        {
            characterType = characterType.GameMaster;
            //CharacterControl.Characters.Add(this);
            CharacterControl.gameMaster = this;
        }

        public int timingEach = 3;
        int timingNow = 1;

        bool lastTimeWasGM = false;
        public bool CheckInreaseTiming()
        {
            if (lastTimeWasGM)
            {
                lastTimeWasGM = false;
                return false;
            }
            

            bool isIt = timingNow+1 >= timingEach;


            if (isIt)
            {
                lastTimeWasGM = true;
                timingNow = 1;
            }

            else timingNow += 1;
            
            

            return isIt;

        }
        public bool isTimeToCorrect(int addition)
        {
            return (timingNow + addition) % timingEach == 0;
        }

    }
}
