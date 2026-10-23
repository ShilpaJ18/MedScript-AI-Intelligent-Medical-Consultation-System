import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.getenv("SECRET_KEY", "medical_audio_prescription_super_secret_key_12345")
    
    # DB settings
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
    MYSQL_DB = os.getenv("MYSQL_DB", "medical_audio_prescription_db")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    
    # Upload paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_AUDIO_FOLDER = os.path.join(BASE_DIR, 'uploads', 'audio')
    GENERATED_PDF_FOLDER = os.path.join(BASE_DIR, 'generated_pdfs')
    
    # AI settings (read from .env file or environment variables only)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_STT_MODEL = os.getenv("NVIDIA_STT_MODEL", "nvidia/nemotron-3.5-asr-streaming-0.6b")
    NVIDIA_STT_ENDPOINT = os.getenv("NVIDIA_STT_ENDPOINT", "https://integrate.api.nvidia.com/v1/audio/transcriptions")
    
    # Ensure folders exist
    os.makedirs(UPLOAD_AUDIO_FOLDER, exist_ok=True)
    os.makedirs(GENERATED_PDF_FOLDER, exist_ok=True)
