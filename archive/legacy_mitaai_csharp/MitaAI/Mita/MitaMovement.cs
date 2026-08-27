using Il2Cpp;

using MelonLoader;
using System.Collections;
using UnityEngine;
using System.Text.RegularExpressions;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine.Playables;
using UnityEngine.AI;
using Il2CppRootMotion.FinalIK;
using UnityEngine.Events;
using MitaAI.Mita;
using static UnityEngine.TextEditor;

namespace MitaAI
{
    public enum MovementStyles
    {
        walkNear = 0,
        follow = 1,
        stay = 2,
        noclip = 3,
        layingOnTheFloorAsDead = 4,
        sitting,
        cryingOnTheFloor

    }

    public class MitaMovement
    {
        private static Dictionary<characterType, MovementStyles> movementStyles = new Dictionary<characterType, MovementStyles>();       

        public static MovementStyles GetMovementStyle(characterType characterType) { 
            
            if (movementStyles.ContainsKey(characterType)) return movementStyles[characterType];
            else movementStyles[characterType] = MovementStyles.walkNear;
            return movementStyles[characterType];
        }
        public static void setMovementStyle(characterType characterType, MovementStyles style) { movementStyles[characterType] = style; }
       
        
        public static string FindMovementStyle(characterType characterType,string response)
        {
            // Регулярное выражение для извлечения эмоций
            string pattern = @"<m>(.*?)</m>";
            Match match = Regex.Match(response, pattern);

            string MovementStyle = string.Empty;
            string cleanedResponse = Regex.Replace(response, @"<m>.*?</m>", ""); // Очищаем от всех тегов

            if (match.Success)
            {
                // Если эмоция найдена, устанавливаем её в переменную faceStyle
                MovementStyle = match.Groups[1].Value;
            }
            try { 
            
                var Mita = MitaCore.getMitaByEnum(characterType);
            // Проверка на наличие объекта Mita перед применением эмоции
                if (Mita == null)
                {

                    MelonLogger.Error("Mita object is null or Mita.gameObject is not active.");
                    return cleanedResponse; // Возвращаем faceStyle и очищенный текст
                }
                
                var MitaAnimation = MitaAnimationModded.getMitaAnimationModded(characterType);
                // Устанавливаем лицо, если оно найдено
                switch (MovementStyle)
                {
                    case "Следовать рядом с игроком":
                        ObjectAnimationMita.finishWorkingOAM();
                        movementStyles[characterType] = MovementStyles.walkNear;
                        MitaAnimation.location34_Communication.ActivationCanWalk(true);
                        break;
                    case "Следовать за игроком":
                        ObjectAnimationMita.finishWorkingOAM();
                        movementStyles[characterType] = MovementStyles.follow;
                        MitaAnimation.location34_Communication.ActivationCanWalk(false);
                        MelonCoroutines.Start(FollowPlayer(MitaAnimation));
                        MelonCoroutines.Start(LookOnPlayer(MitaAnimation));
                        break;
                    case "Стоять на месте":
                        ObjectAnimationMita.finishWorkingOAM();
                        MitaSetStaing(characterType);
                        break;
                    case "NoClip":
                        ObjectAnimationMita.finishWorkingOAM();
                        movementStyles[characterType] = MovementStyles.noclip;
                        MitaAnimation.location34_Communication.ActivationCanWalk(false);
                        MelonCoroutines.Start(FollowPlayerNoclip(characterType));
                        break;
                    default:
                        break;
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Error($"Problem with SetMovementStyle: {ex.Message}");
            }

            // Возвращаем кортеж: лицо и очищенный текст
            return cleanedResponse;
        }
        public static void MitaSetStaing(characterType characterType)
        {
            movementStyles[characterType] = MovementStyles.stay;

            var MitaAnim = MitaAnimationModded.getMitaAnimationModded(characterType);
            MitaAnim.location34_Communication.ActivationCanWalk(false);
            MelonCoroutines.Start(LookOnPlayer(MitaAnim));
            MitaAnim.resetToIdleAnimation();
        }
        public static void ChoseStyle(characterType characterType,string animName)
        {

            if (animName.Contains("sit") || animName.Contains("Sit"))
            {
                movementStyles[characterType] = MovementStyles.sitting;
            }
            else if(animName.Contains("fall") || animName.Contains("Fall"))
            {
                movementStyles[characterType] = MovementStyles.layingOnTheFloorAsDead;
                
            }
            else
            {
                movementStyles[characterType] = MovementStyles.walkNear;
            }

        }

        public static IEnumerator LookOnPlayer(MitaAnimationModded mitaAnimationModded)
        {

            while (movementStyles[mitaAnimationModded.mitaCharacter] != MovementStyles.walkNear)
            {
                if (!mitaAnimationModded.mitaPerson.GetComponentInChildren<NavMeshAgent>().enabled)
                {
                    try
                    {
                        mitaAnimationModded.mitaLook.LookOnPlayerAndRotate();
                    }
                    catch (Exception e)
                    {

                        MelonLogger.Msg(e);
                    }
                    //if (Utils.Random(6, 10))

                    //else MitaLook.LookRandom();

                }
                yield return new WaitForSecondsRealtime(1);
            }
        }


        public static IEnumerator FollowPlayer(MitaAnimationModded MitaAnimation, float distance = 1f)
        {

            while (movementStyles[MitaAnimation.mitaCharacter] == MovementStyles.follow)
            {
                if (MitaCore.Instance.getDistanceToPlayer(MitaCore.getMitaByEnum(MitaAnimation.mitaCharacter)) > distance)
                {
                    MitaAnimation.mitaPerson.AiWalkToTarget(MitaCore.Instance.playerPersonObject.transform);

                }
                else
                {
                    MitaAnimation.mitaPerson.AiShraplyStop();
                    yield return new WaitForSeconds(2f);
                }

                yield return new WaitForSeconds(0.55f);
            }


        }
        public static IEnumerator FollowPlayerNoclip(characterType mitaCharacter, float distance = 1.1f)
        {
            MelonLogger.Msg("Begin noClip");
            var MitaPersonObject = MitaCore.getMitaByEnum(mitaCharacter);
            MitaPersonObject.GetComponent<CapsuleCollider>().enabled = false;
            while (movementStyles[mitaCharacter] == MovementStyles.noclip && MitaCore.Instance.getDistanceToPlayer(MitaPersonObject) > distance)
            {

                yield return MelonCoroutines.Start(MoveToPositionNoClip(mitaCharacter, MitaPersonObject, 25));

                yield return new WaitForSeconds(1f);
            }
            MitaPersonObject.GetComponent<CapsuleCollider>().enabled = true;

        }
        private static IEnumerator MoveToPositionNoClip(characterType characterType, GameObject MitaPersonObject, float speed)
        {
            while (movementStyles[characterType] == MovementStyles.noclip && MitaCore.Instance.getDistanceToPlayer(MitaPersonObject) > 0.9f)
            {
                Vector3 targetPosition = MitaCore.Instance.playerPerson.gameObject.transform.position;
                // Двигаем персонажа напрямую к цели (без учета препятствий)
                MitaPersonObject.transform.position = Vector3.MoveTowards(MitaCore.Instance.MitaPersonObject.transform.position, targetPosition, speed * Time.deltaTime);

                // Можно добавить поворот персонажа в направлении движения (опционально)
                Vector3 direction = (targetPosition - MitaPersonObject.transform.position).normalized;
                if (direction != Vector3.zero)
                    MitaPersonObject.transform.rotation = Quaternion.LookRotation(direction);

                yield return null; // Ждем следующий кадр
            }

            // Когда достигли цели
            Debug.Log("NoClip movement completed!");
        }














    }

}
