"""
Medical RAG Chatbot - Flask API Module
Provides /chat endpoint and /rag-chatbot UI page.
This is a SEPARATE Flask Blueprint that gets registered into the main app.py
so existing audio-to-prescription and appointment booking routes are NOT disturbed.
"""

import uuid
from flask import Blueprint, request, jsonify, render_template, session

from rag.pipeline import MedicalRAGPipeline
from rag.chat_history import ChatHistoryManager

# Create Flask Blueprint (does NOT interfere with existing app routes)
rag_bp = Blueprint('rag_chatbot', __name__, template_folder='templates')

# Lazy initialization of pipeline (initialized on first request)
_pipeline = None
_chat_history = None


def _get_pipeline():
    """Lazily initializes the RAG pipeline (loads vector store on first call only)."""
    global _pipeline
    if _pipeline is None:
        print("[RAG API] Initializing Medical RAG Pipeline (first request)...")
        _pipeline = MedicalRAGPipeline()
        print("[RAG API] Pipeline ready.")
    return _pipeline


def _get_chat_history():
    """Lazily initializes chat history manager."""
    global _chat_history
    if _chat_history is None:
        _chat_history = ChatHistoryManager()
    return _chat_history


@rag_bp.route('/rag-chatbot')
def rag_chatbot_page():
    """Renders the Medical RAG Chatbot UI page."""
    return render_template('chat.html')


@rag_bp.route('/chat', methods=['POST'])
def chat():
    """
    Medical RAG Chatbot API Endpoint.
    Accepts JSON: {"question": "your medical question here"}
    Returns JSON with answer, intent, severity, recommendation, and sources.
    """
    try:
        data = request.get_json()

        if not data or 'question' not in data:
            return jsonify({
                "error": "Missing 'question' field in request body.",
                "usage": "POST /chat with JSON body: {\"question\": \"your medical question\"}"
            }), 400

        question = data['question'].strip()
        if not question:
            return jsonify({"error": "Question cannot be empty."}), 400

        # Get or create session ID for chat history tracking
        session_id = data.get('session_id', str(uuid.uuid4()))

        # Execute RAG pipeline
        pipeline = _get_pipeline()
        result = pipeline.query(question)

        # Save to chat history
        try:
            chat_hist = _get_chat_history()
            chat_hist.save_chat(session_id, result)
        except Exception as e:
            print(f"[RAG API Warning] Failed to save chat history: {str(e)}")

        # Build response
        response = {
            "success": True,
            "session_id": session_id,
            "question": result.get("question", question),
            "answer": result.get("answer", ""),
            "intent": result.get("intent", ""),
            "severity": result.get("severity", ""),
            "recommendation": result.get("recommendation", ""),
            "sources": result.get("sources", [])
        }

        return jsonify(response), 200

    except Exception as e:
        print(f"[RAG API Error] {str(e)}")
        return jsonify({
            "success": False,
            "error": "An internal error occurred. Please try again.",
            "details": str(e)
        }), 500


@rag_bp.route('/chat/history', methods=['GET'])
def get_chat_history():
    """Retrieves chat history for a specific session."""
    try:
        session_id = request.args.get('session_id', '')
        if not session_id:
            return jsonify({"error": "Missing 'session_id' query parameter."}), 400

        chat_hist = _get_chat_history()
        history = chat_hist.get_session_history(session_id)

        return jsonify({
            "success": True,
            "session_id": session_id,
            "history": history,
            "count": len(history)
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
