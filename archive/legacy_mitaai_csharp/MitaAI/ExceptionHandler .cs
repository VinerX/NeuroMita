using System;
using System.Threading.Tasks;
using UnityEngine;

public class ExceptionHandler : MonoBehaviour
{
    private void Awake()
    {
        // Обработка синхронных необработанных исключений
        AppDomain.CurrentDomain.UnhandledException += (sender, args) =>
        {
            var exception = args.ExceptionObject as Exception;
            if (exception != null)
            {
                Debug.LogError($"Unhandled exception: {exception.Message}\n{exception.StackTrace}");
            }
            else
            {
                Debug.LogError("Unhandled non-exception error occurred.");
            }
        };

        // Обработка необработанных исключений в асинхронных задачах
        TaskScheduler.UnobservedTaskException += (sender, args) =>
        {
            Debug.LogError($"Unobserved task exception: {args.Exception}");
            args.SetObserved(); // Помечаем исключение как обработанное
        };
    }


}
