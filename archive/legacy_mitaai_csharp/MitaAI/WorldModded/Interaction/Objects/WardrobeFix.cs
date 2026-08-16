using UnityEngine;
using System.Collections;
using MelonLoader;
using MitaAI.Mita;

namespace MitaAI
{

    [RegisterTypeInIl2Cpp]
    public class WardrobeFix : MonoBehaviour
    {
        // Единственная цель этого класса - возможность миты проходить в подвал и обратно

        private float moveDuration = 1.3f; // Время перемещения
        private float moveDistance = 1.65f; // Дистанция перемещения

        private bool active = false;

        void Update()
        {

            //MelonLogger.Msg("Update");
            GameObject Mita = MitaCore.Instance.MitaPersonObject;
            if (Mita == null) return;

            if (Utils.getDistanceBetweenObjects(Mita,this.gameObject)<0.78f && !active)
            {

                MelonLogger.Msg("Mita wardrobe fix");
                
                // Если у миты Z больше, она в комнате
                float zDirection = (Mita.transform.position.z > this.transform.position.z) ? -1 : 1;

                // Запускаем последовательность перемещений
                MelonCoroutines.Start(MovementSequence(zDirection, Mita));
                active = true;
            }
        }


        private void OnTriggerEnter(Collider other)
        {
            try
            {
                MelonLogger.Msg($"Deect {other.gameObject.name}");
                // Определяем направление по Z
                if (other || !other.gameObject.name.Contains("Mita")) return;

                MelonLogger.Msg("Mita");
                float zDirection = (other.transform.position.z > transform.position.z) ? 1 : -1;

                // Запускаем последовательность перемещений
                MelonCoroutines.Start(MovementSequence(zDirection, other.gameObject));
            }
            catch (Exception e)
            {

                MelonLogger.Error($"Deect error {e}");
            }
           
        }

        private IEnumerator MovementSequence(float direction, GameObject targetObject)
        {
            // Первый этап: движение к центру
            //MitaAnimationModded.EnqueueAnimation("Walk");

            yield return MelonCoroutines.Start(MoveObject(targetObject.transform,direction * moveDistance,moveDuration));

            // Второй этап: движение за край
            //yield return MelonCoroutines.Start(MoveObject(targetObject.transform,-direction * moveDistance,direction,moveDuration));

            MitaCore.Instance.Mita.AiShraplyStop();

            yield return new WaitForSeconds(1f);
            active = false;

            
        }

        private IEnumerator MoveObject(Transform obj, float distance, float duration)
        {
            Vector3 startPos = obj.position;
            Vector3 endPos = startPos + new Vector3(0, 0, distance);

            float elapsed = 0f;

            while (elapsed < duration)
            {
                obj.position = Vector3.Lerp(startPos, endPos, elapsed / duration);
                elapsed += Time.deltaTime;
                yield return null;
            }

            obj.position = endPos;
        }
    }
}