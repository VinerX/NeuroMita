using Il2Cpp;
using Il2CppInterop.Runtime.InteropTypes;
using MelonLoader;
using System;
using System.Collections;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using System.Text.RegularExpressions;
namespace MitaAI
{
    public static class Testing
    {

        public static void makeTestingSphere(GameObject parent,Color color)
        {
            var debugSphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            debugSphere.transform.SetParent(parent.transform, false);
            debugSphere.transform.SetLocalPositionAndRotation(new Vector3(0,0.5f,0),Quaternion.identity);
            debugSphere.transform.localScale = Vector3.one * 0.4f; // Масштабируем до небольшого размера
            debugSphere.GetComponent<Collider>().enabled = false; // Отключаем коллизию
            debugSphere.GetComponent<Renderer>().material.color = color; // Делаем красным для заметности
        }




    }


}
