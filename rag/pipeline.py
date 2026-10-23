from typing import List, Dict, Any
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from rag_config import RAGConfig
from rag.vector_store import VectorStoreManager
from rag.classifier import QueryPreprocessor, MedicalIntentClassifier


# --- Medical RAG Prompt Template ---
MEDICAL_RAG_PROMPT = """You are a highly knowledgeable and empathetic Medical AI Assistant.
Your role is to provide accurate, evidence-based medical information using ONLY the provided context.

SEVERITY CLASSIFICATION: {severity}
INTENT: {intent}
CARE RECOMMENDATION: {recommendation}

CONTEXT FROM MEDICAL KNOWLEDGE BASE:
{context}

USER QUESTION: {question}

INSTRUCTIONS:
1. Answer the question using ONLY the information found in the provided context above.
2. If the context does not contain enough information to answer the question, clearly state:
   "I don't have sufficient information in my medical knowledge base to answer this question accurately. Please consult a qualified healthcare professional for personalized medical advice."
3. Structure your response clearly with:
   - A direct answer to the question
   - Supporting details from the context
   - Relevant medical terminology explained in simple terms
4. For EMERGENCY severity queries, always begin with the emergency recommendation.
5. Always end with a medical disclaimer reminding the user that this is for informational purposes only.
6. Cite the source of information where possible (e.g., "According to Anatomy & Physiology 2e..." or "Based on IFRC First Aid Guidelines...").

RESPONSE:"""


class MedicalRAGPipeline:
    """
    Production-grade Medical RAG Pipeline.
    Orchestrates: Query Preprocessing → Intent/Severity Classification →
    Vector Retrieval (Top 5) → Gemini LLM Generation → Safety Layer.
    """

    def __init__(self, vector_store_manager: VectorStoreManager = None):
        # Initialize components
        self.preprocessor = QueryPreprocessor()
        self.classifier = MedicalIntentClassifier()
        self.vector_manager = vector_store_manager or VectorStoreManager()

        # Ensure vector store is loaded/built
        self.vector_manager.build_vector_store()
        self.retriever = self.vector_manager.get_retriever(top_k=RAGConfig.TOP_K)

        # Initialize Gemini LLM via LangChain
        self.llm = ChatGoogleGenerativeAI(
            model=RAGConfig.GEMINI_MODEL_NAME,
            google_api_key=RAGConfig.GEMINI_API_KEY,
            temperature=0.3,
            max_output_tokens=2048
        )

        # Build LangChain prompt
        self.prompt = ChatPromptTemplate.from_template(MEDICAL_RAG_PROMPT)
        self.output_parser = StrOutputParser()

    @staticmethod
    def _format_context(docs: List[Document]) -> str:
        """Formats retrieved documents into a structured context string with source info."""
        if not docs:
            return "No relevant context found in the medical knowledge base."

        context_parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", "N/A")
            doc_type = doc.metadata.get("type", "unknown")

            if doc_type == "pdf":
                header = f"[Source {i}: {source}, Page {page}]"
            elif doc_type == "medquad_csv":
                focus = doc.metadata.get("focus", "General")
                header = f"[Source {i}: MedQuAD - {focus}]"
            else:
                header = f"[Source {i}: {source}]"

            context_parts.append(f"{header}\n{doc.page_content}")

        return "\n\n---\n\n".join(context_parts)

    def _extract_sources(self, docs: List[Document]) -> List[Dict[str, Any]]:
        """Extracts citation metadata from retrieved documents."""
        sources = []
        for doc in docs:
            source_info = {
                "source": doc.metadata.get("source", "Unknown"),
                "page": doc.metadata.get("page", "N/A"),
                "type": doc.metadata.get("type", "unknown"),
                "chunk_id": doc.metadata.get("chunk_id", "N/A"),
            }
            if doc.metadata.get("focus"):
                source_info["focus"] = doc.metadata["focus"]
            sources.append(source_info)
        return sources

    def query(self, user_question: str) -> Dict[str, Any]:
        """
        Full RAG pipeline execution:
        1. Preprocess query (clean + spell correct)
        2. Classify intent and severity
        3. Retrieve top 5 relevant chunks from vector store
        4. Generate grounded answer using Gemini LLM
        5. Attach safety recommendations and source citations
        """
        result = {
            "question": user_question,
            "answer": "",
            "intent": "",
            "severity": "",
            "recommendation": "",
            "sources": [],
            "error": None
        }

        try:
            # Step 1: Preprocess query
            processed_query = self.preprocessor.preprocess(user_question)
            print(f"[Pipeline] Preprocessed query: '{processed_query}'")

            # Step 2: Classify intent and severity
            classification = self.classifier.classify(processed_query)
            result["intent"] = classification["intent"]
            result["severity"] = classification["severity"]
            result["recommendation"] = classification["recommendation"]
            print(f"[Pipeline] Classification: {classification}")

            # Step 3: Retrieve top 5 relevant chunks
            retrieved_docs = self.retriever.invoke(processed_query)
            print(f"[Pipeline] Retrieved {len(retrieved_docs)} relevant chunks.")

            # Step 4: Format context and generate answer
            context = self._format_context(retrieved_docs)

            chain_input = {
                "context": context,
                "question": processed_query,
                "severity": classification["severity"].upper(),
                "intent": classification["intent"].upper(),
                "recommendation": classification["recommendation"]
            }

            # Execute LangChain chain
            chain = self.prompt | self.llm | self.output_parser
            answer = chain.invoke(chain_input)
            result["answer"] = answer

            # Step 5: Extract source citations
            result["sources"] = self._extract_sources(retrieved_docs)

            print(f"[Pipeline] Response generated successfully.")

        except Exception as e:
            error_msg = f"An error occurred while processing your question: {str(e)}"
            print(f"[Pipeline Error] {error_msg}")
            result["answer"] = (
                "I apologize, but I encountered an error while processing your question. "
                "Please try again or consult a healthcare professional for immediate assistance."
            )
            result["error"] = str(e)

        return result
