using Il2Cpp;
using MelonLoader;
using UnityEngine;

namespace MitaAI
{
    [RegisterTypeInIl2Cpp]
    public class Items : MonoBehaviour
    {
        Transform oldParent;
        Vector3 oldPos;
        Vector3 oldRot;
        Vector3 oldScale;

        Transform NewParent;
        Vector3 NewPos;
        Vector3 NewRot;
        Vector3 newScale;

        bool isCurrentMita = true;
        string part;

        void Start()
        {
            oldParent = transform;
            oldPos = transform.localPosition;
            oldRot = transform.localEulerAngles;
            oldScale = transform.localScale;
        }
        public void init(Transform where, Vector3 localPos, Vector3 localRot,Vector3 localScale, string _part = null)
        {
            oldParent = transform.parent;
            oldPos = transform.localPosition;
            oldRot = transform.localEulerAngles;

            NewParent = where;
            NewPos = localPos;
            NewRot = localRot;
            newScale = localScale;
            part = _part;
        }
        public void init(Vector3 localPos, Vector3 localRot, Vector3 localScale, string _part = null)
        {
            oldParent = transform.parent;
            oldPos = transform.localPosition;
            oldRot = transform.localEulerAngles;
            newScale = transform.localScale;

            NewPos = localPos;
            NewRot = localRot;
            part = _part;
            newScale = localScale;
        }

        public static void Take(Transform what, Transform where, Vector3 localPos, Vector3 localRot)
        {
            // Присоединяем объект к руке
            var ItemComp = what.GetComponent<Items>();
            if (ItemComp == null)
            {
                what.gameObject.AddComponent<Items>();
            }

            ItemComp.oldParent = what.parent;
            ItemComp.oldPos = what.localPosition;
            ItemComp.oldRot = what.localEulerAngles;


            what.SetParent(where);
            what.localPosition = localPos;
            what.localEulerAngles = localRot;
        }
        public void Take()
        {

            oldParent = transform.parent;
            oldPos = transform.localPosition;
            oldRot = transform.localEulerAngles;

            if (string.IsNullOrEmpty(part))
            {
                transform.SetParent(NewParent);
            }
            else
            {
                if (isCurrentMita)
                {
                    var oldParentChild = MitaCore.Instance.MitaPersonObject.transform.Find(part);
                    if (oldParentChild != null) transform.SetParent(oldParentChild);
                }
                else
                {
                    var oldParentChild = transform.parent.transform.Find(part);
                    if (oldParentChild != null) transform.SetParent(oldParentChild);
                }

            }


            transform.localPosition = NewPos;
            transform.localEulerAngles = NewRot;
            transform.localScale = newScale;
        }


        public static void Free(Transform what)
        {
            var ItemComp = what.GetComponent<Items>();
            if (ItemComp == null) return;

            what.SetParent(ItemComp.oldParent);
            what.localPosition = ItemComp.oldPos;
            what.localEulerAngles = ItemComp.oldRot;
            what.localScale = ItemComp.oldScale;
        }

        public void Free()
        {
            transform.SetParent(oldParent);
            transform.localPosition = oldPos;
            transform.localEulerAngles = oldRot;
        }

    }
}
