from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class MedicalTextSplitter:
    """
    Splits medical documents into chunks based on word count parameters:
    - Target Chunk Size: 400 words
    - Chunk Overlap: 60 words
    """

    def __init__(self, chunk_size_words: int = 400, chunk_overlap_words: int = 60):
        self.chunk_size_words = chunk_size_words
        self.chunk_overlap_words = chunk_overlap_words

        # Average English word is ~5 characters; adding safety factor for separators
        # 400 words ~ 2000-2400 chars; 60 words ~ 300-360 chars
        approx_char_size = chunk_size_words * 6
        approx_char_overlap = chunk_overlap_words * 6

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=approx_char_size,
            chunk_overlap=approx_char_overlap,
            length_function=self._word_count,
            separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""]
        )

    @staticmethod
    def _word_count(text: str) -> int:
        """Helper method to count words in a given text snippet."""
        return len(text.split())

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """
        Splits a list of raw Document objects into word-bound chunks.
        Preserves metadata for source attribution and citations.
        """
        if not documents:
            print("[Splitter] Warning: Received empty document list to split.")
            return []

        print(f"[Splitter] Splitting {len(documents)} raw documents into chunks "
              f"({self.chunk_size_words} words, {self.chunk_overlap_words} overlap)...")

        chunked_docs = self.splitter.split_documents(documents)

        # Attach chunk index metadata
        for i, chunk in enumerate(chunked_docs):
            chunk.metadata["chunk_id"] = i
            chunk.metadata["word_count"] = self._word_count(chunk.page_content)

        print(f"[Splitter] Created {len(chunked_docs)} chunked documents.")
        return chunked_docs
