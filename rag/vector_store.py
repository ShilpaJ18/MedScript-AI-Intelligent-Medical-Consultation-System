import os
from typing import List, Tuple
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS, Chroma

from rag_config import RAGConfig
from rag.embeddings import EmbeddingManager
from rag.loader import DocumentLoader
from rag.splitter import MedicalTextSplitter


class VectorStoreManager:
    """
    Manages persistent FAISS / ChromaDB vector databases.
    Ensures vector store is built ONLY ONCE and reused on subsequent runs.
    """

    def __init__(
        self,
        store_type: str = None,
        embedding_manager: EmbeddingManager = None
    ):
        self.store_type = (store_type or RAGConfig.VECTOR_STORE_TYPE).lower()
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.embeddings = self.embedding_manager.get_embeddings_model()
        self.vector_store = None

        self.faiss_dir = RAGConfig.FAISS_INDEX_DIR
        self.chroma_dir = RAGConfig.CHROMA_PERSIST_DIR

    def is_store_built(self) -> bool:
        """Checks if persistent index already exists on disk."""
        if self.store_type == "faiss":
            index_file = os.path.join(self.faiss_dir, "index.faiss")
            return os.path.exists(index_file)
        elif self.store_type in ["chroma", "chromadb"]:
            return os.path.exists(self.chroma_dir) and len(os.listdir(self.chroma_dir)) > 0
        return False

    def build_vector_store(self, documents: List[Document] = None, force_rebuild: bool = False):
        """
        Builds persistent vector store if it doesn't exist, or loads existing index from disk.
        """
        if self.is_store_built() and not force_rebuild:
            print(f"[VectorStore] Existing {self.store_type.upper()} index found. Loading from disk...")
            self.load_vector_store()
            return

        print(f"[VectorStore] No existing index found (or force_rebuild=True). Building {self.store_type.upper()} index...")

        # If documents not provided, load and split automatically
        if not documents:
            loader = DocumentLoader(
                pdf_paths=[RAGConfig.ANATOMY_PDF_PATH, RAGConfig.FIRST_AID_PDF_PATH],
                medquad_csv_path=RAGConfig.MEDQUAD_CSV_PATH
            )
            raw_docs = loader.load_all()
            if not raw_docs:
                print("[VectorStore Error] No documents loaded! Vector store creation aborted.")
                return

            splitter = MedicalTextSplitter(
                chunk_size_words=RAGConfig.CHUNK_SIZE_WORDS,
                chunk_overlap_words=RAGConfig.CHUNK_OVERLAP_WORDS
            )
            documents = splitter.split_documents(raw_docs)

        if not documents:
            print("[VectorStore Error] Document list is empty after splitting.")
            return

        print(f"[VectorStore] Generating embeddings and indexing {len(documents)} chunks into {self.store_type.upper()}...")

        try:
            if self.store_type == "faiss":
                os.makedirs(self.faiss_dir, exist_ok=True)
                self.vector_store = FAISS.from_documents(documents, self.embeddings)
                self.vector_store.save_local(self.faiss_dir)
                print(f"[VectorStore] FAISS index saved successfully to '{self.faiss_dir}'.")
            else:  # Chroma
                os.makedirs(self.chroma_dir, exist_ok=True)
                self.vector_store = Chroma.from_documents(
                    documents=documents,
                    embedding=self.embeddings,
                    persist_directory=self.chroma_dir
                )
                print(f"[VectorStore] ChromaDB index saved successfully to '{self.chroma_dir}'.")
        except Exception as e:
            print(f"[VectorStore Error] Failed to build vector store: {str(e)}")
            raise e

    def load_vector_store(self):
        """Loads persistent vector store from disk."""
        try:
            if self.store_type == "faiss":
                if not os.path.exists(self.faiss_dir):
                    raise FileNotFoundError(f"FAISS index directory '{self.faiss_dir}' does not exist.")
                self.vector_store = FAISS.load_local(
                    self.faiss_dir,
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
                print(f"[VectorStore] FAISS index loaded from '{self.faiss_dir}'.")
            else:
                self.vector_store = Chroma(
                    persist_directory=self.chroma_dir,
                    embedding_function=self.embeddings
                )
                print(f"[VectorStore] ChromaDB loaded from '{self.chroma_dir}'.")
        except Exception as e:
            print(f"[VectorStore Error] Error loading vector store: {str(e)}")
            raise e

    def get_retriever(self, top_k: int = None):
        """Returns a LangChain retriever configured to fetch top_k relevant chunks."""
        k = top_k or RAGConfig.TOP_K
        if self.vector_store is None:
            self.build_vector_store()
        return self.vector_store.as_retriever(search_kwargs={"k": k})

    def similarity_search_with_score(self, query: str, top_k: int = None) -> List[Tuple[Document, float]]:
        """
        Executes similarity search returning top K matching documents with similarity scores.
        """
        k = top_k or RAGConfig.TOP_K
        if self.vector_store is None:
            self.build_vector_store()

        try:
            results = self.vector_store.similarity_search_with_score(query, k=k)
            return results
        except Exception as e:
            print(f"[VectorStore Error] Search failed for query '{query}': {str(e)}")
            return []
