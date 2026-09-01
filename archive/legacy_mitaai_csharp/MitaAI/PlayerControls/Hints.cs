using Il2Cpp;
using MelonLoader;
using UnityEngine;
using UnityEngine.Events;
using static MelonLoader.InteropSupport;

namespace MitaAI
{
    public static class Hints
    {
        public static GameObject interfaceHintTeplate;
        // 0 0 0 локальнйо позиции это центр


        public static GameObject flyingHintTeplate;
        public static Transform interfaceCanvas;

        public static GameObject exitButton;

        static Transform GetInterfaceCanvas()
        {
            if (interfaceCanvas == null)
            {
                interfaceCanvas = GameObject.Find("GameController/Interface").transform;
            }
            return interfaceCanvas;
        }

        public static Interface_KeyHint_Key CreateHint(string text, string key, Vector3 localPosition, bool isFlyingHint = false, GameObject parentObject = null,bool destroyAfter = true)
        {

            GameObject template = isFlyingHint ? flyingHintTeplate : interfaceHintTeplate;
            Transform parent = isFlyingHint ?
                (parentObject != null ? parentObject.transform : null) :
                GetInterfaceCanvas();

            if (template == null || parent == null)
            {
                Debug.LogError("Hint template or parent is not set!");
                return null;
            }
            

            GameObject hintObject = GameObject.Instantiate(template, parent);


            hintObject.transform.localPosition = localPosition;
            hintObject.name = $"hint {text}";

            Interface_KeyHint_Key interfaceKeyHint = hintObject.GetComponent<Interface_KeyHint_Key>();
            interfaceKeyHint.nameKey = key;
            interfaceKeyHint.textKey.text = key;



            interfaceKeyHint.indexString = -1;
            
            try
            {
                hintObject.active = true;
                interfaceKeyHint.Start();
            }
            catch (Exception ex) { }
            
            
            interfaceKeyHint.textDescription.text = text;
            interfaceKeyHint.textDescription.m_Text = text;
            Utils.setTextTimed(interfaceKeyHint.textDescription, text, 0.5f);

            interfaceKeyHint.destroyAfter = destroyAfter;
            if (interfaceKeyHint.eventKeyDown == null) interfaceKeyHint.eventKeyDown = new UnityEngine.Events.UnityEvent();
            interfaceKeyHint.eventKeyDown.RemoveAllListeners();

            

            return interfaceKeyHint;
        }


        public static void createExitButton()
        {
            if (exitButton != null)
            {
                MelonCoroutines.Start(Utils.OnOffObjectActiveAfterTime(exitButton,true,0.75f));
                //exitButton.active = true;
                return;
            }
            
            var hint = CreateHint(loc._("Закончить","Finish"), "_", new Vector3(-500, -350, 0));
            hint.eventKeyDown.AddListener((UnityAction)PlayerAnimationModded.stopAnim);
            exitButton = hint.gameObject;
            
        }

        public static void freeExitButton()
        {
            if (exitButton == null) return;

            exitButton.SetActive(false);
        }
    }
}