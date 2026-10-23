import os
import fitz  # PyMuPDF
import pandas as pd
from typing import List, Dict, Any
from langchain_core.documents import Document


class DocumentLoader:
    """
    Modular Document Loader for Medical RAG Chatbot.
    Loads and extracts text from:
    1. PDFs (Anatomy & Physiology 2e, IFRC First Aid Guidelines) via PyMuPDF.
    2. MedQuAD dataset (CSV) combining Question and Answer into structured documents.
    """

    def __init__(self, pdf_paths: List[str] = None, medquad_csv_path: str = None):
        self.pdf_paths = pdf_paths or []
        self.medquad_csv_path = medquad_csv_path

    def load_pdf(self, pdf_path: str) -> List[Document]:
        """
        Extracts text from a single PDF using PyMuPDF (fitz).
        Returns a list of LangChain Document objects with page-level metadata.
        """
        documents = []
        if not os.path.exists(pdf_path):
            print(f"[Warning] PDF file not found at path: {pdf_path}")
            return documents

        file_basename = os.path.basename(pdf_path)
        try:
            doc = fitz.open(pdf_path)
            print(f"[Loader] Extracting text from '{file_basename}' ({len(doc)} pages)...")
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text("text")
                if text and text.strip():
                    documents.append(
                        Document(
                            page_content=text.strip(),
                            metadata={
                                "source": file_basename,
                                "page": page_num + 1,
                                "file_path": pdf_path,
                                "type": "pdf"
                            }
                        )
                    )
            doc.close()
            print(f"[Loader] Successfully loaded {len(documents)} page documents from '{file_basename}'.")
        except Exception as e:
            print(f"[Error] Failed to read PDF '{pdf_path}': {str(e)}")

        return documents

    def load_medquad_csv(self, csv_path: str = None) -> List[Document]:
        """
        Loads the MedQuAD dataset CSV.
        Combines each Question + Answer into one coherent document chunk.
        """
        target_path = csv_path or self.medquad_csv_path
        documents = []

        if not target_path or not os.path.exists(target_path):
            print(f"[Info] MedQuAD CSV not found at '{target_path}'. Skipping MedQuAD load.")
            return documents

        try:
            df = pd.read_csv(target_path)
            print(f"[Loader] Reading MedQuAD dataset from '{target_path}' ({len(df)} records)...")

            # Identify column names flexibly (case-insensitive)
            col_map = {col.lower(): col for col in df.columns}
            q_col = col_map.get("question", col_map.get("q", None))
            a_col = col_map.get("answer", col_map.get("a", None))
            focus_col = col_map.get("focus", col_map.get("topic", None))

            for idx, row in df.iterrows():
                question = str(row[q_col]).strip() if q_col and pd.notna(row[q_col]) else ""
                answer = str(row[a_col]).strip() if a_col and pd.notna(row[a_col]) else ""
                focus = str(row[focus_col]).strip() if focus_col and pd.notna(row[focus_col]) else "General"

                if question or answer:
                    combined_text = f"Medical Focus: {focus}\nQuestion: {question}\nAnswer: {answer}"
                    documents.append(
                        Document(
                            page_content=combined_text,
                            metadata={
                                "source": "MedQuAD_Dataset",
                                "row_id": idx,
                                "focus": focus,
                                "type": "medquad_csv"
                            }
                        )
                    )
            print(f"[Loader] Successfully created {len(documents)} MedQuAD documents.")
        except Exception as e:
            print(f"[Error] Failed loading MedQuAD CSV '{target_path}': {str(e)}")

        return documents

    def load_all(self, pdf_paths: List[str] = None, csv_path: str = None) -> List[Document]:
        """
        Combines and loads all documents from both PDF books and MedQuAD CSV dataset.
        """
        all_documents = []
        target_pdfs = pdf_paths if pdf_paths is not None else self.pdf_paths
        target_csv = csv_path if csv_path is not None else self.medquad_csv_path

        for pdf in target_pdfs:
            pdf_docs = self.load_pdf(pdf)
            all_documents.extend(pdf_docs)

        if target_csv:
            csv_docs = self.load_medquad_csv(target_csv)
            all_documents.extend(csv_docs)

        print(f"[Loader] Total documents loaded across all knowledge sources: {len(all_documents)}")
        return all_documents
