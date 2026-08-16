using static MelonLoader.MelonLogger;
using System.Net.Sockets;
using System.Text;
using MelonLoader;
using UnityEngine;
using System.Text.Json;
namespace MitaAI
{
    public static class NetworkController
    {
        static MitaCore mitaCore;
        private const string ServerAddress = "127.0.0.1";
        private const int Port = 12345;

        public static bool connectedToSilero;

        static public void Initialize()
        {
            mitaCore = MitaCore.Instance;
        }
        static int lastId = 0;
        static int getIncreaseMessasgeId()
        {
            int sendId = lastId;
            lastId += 1;
            return sendId;
        }
        static public async Task<Dictionary<string, JsonElement>> GetResponseFromPythonSocketAsync(string input, string dataToSentSystem, string systemInfo, characterType characterSend = characterType.Crazy)
        {
            // Ожидаем, чтобы получить доступ к ресурсу (сокету)

            using (Socket clientSocket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp))
            {
                bool connected = await TryConnectAsync(clientSocket, ServerAddress, Port);
                if (!connected)
                {
                    return null; // Возвращаем пустой ответ, если не удалось подключиться
                }
                //MelonLogger.Msg("In GetResponseFromPythonSocketAsync");
                bool waitResponse = (input != "waiting" || dataToSentSystem != "-");
                // Дополнительная логика для подготовки данных



                string _currentInfo = waitResponse ? CurrentInfoControl.currentInfo : "-";
                if (string.IsNullOrEmpty(CurrentInfoControl.currentInfo)) _currentInfo = "-";
                if (string.IsNullOrEmpty(systemInfo)) systemInfo = "-";

                var messageData = new
                {
                    id = getIncreaseMessasgeId(),  // Например, ID сообщения
                    type = "chat", // Тип сообщения
                    character = characterSend.ToString(),
                    input,
                    dataToSentSystem,
                    systemInfo,
                    distance = mitaCore.distance.ToString("F2"),
                    roomPlayer = (int)mitaCore.roomPlayer,
                    roomMita = (int)mitaCore.roomMita,
                    hierarchy = mitaCore.hierarchy,
                    currentInfo = _currentInfo,
                    dialog_active = DialogueControl.dialogActive

                };

                string jsonMessage = JsonSerializer.Serialize(messageData);
                byte[] messageBytes = Encoding.UTF8.GetBytes(jsonMessage);
                await clientSocket.SendAsync(messageBytes, SocketFlags.None);


                byte[] buffer = new byte[32000];
                try
                {
                    int bytesRead = await clientSocket.ReceiveAsync(buffer, SocketFlags.None);
                    string receivedMessage = Encoding.UTF8.GetString(buffer, 0, bytesRead);

                    Dictionary<string, JsonElement> messageData2 = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(receivedMessage);

                    return messageData2;
                }
                catch (Exception ex)
                {
                    MelonLogger.Msg($"Error receiving data: {ex.Message}");
                    return null; // Возвращаем пустой ответ в случае ошибки при получении данных
                }
            }

        }
        static private async Task<bool> TryConnectAsync(Socket socket, string address, int port, int maxRetries = 3, int delayBetweenRetries = 2000)
        {
            int attempt = 0;
            while (attempt < maxRetries)
            {
                try
                {
                    await Task.Factory.FromAsync(socket.BeginConnect(address, port, null, null), socket.EndConnect);
                    return true; // Если подключение прошло успешно
                }
                catch (SocketException)
                {
                    attempt++;
                    if (attempt >= maxRetries)
                    {
                        //MelonLogger.Msg($"Max retries reached. Unable to connect to {address}:{port}.{ex}");
                        return false; // После превышения количества попыток
                    }
                    await Task.Delay(delayBetweenRetries); // Задержка перед повторной попыткой
                }
                catch (Exception)
                {
                    //MelonLogger.Msg($"Unexpected error connecting to {address}:{port}: {ex.Message}");
                    return false; // Если произошла неожиданная ошибка
                }
            }
            return false; // В случае завершения цикла
        }
        public static async Task<AudioClip> LoadAudioClipFromFileAsync(string filePath)
        {
            try
            {
                MelonLoader.MelonLogger.Msg("Loading audio file: " + filePath);

                // Читаем все байты файла
                byte[] fileData = File.ReadAllBytes(filePath);

                // Конвертируем байты в массив float
                float[] audioData = ConvertByteArrayToFloatArray(fileData);

                // Применяем нормализацию
                audioData = NormalizeAudioData(audioData);

                // Применяем fade-in (0.1 секунды на 44100 Hz)
                audioData = ApplyFadeIn(audioData, 44100 / 10);

                // Создаем аудиоклип
                AudioClip audioClip = AudioClip.Create("LoadedAudio", audioData.Length, 2, 44100, false);
                audioClip.SetData(audioData, 0);

                MelonLoader.MelonLogger.Msg("Audio returned");

                // Удаление исходного файла
                try
                {
                    await Task.Delay(100);
                    File.Delete(filePath);
                    MelonLoader.MelonLogger.Msg("Original file deleted: " + filePath);
                }
                catch (Exception ex)
                {
                    MelonLoader.MelonLogger.Error("Error deleting original file: " + ex.Message);
                }

                return audioClip;
            }
            catch (Exception ex)
            {
                MelonLoader.MelonLogger.Error("Error loading audio: " + ex.Message);
                return null;
            }
        }


        // Нормализация аудиоданных
        private static float[] NormalizeAudioData(float[] audioData)
        {
            float maxAmplitude = 0f;
            foreach (var sample in audioData)
            {
                if (Math.Abs(sample) > maxAmplitude)
                {
                    maxAmplitude = Math.Abs(sample);
                }
            }
            if (maxAmplitude > 0)
            {
                for (int i = 0; i < audioData.Length; i++)
                {
                    audioData[i] /= maxAmplitude;
                }
            }
            return audioData;
        }

        // Применение fade-in
        private static float[] ApplyFadeIn(float[] audioData, int fadeSamples)
        {
            for (int i = 0; i < fadeSamples && i < audioData.Length; i++)
            {
                float fadeFactor = (float)i / fadeSamples;
                audioData[i] *= fadeFactor;
            }
            return audioData;
        }

        // Преобразование байтов в массив float
        private static float[] ConvertByteArrayToFloatArray(byte[] byteArray)
        {
            float[] floatArray = new float[byteArray.Length / 2]; // предполагаем, что файл в 16-битах
            for (int i = 0; i < floatArray.Length; i++)
            {
                short sample = BitConverter.ToInt16(byteArray, i * 2);
                floatArray[i] = sample / 32768f; // Нормализация в диапазон [-1, 1]
            }
            return floatArray;
        }
    }
}