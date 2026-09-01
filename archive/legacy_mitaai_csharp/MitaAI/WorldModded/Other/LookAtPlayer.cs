using MelonLoader;
using UnityEngine;

namespace MitaAI
{
    [RegisterTypeInIl2Cpp]

    public class LookAtPlayer : MonoBehaviour
    {
        static Transform playerTransform;
        public bool flipSprite = true; // Для 2D объектов с рендерером
        public float rotationOffset = 0f; // Дополнительный поворот

        public static void Init(Transform _playerTransform)
        {
            playerTransform = _playerTransform;
        }

        void Update()
        {
            if (playerTransform != null)
            {
                // Разворачиваем объект в сторону игрока
                Vector3 direction = playerTransform.position - transform.position;

                // Для 3D объектов
                if (direction != Vector3.zero)
                {
                    Quaternion lookRotation = Quaternion.LookRotation(direction);
                    transform.rotation = Quaternion.Euler(0f, 0f, lookRotation.eulerAngles.y + rotationOffset);
                }

                // Для 2D спрайтов
                if (flipSprite)
                {
                    SpriteRenderer spriteRenderer = GetComponent<SpriteRenderer>();
                    if (spriteRenderer != null)
                    {
                        spriteRenderer.flipX = direction.x < 0;
                    }
                }
            }
        }
    }
}
