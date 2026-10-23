from langchain_community.embeddings import HuggingFaceEmbeddings
from rag_config import RAGConfig


class EmbeddingManager:
    """
    Embedding Provider for Medical RAG System.
    Loads and provides the SentenceTransformer 'all-MiniLM-L6-v2' model
    compatible with LangChain FAISS and ChromaDB vector stores.
    """

    def __init__(self, model_name: str = None):
        self.model_name = model_name or RAGConfig.EMBEDDING_MODEL_NAME
        self.embeddings = None
        self._initialize_embeddings()

    def _initialize_embeddings(self):
        """Initializes HuggingFaceEmbeddings using sentence-transformers model."""
        print(f"[Embeddings] Loading embedding model '{self.model_name}'...")
        try:
            model_kwargs = {'device': 'cpu'}
            encode_kwargs = {'normalize_embeddings': True}

            self.embeddings = HuggingFaceEmbeddings(
                model_name=self.model_name,
                model_kwargs=model_kwargs,
                encode_kwargs=encode_kwargs
            )
            print(f"[Embeddings] Model '{self.model_name}' successfully loaded.")
        except Exception as e:
            print(f"[Embeddings Error] Failed to initialize embedding model '{self.model_name}': {str(e)}")
            raise e

    def get_embeddings_model(self) -> HuggingFaceEmbeddings:
        """Returns the initialized LangChain embeddings instance."""
        if self.embeddings is None:
            self._initialize_embeddings()
        return self.embeddings
