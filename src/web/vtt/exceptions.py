from fastapi import HTTPException, status


WRONG_AUDIO_FILE_TYPE_EXCEPTION = HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Поддерживаются только .wav файлы")
WRONG_MODEL_NAME_EXCEPTION = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Модель не найдена")
WRONG_AUDIO_FILE_FORMAT_EXCEPTION = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Формат аудиофайла должен быть WAV моно PCM.")