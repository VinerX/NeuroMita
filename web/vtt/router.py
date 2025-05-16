import time
from fastapi import APIRouter, Depends, status
from web.vtt.consts import MODELS_FOLDER_PATH
from web.vtt.dependencies import validate_model_name, prepare_audio_file
from web.utils import scan_folder
from web.vtt.schemas import TranscribeResponse
import wave
from loguru import logger
from web.vtt.service import KaldiService

router = APIRouter(prefix="/vtt", tags=["Voice-To-Text"])

@router.get("/models",
            summary="Получение списка доступных моделей",
            description="Возвращает список доступных моделей, которые можно использовать для преобразования аудио в текст. "
            "Модели находятся в папке <code>web/vtt/models</code>.",
            )
async def get_all_models() -> list[str]:
    return await scan_folder("web/vtt/models")

@router.post("/transcribe", 
             status_code=status.HTTP_200_OK,
             summary="Преобразование аудио в текст",
             description=f"<b>model_name</b> - имя модели, которая будет использоваться для преобразования аудио в текст. Берется из папки <code>{MODELS_FOLDER_PATH}</code>.\n\n"
             "<b>file</b> - аудиофайл формата WAV, который будет преобразован в текст.",
             )
def transcribe(validated_model_name: str = Depends(validate_model_name), wf: wave.Wave_read = Depends(prepare_audio_file)) -> TranscribeResponse:
    start_time = time.time()

    ks = KaldiService(validated_model_name)
    text = ks.transcribe(wf)

    end_time = time.time()
    return TranscribeResponse(text=text, time_elapsed=end_time - start_time)