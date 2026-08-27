using System;
using System.Collections.Generic;

namespace MitaAI
{
    public enum MitaStateType
    {
        normal,
        hunt,
        interaction
    }

    public class MitaState
    {
        private static Dictionary<characterType, MitaStateType> characterStates = new Dictionary<characterType, MitaStateType>();

        public static MitaStateType GetCurrentState(characterType characterType)
        {
            if (characterStates.TryGetValue(characterType, out MitaStateType state))
            {
                return state;
            }
            return MitaStateType.normal; // Возвращаем значение по умолчанию, если ключ не найден
        }

        public static void SetCurrentState(characterType characterType, MitaStateType newState)
        {
            characterStates[characterType] = newState;
        }

        public static bool IsMovingAvailable(characterType characterType)
        {
            return GetCurrentState(characterType) == MitaStateType.normal;
        }

        public static bool IsAnimationAvailable(characterType characterType)
        {
            return GetCurrentState(characterType) == MitaStateType.normal;
        }
    }
}