using Il2CppRootMotion.FinalIK;
using UnityEngine;
using UnityEngine.Events;

using Il2Cpp;
using MelonLoader;

namespace MitaAI
{

    [RegisterTypeInIl2Cpp]
    public class Character_Look_Old : MonoBehaviour
    {
        public static void CopyCharacterLookToOld(Character_Look source, Character_Look_Old target)
        {
            if (source == null || target == null) return;

            // Copy simple fields
            target.active = source.active;
            target.activeBlink = source.activeBlink;
            target.animPerson = source.animPerson;
            target.movePoints = source.movePoints;
            target.movePointsBody = source.movePointsBody;
            target.boneHead = source.boneHead;
            target.forwardPerson = source.forwardPerson;
            target.spine = source.spine;
            target.head = source.head;
            target.eyes = source.eyes;
            target.body = source.body;
            target.activeBodyIK = source.activeBodyIK;
            target.offLimitAngleLook = source.offLimitAngleLook;
            target.offTimeLookRandom = source.offTimeLookRandom;
            target.offIKHead = source.offIKHead;
            target.animationRotateBody = source.animationRotateBody;
            target.animationRotateBodyUpLegs = source.animationRotateBodyUpLegs;
            target.canRotateBody = source.canRotateBody;
            target.pivotLegs = source.pivotLegs;
            target.legRight = source.legRightBone; // Note: field name difference
            target.legLeft = source.legLeftBone;   // Note: field name difference
            target.animBlink = source.animBlink;
            target.startPriorityPlayer = source.startPriorityPlayer;
            target.lookObject = source.lookObject;
            target.dotLook = source.dotLook;

            // Copy events if needed
            // Note: You might need to handle event copying differently depending on your needs
            target.eventRotateBodyFinish = source.eventRotateBodyFinish;
            target.eventRotateBodyHalfFinish = source.eventRotateBodyHalfFinish;

            // Copy state fields
            target.erbfReady = source.erbfReady;
            target.erbhfReady = source.erbhfReady;

            // Copy timing fields
            target.timeAnimationPivotLegsRotate = source.timeAnimationPivotLegsRotate;
            target.pivotLegsRotateWas = source.pivotLegsRotateWas;
            target.pivotLegsRotateNeed = source.pivotLegsRotateNeed;
            target.rotateBodySide = source.rotateBodySide;
            target.positionRightLegStay = source.positionRightLegStay;
            target.positionLeftLegStay = source.positionLeftLegStay;
            target.positionLegNeedLeft = source.positionLegNeedLeft;
            target.positionLegNeedRight = source.positionLegNeedRight;
            target.rotationLegRotateRight = source.rotationLegRotateRight;
            target.rotationLegRotateLeft = source.rotationLegRotateLeft;
            target.timeDontCanRotateBody = source.timeDontCanRotateBody;
            target.timeNowCanRotateBody = source.timeNowCanRotateBody;
            target.speedRotateBody = source.speedRotateBody;
            target.lookObjectEyes = source.lookObjectEyes;
            target.timeLookObjectEyes = source.timeLookObjectEyes;
            target.timeCheckEyes = source.timeCheckEyes;
            target.eyesPositionRandom = source.eyesPositionRandom;
            target.timeBlink = source.timeBlink;
            target.timeBlinkM = source.timeBlinkM;
            target.randomLook = source.randomLook;
            target.positionRandomLook = source.positionRandomLook;
            target.timeLookEyes = source.timeLookEyes;
            target.timeLookEyesMax = source.timeLookEyesMax;
            target.timeLookHead = source.timeLookHead;
            target.timeLookHeadMax = source.timeLookHeadMax;
            target.speedLerpLookHead = source.speedLerpLookHead;
            target.speedLerpDivide = source.speedLerpDivide;

            // Note: Some fields in Character_Look don't have direct equivalents in Character_Look_Old
            // like ikMain, bodyYOffset, needBodyYOffset, wasBodyYOffset, timeNeedBodyYOffset,
            // stepLegs, timeAnimationNow, animationNod, typeNod, positionNod, speedActivation, speedLook
        }

        // Usage example:
        // Character_Look newLook = ...;
        // Character_Look_Old oldLook = ...;
        // CopyCharacterLookToOld(newLook, oldLook);

        private Transform mainTransform;

        //[Header("Поведение")]
        public bool active = true;

        public bool activeBlink = true;

        // [Header("Анимация")]
        public Animator animPerson;

        public AnimationCurve movePoints;

        public AnimationCurve movePointsBody;

        private Transform boneHead;

        //  [Header("IK")]
        public Transform forwardPerson;

        public Transform spine;

        public LookAtIK head;

        public LookAtIK eyes;

        public LookAtIK body;

        public bool activeBodyIK;

        public bool offLimitAngleLook;

        public bool offTimeLookRandom;

        public bool offIKHead;

        private float timeAnimationPivotLegsRotate;

        private float pivotLegsRotateWas;

        private float pivotLegsRotateNeed;

        private bool rotateBodySide;

        private Vector3 positionRightLegStay;

        private Vector3 positionLeftLegStay;

        private Vector3 positionLegNeedLeft;

        private Vector3 positionLegNeedRight;

        private Quaternion rotationLegRotateRight;

        private Quaternion rotationLegRotateLeft;

        private float timeDontCanRotateBody;

        private float timeNowCanRotateBody;

        public float speedRotateFactor = 0.5f;
        public float speedRotateBody;

        private Transform targetForRotateBody;

        // [Header("Поворот персонажа")]
        public AnimationCurve animationRotateBody;

        public AnimationCurve animationRotateBodyUpLegs;

        public bool canRotateBody;

        public Transform pivotLegs;

        public Transform legRight;

        public Transform legLeft;

        // [Header("Блендшейпы")]
        public Animator animBlink;

        //  [Header("Стартовые настройки")]
        public bool startPriorityPlayer;

        //  [Header("Инфо")]
        private Transform lookObjectEyes;

        private float timeLookObjectEyes;

        private float timeCheckEyes;

        private Vector3 eyesPositionRandom;

        private float timeBlink;

        private float timeBlinkM;

        private bool randomLook;

        private Vector3 positionRandomLook;

        private float timeLookEyes;

        private float timeLookEyesMax;

        private float timeLookHead;

        private float timeLookHeadMax;

        private float speedLerpLookHead;

        private float speedLerpDivide;

        // [Header("Взгляд персонажа")]
        public Transform lookObject;

        public float dotLook;

        //  [HideInInspector]
        public UnityEvent eventRotateBodyFinish;

        //  [HideInInspector]
        public bool erbfReady;

        //  [HideInInspector]
        public UnityEvent eventRotateBodyHalfFinish;

        //  [HideInInspector]
        public bool erbhfReady;

        private void Start()
        {
            ReTimeBlink();
            ReTimeLookHead();
            mainTransform = base.transform.parent;
            boneHead = spine.transform.Find("Chest/Neck2/Neck1/Head");
            speedLerpLookHead = 8f;
            timeAnimationPivotLegsRotate = 1f;
            timeNowCanRotateBody = UnityEngine.Random.Range(0.1f, 0.5f);
            if (!active)
            {
                head.solver.IKPositionWeight = 0f;
                eyes.solver.IKPositionWeight = 0f;
            }
            if (!activeBodyIK)
            {
                body.solver.IKPositionWeight = 0f;
            }
            speedLerpDivide = 1f;
            if (lookObject != null)
            {
                LookOnObject(lookObject);
            }
            if (startPriorityPlayer)
            {
                PriorityLookOnPlayer();
            }
        }

        private void Update()
        {
            if (active)
            {
                if (lookObject != null)
                {
                    dotLook = Vector3.Dot(forwardPerson.forward, GlobalAM.NormalizeFloor(lookObject.position - forwardPerson.position));
                }
                eyes.solver.IKPositionWeight = Mathf.Lerp(eyes.solver.IKPositionWeight, 1f, Time.deltaTime * 3f);
                if (!offTimeLookRandom)
                {
                    timeLookEyes += Time.deltaTime;
                    if (timeLookEyes > timeLookEyesMax)
                    {
                        ReTimeLookEyes();
                    }
                }
                if (lookObjectEyes == null)
                {
                    eyes.solver.target.transform.position = Vector3.Lerp(eyes.solver.target.transform.position, head.solver.target.transform.position + eyesPositionRandom, Time.deltaTime * 50f);
                    timeCheckEyes -= Time.deltaTime;
                    if (timeCheckEyes < 0f)
                    {
                        CheckLookForEyes();
                    }
                }
                else
                {
                    eyes.solver.target.transform.position = Vector3.Lerp(eyes.solver.target.transform.position, lookObjectEyes.position + eyesPositionRandom, Time.deltaTime * 50f);
                    timeLookObjectEyes -= Time.deltaTime;
                    if (timeLookObjectEyes <= 0f)
                    {
                        lookObjectEyes = null;
                    }
                }
                if (activeBodyIK)
                {
                    body.solver.IKPositionWeight = Mathf.Lerp(body.solver.IKPositionWeight, 1f, Time.deltaTime * 2f);
                }
                else
                {
                    body.solver.IKPositionWeight = Mathf.Lerp(body.solver.IKPositionWeight, 0f, Time.deltaTime * 2f);
                }
                if (lookObject == null)
                {
                    body.transform.position = Vector3.Lerp(body.transform.position, new Vector3(head.solver.target.transform.position.x, spine.position.y, head.solver.target.transform.position.z), Time.deltaTime * 4f);
                }
                else
                {
                    body.transform.position = Vector3.Lerp(body.transform.position, new Vector3(head.solver.target.transform.position.x, spine.position.y, head.solver.target.transform.position.z), Time.deltaTime * 2f);
                }
                if (canRotateBody && lookObject != null && !animPerson.GetBool("Walk"))
                {
                    if (timeDontCanRotateBody > 0f)
                    {
                        timeDontCanRotateBody -= Time.deltaTime;
                        if (timeDontCanRotateBody < 0f)
                        {
                            timeDontCanRotateBody = 0f;
                        }
                    }
                    else if ((double)dotLook < 0.45)
                    {
                        if (timeNowCanRotateBody > 0f)
                        {
                            timeNowCanRotateBody -= Time.deltaTime;
                        }
                        else
                        {
                            StartRotate(lookObject.position);
                            timeNowCanRotateBody = UnityEngine.Random.Range(0.1f, 0.5f);
                        }
                    }
                }
                if (lookObject != null)
                {
                    if (!randomLook)
                    {
                        head.solver.target.transform.position = Vector3.Lerp(head.solver.target.transform.position, lookObject.position, Time.deltaTime * (speedLerpLookHead / speedLerpDivide));
                    }
                    else
                    {
                        head.solver.target.transform.position = Vector3.Lerp(head.solver.target.transform.position, forwardPerson.position + forwardPerson.up * (boneHead.position.y - base.transform.position.y) + forwardPerson.forward * 2f + positionRandomLook, Time.deltaTime * (speedLerpLookHead / speedLerpDivide / 2f));
                    }
                    if (!offIKHead && ((double)Vector3.Dot(forwardPerson.forward, Vector3.Normalize(lookObject.transform.position - forwardPerson.position)) > 0.1 || offLimitAngleLook))
                    {
                        head.solver.IKPositionWeight = Mathf.Lerp(head.solver.IKPositionWeight, 1f, Time.deltaTime * 3f);
                    }
                    else
                    {
                        head.solver.IKPositionWeight = Mathf.Lerp(head.solver.IKPositionWeight, 0f, Time.deltaTime * 3f);
                    }
                }
                else
                {
                    if (!randomLook)
                    {
                        head.solver.target.transform.position = Vector3.Lerp(head.solver.target.transform.position, new Vector3(forwardPerson.position.x, boneHead.position.y, forwardPerson.position.z) + forwardPerson.forward * 2f, Time.deltaTime * (speedLerpLookHead / speedLerpDivide));
                    }
                    else
                    {
                        head.solver.target.transform.position = Vector3.Lerp(head.solver.target.transform.position, new Vector3(forwardPerson.position.x, boneHead.position.y, forwardPerson.position.z) + forwardPerson.forward * 2f + positionRandomLook, Time.deltaTime * (speedLerpLookHead / speedLerpDivide));
                    }
                    if (!offIKHead)
                    {
                        head.solver.IKPositionWeight = Mathf.Lerp(head.solver.IKPositionWeight, 1f, Time.deltaTime * 3f);
                    }
                    else
                    {
                        head.solver.IKPositionWeight = Mathf.Lerp(head.solver.IKPositionWeight, 0f, Time.deltaTime * 3f);
                    }
                }
                if (!offTimeLookRandom)
                {
                    timeLookHead += Time.deltaTime;
                    if (timeLookHead > timeLookHeadMax)
                    {
                        ReTimeLookHead();
                    }
                }
                if (timeDontCanRotateBody == 0f)
                {
                    speedLerpLookHead = Mathf.Lerp(speedLerpLookHead, 8f, Time.deltaTime * 5f);
                }
                else
                {
                    speedLerpLookHead = Mathf.Lerp(speedLerpLookHead, 20f, Time.deltaTime * 5f);
                }
                if (speedLerpDivide > 1f)
                {
                    speedLerpDivide -= Time.deltaTime;
                    if (speedLerpDivide < 1f)
                    {
                        speedLerpDivide = 1f;
                    }
                }
            }
            else
            {
                eyes.solver.IKPositionWeight = Mathf.Lerp(eyes.solver.IKPositionWeight, 0f, Time.deltaTime * 6f);
                head.solver.IKPositionWeight = Mathf.Lerp(head.solver.IKPositionWeight, 0f, Time.deltaTime * 3f);
                if (activeBodyIK)
                {
                    body.solver.IKPositionWeight = Mathf.Lerp(body.solver.IKPositionWeight, 0f, Time.deltaTime * 8f);
                }
            }
            if (timeAnimationPivotLegsRotate < 1f)
            {
                timeAnimationPivotLegsRotate += Time.deltaTime * speedRotateBody;
                if (timeAnimationPivotLegsRotate > 1f)
                {
                    timeAnimationPivotLegsRotate = 1f;
                }
                pivotLegs.rotation = Quaternion.Lerp(Quaternion.Euler(new Vector3(0f, pivotLegsRotateWas, 0f)), Quaternion.Euler(new Vector3(0f, pivotLegsRotateNeed, 0f)), animationRotateBody.Evaluate(timeAnimationPivotLegsRotate * 2f));
                mainTransform.rotation = Quaternion.Lerp(Quaternion.Euler(new Vector3(0f, pivotLegsRotateWas, 0f)), Quaternion.Euler(new Vector3(0f, pivotLegsRotateNeed, 0f)), animationRotateBody.Evaluate(timeAnimationPivotLegsRotate));
                if (timeAnimationPivotLegsRotate < 0.5f && !erbhfReady)
                {
                    erbhfReady = true;
                    eventRotateBodyHalfFinish.Invoke();
                }
                if (rotateBodySide)
                {
                    legLeft.rotation = rotationLegRotateLeft;
                    if (timeAnimationPivotLegsRotate < 0.5f)
                    {
                        legLeft.position = positionLeftLegStay;
                        legRight.localPosition = positionLegNeedRight + Vector3.up * animationRotateBodyUpLegs.Evaluate(timeAnimationPivotLegsRotate);
                    }
                    else
                    {
                        legRight.localPosition = positionLegNeedRight;
                        legLeft.position = Vector3.Lerp(positionLeftLegStay, GlobalAM.TransformPivot(pivotLegs, positionLegNeedLeft) + Vector3.up * animationRotateBodyUpLegs.Evaluate(timeAnimationPivotLegsRotate), animationRotateBody.Evaluate((timeAnimationPivotLegsRotate - 0.5f) * 2f));
                    }
                }
                else
                {
                    legRight.rotation = rotationLegRotateRight;
                    if (timeAnimationPivotLegsRotate < 0.5f)
                    {
                        legRight.position = positionRightLegStay;
                        legLeft.localPosition = positionLegNeedLeft + Vector3.up * animationRotateBodyUpLegs.Evaluate(timeAnimationPivotLegsRotate);
                    }
                    else
                    {
                        legLeft.localPosition = positionLegNeedLeft;
                        legRight.position = Vector3.Lerp(positionRightLegStay, GlobalAM.TransformPivot(pivotLegs, positionLegNeedRight) + Vector3.up * animationRotateBodyUpLegs.Evaluate(timeAnimationPivotLegsRotate), animationRotateBody.Evaluate((timeAnimationPivotLegsRotate - 0.5f) * 2f));
                    }
                }
                if (timeAnimationPivotLegsRotate > 0.5f)
                {
                    float num = 1f - (timeAnimationPivotLegsRotate - 0.5f) * 2f;
                    legRight.GetComponent<LegIK>().solver.SetIKPositionWeight(num);
                    if (legRight.GetComponent<LegIK>().solver.IKRotationWeight > 0f)
                    {
                        legRight.GetComponent<LegIK>().solver.IKRotationWeight = num;
                    }
                    legLeft.GetComponent<LegIK>().solver.SetIKPositionWeight(num);
                    if (legLeft.GetComponent<LegIK>().solver.IKRotationWeight > 0f)
                    {
                        legLeft.GetComponent<LegIK>().solver.IKRotationWeight = num;
                    }
                }
                if (timeAnimationPivotLegsRotate == 1f)
                {
                    StopRotate();
                }
            }
            if (activeBlink)
            {
                if (animBlink != null)
                {
                    timeBlink += Time.deltaTime;
                    if (timeBlink > timeBlinkM)
                    {
                        animBlink.SetTrigger("Blink");
                        ReTimeBlink();
                    }
                }
                if (animBlink.layerCount > 1)
                {
                    animBlink.SetLayerWeight(1, Mathf.Lerp(animBlink.GetLayerWeight(1), 1f, Time.deltaTime * 5f));
                }
            }
            else if (animBlink.layerCount > 1)
            {
                animBlink.SetLayerWeight(1, Mathf.Lerp(animBlink.GetLayerWeight(1), 0f, Time.deltaTime * 5f));
            }
        }

        private void LateUpdate()
        {
            if (targetForRotateBody != null)
            {
                StartRotate(targetForRotateBody.position);
                targetForRotateBody = null;
            }
        }

        private void OnEnable()
        {
            animBlink.SetTrigger("Blink");
            ReTimeBlink();
            if (active && lookObject != null)
            {
                if ((double)Vector3.Dot(forwardPerson.forward, Vector3.Normalize(lookObject.transform.position - forwardPerson.position)) > 0.1 || offLimitAngleLook)
                {
                    head.solver.IKPositionWeight = 1f;
                }
                else
                {
                    head.solver.IKPositionWeight = 0f;
                }
                head.solver.target.transform.position = lookObject.position;
                body.solver.IKPositionWeight = 1f;
                body.transform.position = new Vector3(head.solver.target.transform.position.x, spine.position.y, head.solver.target.transform.position.z);
                lookObjectEyes = lookObject;
                eyes.solver.target.transform.position = lookObjectEyes.position + eyesPositionRandom;
            }
        }

        private void ReTimeLookEyes()
        {
            timeLookEyes = 0f;
            timeLookEyesMax = UnityEngine.Random.Range(1f, 3f);
            if (lookObject == null && lookObjectEyes == null)
            {
                int num = UnityEngine.Random.Range(0, 3);
                if (num == 0)
                {
                    eyesPositionRandom += GlobalAM.Vector3Random(-0.3f, 0.3f);
                }
                if (num == 1)
                {
                    eyesPositionRandom += GlobalAM.Vector3Random(-0.05f, 0.05f);
                }
                if (num == 2)
                {
                    eyesPositionRandom = Vector3.zero;
                }
            }
            else if (UnityEngine.Random.Range(0, 51) > 10)
            {
                eyesPositionRandom = GlobalAM.Vector3Random(-0.05f, 0.05f);
            }
            else
            {
                eyesPositionRandom = Vector3.zero;
            }
        }

        private void CheckLookForEyes()
        {
            if (GlobalTag.cameraPlayer != null && ((double)Vector3.Dot(forwardPerson.forward, Vector3.Normalize(GlobalTag.cameraPlayer.transform.position - forwardPerson.position)) > 0.18 || offLimitAngleLook) && UnityEngine.Random.Range(0, 9) > 5)
            {
                lookObjectEyes = GlobalTag.cameraPlayer.transform;
                timeLookObjectEyes = UnityEngine.Random.Range(0.3f, 1f);
            }
            timeCheckEyes = UnityEngine.Random.Range(1f, 5f);
            eyesPositionRandom = Vector3.zero;
        }

        //[ContextMenu("ReLookHead")]
        private void ReTimeLookHead()
        {
            timeLookHead = 0f;
            timeLookHeadMax = UnityEngine.Random.Range(3f, 8f);
            if (randomLook)
            {
                randomLook = false;
                speedLerpLookHead = 0f;
            }
            if (!offTimeLookRandom && UnityEngine.Random.Range(0, 100) > 95)
            {
                LookRandom();
            }
            ReTimeLookEyes();
        }

        private void ReTimeBlink()
        {
            timeBlink = 0f;
            timeBlinkM = UnityEngine.Random.Range(1f, 8f);
            if (UnityEngine.Random.Range(0, 100) > 90)
            {
                timeBlinkM = 0.3f;
            }
        }

        public void StartRotate(Vector3 _positionTarget)
        {
            if (timeAnimationPivotLegsRotate == 1f)
            {
                randomLook = false;
                timeDontCanRotateBody = 1f;
                pivotLegsRotateWas = base.transform.eulerAngles.y;
                timeAnimationPivotLegsRotate = 0f;
                pivotLegsRotateNeed = Quaternion.LookRotation(Vector3.Normalize(_positionTarget - mainTransform.position), Vector3.up).eulerAngles.y;
                legRight.position = legRight.GetComponent<LegIK>().solver.toe.transform.position;
                legRight.rotation = legRight.GetComponent<LegIK>().solver.toe.transform.rotation;
                legRight.GetComponent<LegIK>().solver.SetIKPositionWeight(1f);
                positionRightLegStay = legRight.position;
                positionLegNeedRight = legRight.localPosition;
                rotationLegRotateRight = legRight.rotation;
                legLeft.position = legLeft.GetComponent<LegIK>().solver.toe.transform.position;
                legLeft.rotation = legLeft.GetComponent<LegIK>().solver.toe.transform.rotation;
                legLeft.GetComponent<LegIK>().solver.SetIKPositionWeight(1f);
                positionLeftLegStay = legLeft.position;
                positionLegNeedLeft = legLeft.localPosition;
                rotationLegRotateLeft = legLeft.rotation;
                if (Vector3.Dot(mainTransform.right, Vector3.Normalize(new Vector3(_positionTarget.x, mainTransform.position.y, _positionTarget.z) - mainTransform.position)) > 0f)
                {
                    rotateBodySide = true;
                    legLeft.GetComponent<LegIK>().solver.IKRotationWeight = 1f;
                }
                else
                {
                    rotateBodySide = false;
                    legRight.GetComponent<LegIK>().solver.IKRotationWeight = 1f;
                }
                if ((double)Vector3.Dot(mainTransform.forward, Vector3.Normalize(new Vector3(_positionTarget.x, mainTransform.position.y, _positionTarget.z) - mainTransform.position)) < -0.4)
                {
                    speedRotateBody = 0.8f * speedRotateFactor;
                }
                else
                {
                    speedRotateBody = 1.5f * speedRotateFactor;
                }
            }
        }

        public void StopRotate()
        {
            legRight.GetComponent<LegIK>().solver.SetIKPositionWeight(0f);
            legRight.GetComponent<LegIK>().solver.IKRotationWeight = 0f;
            legLeft.GetComponent<LegIK>().solver.SetIKPositionWeight(0f);
            legLeft.GetComponent<LegIK>().solver.IKRotationWeight = 0f;
            timeAnimationPivotLegsRotate = 1f;
            if (!erbfReady)
            {
                erbfReady = true;
                eventRotateBodyFinish.Invoke();
            }
        }

        public void IKBodyEnable(bool x)
        {
            activeBodyIK = x;
        }

        public void LookOnObject(Transform _target)
        {
            if (_target == null)
            {
                MonoBehaviour.print("!");
            }
            randomLook = false;
            if (lookObject != _target)
            {
                timeLookHead = 0f;
                timeLookHeadMax = UnityEngine.Random.Range(3f, 7f);
                lookObject = _target;
                speedLerpLookHead = 0f;
            }
            if (lookObjectEyes != _target)
            {
                timeLookEyes = 0f;
                timeLookEyesMax = UnityEngine.Random.Range(1.5f, 4f);
                lookObjectEyes = _target;
            }
        }

        public void LookOnObjectSmooth(Transform _target)
        {
            speedLerpDivide = 8f;
            LookOnObject(_target);
        }

        public void LookAndPriorityObject(Transform _target)
        {
            LookOnObject(_target);
        }

        public void LookOnObjectAndRotate(Transform _target)
        {
            StartRotate(_target.position);
            LookOnObject(_target);
        }

        public void RotateOnTarget(Transform _target)
        {
            targetForRotateBody = _target;
        }

        public void ForwardReTransform(Transform _target)
        {
            forwardPerson = _target;
        }

        //[ContextMenu("Случайный взгляд")]
        public void LookRandom()
        {
            positionRandomLook = new Vector3(UnityEngine.Random.Range(-0.4f, 0.4f), UnityEngine.Random.Range(-0.1f, 0.1f), UnityEngine.Random.Range(0.5f, 1.5f));
            randomLook = true;
            speedLerpLookHead = 0f;
        }

        public void EyesLookOnPlayer(float _time)
        {
            lookObjectEyes = GlobalTag.cameraPlayer.transform;
            timeLookObjectEyes = _time;
            timeCheckEyes = _time + UnityEngine.Random.Range(0.5f, 3f);
            eyesPositionRandom = Vector3.zero;
        }

        public void EyesLookOffsetRandom(float _x)
        {
            eyesPositionRandom += GlobalAM.Vector3Random(0f - _x, _x);
        }

        public void Blink()
        {
            timeBlink = timeBlinkM;
        }

        public void LookOnPlayer()
        {
            LookOnObject(GlobalTag.cameraPlayer.transform);
        }

        public void LookOnPlayerAndRotate()
        {
            StartRotate(GlobalTag.cameraPlayer.transform.position);
            LookOnObject(GlobalTag.cameraPlayer.transform);
        }

        public void LookRotatePriorityOnPlayer()
        {
            StartRotate(GlobalTag.cameraPlayer.transform.position);
            LookOnObject(GlobalTag.cameraPlayer.transform);
            PriorityLook(GlobalTag.cameraPlayer.transform);
        }

        public void PriorityLookOnPlayer()
        {
            PriorityLook(GlobalTag.cameraPlayer.transform);
        }

        public void PriorityLookAndOnPlayer()
        {
            PriorityLook(GlobalTag.cameraPlayer.transform);
            LookOnPlayer();
        }

        public void FastDeactive()
        {
            randomLook = false;
            lookObject = null;
            active = false;
            canRotateBody = false;
            head.solver.IKPositionWeight = 0f;
            eyes.solver.IKPositionWeight = 0f;
            if (activeBodyIK)
            {
                body.solver.IKPositionWeight = 0f;
            }
            if (timeAnimationPivotLegsRotate < 1f)
            {
                timeAnimationPivotLegsRotate = 1f;
                StopRotate();
            }
        }

        public void Activation(bool x)
        {
            if (!active && x)
            {
                speedLerpLookHead = 0f;
            }
            active = x;
        }

        public void ActivationBlink(bool x)
        {
            activeBlink = x;
        }

        public void ActivationRotateBody(bool x)
        {
            canRotateBody = x;
        }

        public void PriorityLook(Transform _transform)
        {
            LookOnObject(_transform);
        }

        public void RandomTimeLookActivation(bool x)
        {
            offTimeLookRandom = !x;
        }
    }

}
