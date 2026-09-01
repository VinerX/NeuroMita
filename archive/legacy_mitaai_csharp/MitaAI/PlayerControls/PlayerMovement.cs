using Il2Cpp;
using MelonLoader;
using System;
using System.Collections;
using UnityEngine.UI;
using UnityEngine;
using MelonLoader.ICSharpCode.SharpZipLib;
using Il2CppSystem.Threading.Tasks;


namespace MitaAI
{
    public static class PlayerMovement
    {


        public static void onUpdate()
        {
            if (!MitaCore.isRequiredScene()) return;

            countTotalDistance();
            checkRoomChange();
        }


        private static Vector3 lastPosition;
        private static float totalDistance;
        private static bool isFirstFrame = true;
        private static void countTotalDistance()
        {
            try
            {
                // Получаем текущую позицию игрока
                Vector3 currentPosition = MitaCore.Instance.playerPersonObject.transform.position;

                if (isFirstFrame)
                {
                    lastPosition = currentPosition;
                    isFirstFrame = false;
                    return;
                }

                // Вычисляем расстояние между предыдущим и текущим положением
                float frameDistance = Vector3.Distance(lastPosition, currentPosition);
                totalDistance += frameDistance;

                // Обновляем предыдущую позицию
                lastPosition = currentPosition;


            }
            catch (Exception ex)
            {
                MelonLogger.Warning($"Ошибка при подсчете расстояния: {ex}");
            }
        }


        static Rooms lastRoom = Rooms.Unknown;
        private static void checkRoomChange()
        {

            Rooms currentRoom = MitaCore.Instance.GetRoomID(MitaCore.Instance.playerPersonObject.transform);

            if (currentRoom != lastRoom)
            {
                lastRoom = currentRoom;
                EventsModded.roomEnter(currentRoom, lastRoom);

                MelonLogger.Msg($"Change room from {lastRoom} to {currentRoom}");
                
            }

            


        }


        public static string getPlayerDistance(bool clear = false)
        {
            float distance = totalDistance;

            if (clear) totalDistance = 0f;

            return $"Player moved {distance.ToString("F2")} meters since last phrase";
        }
    
    }
    



}