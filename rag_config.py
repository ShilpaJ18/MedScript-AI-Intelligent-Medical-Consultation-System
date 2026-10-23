import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class RAGConfig:
    """
    Configuration settings for Medical RAG Chatbot module.
    Preserves existing application settings and isolates RAG parameters.
    """
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Google Gemini API key
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

    # Knowledge Base PDF Paths
    ANATOMY_PDF_PATH = os.getenv(
        "ANATOMY_PDF_PATH",
        r"C:\Users\Shilpa\Downloads\anatomy-and-physiology-2e_-_WEB.pdf"
    )
    FIRST_AID_PDF_PATH = os.getenv(
        "FIRST_AID_PDF_PATH",
        r"C:\Users\Shilpa\Downloads\guideline-170-en.pdf"
    )
    MEDQUAD_CSV_PATH = os.getenv(
        "MEDQUAD_CSV_PATH",
        os.path.join(BASE_DIR, "data", "medquad.csv")
    )

    # Document Chunking Settings (400 words, 60 overlap)
    CHUNK_SIZE_WORDS = int(os.getenv("CHUNK_SIZE_WORDS", 400))
    CHUNK_OVERLAP_WORDS = int(os.getenv("CHUNK_OVERLAP_WORDS", 60))

    # Embeddings Model
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

    # Vector Store Settings
    VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "faiss")  # "faiss" or "chroma"
    FAISS_INDEX_DIR = os.path.join(BASE_DIR, "vector_store_data", "faiss_index")
    CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "vector_store_data", "chroma_db")

    # Retrieval Top-K
    TOP_K = int(os.getenv("TOP_K", 5))

    # Database for Chat History (reuses MySQL if available, falls back to SQLite)
    USE_MYSQL = os.getenv("USE_MYSQL", "true").lower() == "true"
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
    MYSQL_DB = os.getenv("MYSQL_DB", "medical_audio_prescription_db")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    SQLITE_DB_PATH = os.path.join(BASE_DIR, "database", "rag_chat_history.db")

    @classmethod
    def validate_paths(cls):
        """Returns diagnostic info about configured knowledge base paths."""
        status = {
            "anatomy_pdf": os.path.exists(cls.ANATOMY_PDF_PATH),
            "first_aid_pdf": os.path.exists(cls.FIRST_AID_PDF_PATH),
            "medquad_csv": os.path.exists(cls.MEDQUAD_CSV_PATH),
        }
        return status
