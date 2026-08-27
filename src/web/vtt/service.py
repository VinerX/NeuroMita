import wave
from vosk import Model, KaldiRecognizer
import json
from loguru import logger
from abc import ABC, abstractmethod

from web.vtt.consts import MODELS_FOLDER_PATH

class VTTService(ABC):
    def __init__(self, model_name: str):
        model_path = f"{MODELS_FOLDER_PATH}/{model_name}"
        self.model = Model(model_path)

    @abstractmethod
    def transcribe(self, wf: wave.Wave_read) -> str:
        pass

class KaldiService(VTTService):

    def transcribe(self, wf: wave.Wave_read) -> str:
        rec = KaldiRecognizer(self.model, wf.getframerate())
        while True:
            data = wf.readframes(2000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                logger.info('Break due to AcceptWaveform == True') # ватафак почему тут так
                break

        return json.loads(rec.Result())['text']