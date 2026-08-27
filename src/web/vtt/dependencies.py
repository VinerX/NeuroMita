import io
import os
from fastapi import File, Form, UploadFile, Depends
import soundfile
import wave
from web.vtt.consts import MODELS_FOLDER_PATH, AudioFileTypes
from web.vtt.exceptions import WRONG_AUDIO_FILE_TYPE_EXCEPTION, WRONG_MODEL_NAME_EXCEPTION, WRONG_AUDIO_FILE_FORMAT_EXCEPTION

async def validate_uploaded_file(file: UploadFile = File(...)) -> UploadFile:
    if file.content_type not in AudioFileTypes:
        raise WRONG_AUDIO_FILE_TYPE_EXCEPTION
    return file

async def validate_model_name(model_name: str = Form(...)) -> str:
    if not os.path.exists(f"{MODELS_FOLDER_PATH}/{model_name}"):
        raise WRONG_MODEL_NAME_EXCEPTION
    return model_name

async def prepare_audio_file(uploaded_file: UploadFile = Depends(validate_uploaded_file)) -> wave.Wave_read:
    file = uploaded_file.file.read()
    audio_file = io.BytesIO(file)
    data, samplerate = soundfile.read(audio_file)

    # Преобразуем данные обратно в формат WAV в памяти
    wav_io = io.BytesIO()
    soundfile.write(wav_io, data, samplerate, format='WAV')
    wav_io.seek(0)

    # Открываем WAV файл из памяти
    wf = wave.open(wav_io, 'rb')
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
        raise WRONG_AUDIO_FILE_FORMAT_EXCEPTION
    return wf
