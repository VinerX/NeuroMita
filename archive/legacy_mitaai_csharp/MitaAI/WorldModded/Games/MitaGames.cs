using Il2Cpp;
using MelonLoader;
using MitaAI.Mita;
using System;
using System.Collections;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;


namespace MitaAI
{
    public enum MitaGame
    {
        None,
        Snows,
        Milk
    }

    public static class MitaGames
    {
        public static MitaGame currentGame = MitaGame.None;
        public static string getGameInfo()
        {
            switch (currentGame)
            {
                case MitaGame.None:
                    break;
                case MitaGame.Snows:
                    return TVModded.getSnowsString();
                case MitaGame.Milk:
                    return TVModded.getMilkString();

            }

            return "";
    
        }

        #region Hunting
            public static void beginHunt()
        {
            try
            {
                MelonLogger.Msg("beginHunt ");
                MitaCore.Instance.knife.SetActive(true);
                MitaState.SetCurrentState(MitaCore.Instance.currentCharacter,MitaStateType.hunt);


                if (MitaCore.Instance.currentCharacter == characterType.Creepy && LogicCharacter.Instance != null)
                {
                    LogicCharacter.Instance.StartHunt(MitaCore.Instance);
                }
                else
                {
                    // Для других персонажей - вызываем внутренний метод охоты
                    var mitaAnimationModded = MitaAnimationModded.getMitaAnimationModded(MitaCore.Instance.currentCharacter);
                    mitaAnimationModded.location34_Communication.ActivationCanWalk(false);
                    mitaAnimationModded.EnqueueAnimation("Mita TakeKnife_0");
                    mitaAnimationModded.setIdleWalk("Mita WalkKnife");
                    MelonCoroutines.Start(hunting());
                }

                ObjectAnimationMita.finishWorkingOAM(MitaCore.Instance.currentCharacter);
            }
            catch (Exception ex)
            {
                MelonLogger.Error("beginHunt " + ex);
            }
        }
        static IEnumerator hunting()
        {
            if (!MitaCore.isRequiredScene()) yield break;

            float startTime = Time.unscaledTime;
            float lastMessageTime = 0f;
            float timeToUpdateCommand = 2.5f;

            yield return new WaitForSecondsRealtime(1f);

            while (MitaState.GetCurrentState(MitaCore.Instance.currentCharacter) == MitaStateType.hunt)
            {
                if (MitaCore.Instance.getDistanceToPlayer() > timeToUpdateCommand)
                {
                    MitaCore.Instance.Mita.AiWalkToTarget(MitaCore.Instance.playerPerson.transform);
                }
                else
                {
                    try
                    {
                        MelonCoroutines.Start(CommandProcessor.ActivateAndDisableKiller(3));
                    }
                    catch (Exception ex)
                    {
                        MelonLogger.Error(ex);
                    }

                    yield break;
                }

                float elapsedTime = Time.unscaledTime - startTime;

                // Проверяем, прошло ли 45 секунд с последнего сообщения
                if (elapsedTime - lastMessageTime >= 45f)
                {
                    string message = $"Игрок жив уже {elapsedTime.ToString("F2")} секунд. Скажи что-нибудь короткое. ";
                    if (Mathf.FloorToInt(elapsedTime) % 60 == 0)
                        message += "Может быть, пора усложнять игру...";

                    CharacterMessages.sendSystemMessage(message);
                    lastMessageTime = elapsedTime; // Обновляем время последнего сообщения
                }

                yield return new WaitForSecondsRealtime(0.5f);
            }
        }
        public static void endHunt()
        {
            if (MitaCore.Instance.currentCharacter == characterType.Creepy && LogicCharacter.Instance != null)
            {
                // Для Creepy вызываем логику из LogicCharacter
                LogicCharacter.Instance.EndHunt();
            }
            else
            {
                // Для других персонажей используем стандартную логику
                var mitaAnimationModded = MitaAnimationModded.getMitaAnimationModded(MitaCore.Instance.currentCharacter);
                mitaAnimationModded.setIdleWalk("Mita Walk_1");
                MitaCore.Instance.knife.SetActive(false);
                MitaMovement.setMovementStyle(MitaCore.Instance.currentCharacter,MovementStyles.walkNear);
                mitaAnimationModded.location34_Communication.ActivationCanWalk(true);
                MitaState.SetCurrentState(MitaCore.Instance.currentCharacter,MitaStateType.normal);
                MitaCore.Instance.MitaSharplyStopTimed(0.5f);
            }
        }

        // Метод для вызова из LogicCharacter, чтобы активировать анимацию убийства
        public static void ActivateKillerAnimation()
        {
            MelonCoroutines.Start(CommandProcessor.ActivateAndDisableKiller(3));
        }

        // Метод для LogicCharacter, чтобы установить состояние персонажа
        public static void SetHuntState(bool isHunting)
        {
            MitaState.SetCurrentState(MitaCore.Instance.currentCharacter,isHunting ? MitaStateType.hunt : MitaStateType.normal);
        }
        #endregion

        #region Manekens

        public static bool manekenGame = false;
        public static List<GameObject> activeMakens = new List<GameObject>();
        public static float blinkTimer = 7f;
        public static GameObject ManekenTemplate;
        public static void spawnManeken()
        {
            GameObject someManeken = GameObject.Instantiate(ManekenTemplate, MitaCore.worldHouse.Find("House"));
            someManeken.SetActive(true);
            activeMakens.Add(someManeken);

            if (manekenGame == false)
            {
                manekenGame = true;
                MelonCoroutines.Start(CheckManekenGame());
            }
            someManeken.transform.SetPositionAndRotation(MitaCore.Instance.GetRandomLoc().position, MitaCore.Instance.GetRandomLoc().rotation);


        }
        public static void TurnAllMenekens(bool on)
        {
            if (activeMakens.Count <= 0) return;

            foreach (GameObject m in activeMakens)
            {
                if (on) m.transform.FindChild("MitaManeken 1").gameObject.GetComponent<Mob_Maneken>().ResetManeken();
                else m.transform.FindChild("MitaManeken 1").gameObject.GetComponent<Mob_Maneken>().DeactivationManeken();

            }
            manekenGame = on;
        }
        public static void removeAllMenekens()
        {
            foreach (GameObject m in activeMakens)
            {
                GameObject.Destroy(m);
            }
            activeMakens.Clear();
            manekenGame = false;
        }
        private static IEnumerator CheckManekenGame()
        {
            while (MitaCore.isRequiredScene())
            {
                try
                {
                    if (!manekenGame) yield break;

                    if (MitaCore.blackScreen != null && MitaCore.playerCamera != null)
                    {
                        MitaCore.blackScreen.BlackScreenAlpha(0.75f);
                        MitaCore.playerCamera.GetComponent<Camera>().enabled = false;
                        MelonCoroutines.Start(Utils.ToggleComponentAfterTime(MitaCore.playerCamera.GetComponent<Camera>(), 0.75f)); // Отключит playerCamera через 1 секунду
                    }

                    yield return new WaitForSeconds(blinkTimer); // Ждем 7 секунд перед следующим циклом
                }
                finally { }

            }
        }

        #endregion


    }
}
