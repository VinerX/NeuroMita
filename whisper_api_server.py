import json
import os
import io
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from flask_compress import Compress
from faster_whisper import WhisperModel
import librosa

# Nvidia CUDNN + CUBLAS
os.environ["PATH"] = os.environ["PATH"] + ";" + os.path.abspath(os.curdir) + "\\libs;"

# Server configuration
host = "0.0.0.0"
port = 5100

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # allow cross-domain requests
Compress(app)  # compress responses

# Whisper configuration
model_size = "./models/faster-whisper-large-v3-turbo"
DEBUG_PREFIX = "<stt whisper module>"

# Global model variable
model = None

def load_model(whisper_device="cuda", whisper_compute_type="auto"):
    if whisper_compute_type == "auto":
        whisper_compute_type = (
            "int8"
            if whisper_device == "cpu"
            else "int8_float16"
            # else "float16"
        )
    print(f"faster-whisper using {model_size} model with {whisper_compute_type}")
    return WhisperModel(model_size, device=whisper_device, compute_type=whisper_compute_type)
    
def initialize_model():
    """Initialize the Whisper model"""
    global model
    try:
        print("Initializing Whisper speech-recognition model...")
        model = load_model()
        print("Whisper model initialized successfully!")
    except Exception as e:
        print(f"Error initializing Whisper model: {e}")
        model = None

def process_audio():
    """
    Transcript request audio file to text using Whisper
    """
    if model is None:
        print(DEBUG_PREFIX, "Whisper model not initialized yet.")
        abort(500, DEBUG_PREFIX + " Whisper model not initialized")
    
    try:
        file = request.files.get('AudioFile')
        if file is None:
            abort(400, DEBUG_PREFIX + " No audio file provided")
        
        language = request.form.get('language', default=None)
        
        # Читаем аудио данные в память
        audio_data = file.read()
        
        # Используем io.BytesIO для работы с данными в памяти
        audio_file = io.BytesIO(audio_data)
        
        # Загружаем аудио с помощью librosa напрямую из памяти
        # sr=16000 - стандартная частота дискретизации для Whisper
        audio_array, sample_rate = librosa.load(audio_file, sr=16000)
        
        # Transcribe using Whisper напрямую с numpy массивом
        segments, info = model.transcribe(audio_array, beam_size=5, language=language)
        
        # Combine all segments into a single transcript
        transcript = ""
        for segment in segments:
            transcript = transcript + " " + segment.text
        
        # Clean up the transcript (remove leading space)
        transcript = transcript.strip()
        
        print(DEBUG_PREFIX, "Transcripted from audio file (whisper):", transcript)
        
        return jsonify({"transcript": transcript})
        
    except Exception as e:
        print(f"{DEBUG_PREFIX} Exception: {e}")
        abort(500, DEBUG_PREFIX + " Exception occurs while processing audio")

def modules():
    """
    Emulate SillyTavernExtras API if you want to use this server for it
    Для совместимости с другими ИИ приложениями
    """
    return jsonify({"modules": ["whisper-stt"]})

# Register routes
app.add_url_rule(
    "/api/speech-recognition/whisper/process-audio",
    view_func=process_audio,
    methods=["POST"]
)

app.add_url_rule(
    "/api/modules",
    view_func=modules,
    methods=["POST", "GET"]
)

if __name__ == "__main__":
    # Initialize the model before starting the server
    initialize_model()
    
    if model is None:
        print("Failed to initialize Whisper model. Server will not start.")
        exit(1)
    
    print(f"Starting Whisper speech recognition server on {host}:{port}")
    app.run(host=host, port=port, debug=False)
