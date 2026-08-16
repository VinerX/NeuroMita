using UnityEngine;
using System.Collections;
using MelonLoader;


namespace MitaAI
{
    [RegisterTypeInIl2Cpp]
    public class Chair : MonoBehaviour
    {
        private bool isCloseToTable = true;
        private float moveDistance = 0.4f; // Расстояние для перемещения
        private float animationDuration = 0.8f; // Длительность анимации

        public void moveChair()
        {
            float yRotation = transform.eulerAngles.y; // Текущий угол поворота по Y (0-360°)
            float directionMultiplier = -Mathf.Sign(Mathf.Cos(yRotation * Mathf.Deg2Rad));

            Vector3 localMovement = Vector3.right * moveDistance * (isCloseToTable ? 1 : -1) * directionMultiplier;
            Utils.StartObjectAnimation(gameObject, localMovement, Vector3.zero, animationDuration, true);

            isCloseToTable = !isCloseToTable;
        }
    }
}