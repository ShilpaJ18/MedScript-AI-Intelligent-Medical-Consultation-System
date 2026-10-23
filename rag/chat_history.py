import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional

from rag_config import RAGConfig

# Conditional MySQL import
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False


class ChatHistoryManager:
    """
    Manages chat history persistence for the Medical RAG Chatbot.
    Supports MySQL (primary) and SQLite (fallback) backends.
    Designed to coexist with the existing medical_audio_prescription_db.
    """

    def __init__(self):
        self.use_mysql = RAGConfig.USE_MYSQL and MYSQL_AVAILABLE
        self.connection = None
        self._initialize_db()

    def _initialize_db(self):
        """Creates the chat_history table if it doesn't exist."""
        try:
            if self.use_mysql:
                self._init_mysql()
            else:
                self._init_sqlite()
            print(f"[ChatHistory] Database initialized ({'MySQL' if self.use_mysql else 'SQLite'}).")
        except Exception as e:
            print(f"[ChatHistory Error] DB initialization failed: {str(e)}")
            # Fallback to SQLite if MySQL fails
            if self.use_mysql:
                print("[ChatHistory] Falling back to SQLite...")
                self.use_mysql = False
                self._init_sqlite()

    def _init_mysql(self):
        """Initializes MySQL connection and creates rag_chat_history table."""
        self.connection = mysql.connector.connect(
            host=RAGConfig.MYSQL_HOST,
            user=RAGConfig.MYSQL_USER,
            password=RAGConfig.MYSQL_PASSWORD,
            database=RAGConfig.MYSQL_DB,
            port=RAGConfig.MYSQL_PORT
        )
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rag_chat_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(100) NOT NULL,
                user_question TEXT NOT NULL,
                bot_answer TEXT NOT NULL,
                intent VARCHAR(50),
                severity VARCHAR(50),
                recommendation TEXT,
                sources JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_session (session_id),
                INDEX idx_created (created_at)
            )
        """)
        self.connection.commit()
        cursor.close()

    def _init_sqlite(self):
        """Initializes SQLite database and creates rag_chat_history table."""
        os.makedirs(os.path.dirname(RAGConfig.SQLITE_DB_PATH), exist_ok=True)
        self.connection = sqlite3.connect(RAGConfig.SQLITE_DB_PATH, check_same_thread=False)
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rag_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_question TEXT NOT NULL,
                bot_answer TEXT NOT NULL,
                intent TEXT,
                severity TEXT,
                recommendation TEXT,
                sources TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.connection.commit()
        cursor.close()

    def _get_connection(self):
        """Returns active DB connection, reconnecting if necessary."""
        if self.use_mysql:
            if self.connection is None or not self.connection.is_connected():
                self._init_mysql()
        else:
            if self.connection is None:
                self._init_sqlite()
        return self.connection

    def save_chat(self, session_id: str, rag_result: Dict[str, Any]):
        """Saves a single chat exchange (question + response) to the database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sources_json = json.dumps(rag_result.get("sources", []))

            if self.use_mysql:
                cursor.execute("""
                    INSERT INTO rag_chat_history
                    (session_id, user_question, bot_answer, intent, severity, recommendation, sources)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    session_id,
                    rag_result.get("question", ""),
                    rag_result.get("answer", ""),
                    rag_result.get("intent", ""),
                    rag_result.get("severity", ""),
                    rag_result.get("recommendation", ""),
                    sources_json
                ))
            else:
                cursor.execute("""
                    INSERT INTO rag_chat_history
                    (session_id, user_question, bot_answer, intent, severity, recommendation, sources)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    rag_result.get("question", ""),
                    rag_result.get("answer", ""),
                    rag_result.get("intent", ""),
                    rag_result.get("severity", ""),
                    rag_result.get("recommendation", ""),
                    sources_json
                ))

            conn.commit()
            cursor.close()
            print(f"[ChatHistory] Chat saved for session '{session_id}'.")
        except Exception as e:
            print(f"[ChatHistory Error] Failed to save chat: {str(e)}")

    def get_session_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves chat history for a specific session."""
        history = []
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            placeholder = "%s" if self.use_mysql else "?"
            cursor.execute(f"""
                SELECT user_question, bot_answer, intent, severity, recommendation, sources, created_at
                FROM rag_chat_history
                WHERE session_id = {placeholder}
                ORDER BY created_at ASC
                LIMIT {placeholder}
            """, (session_id, limit))

            rows = cursor.fetchall()
            for row in rows:
                history.append({
                    "question": row[0],
                    "answer": row[1],
                    "intent": row[2],
                    "severity": row[3],
                    "recommendation": row[4],
                    "sources": json.loads(row[5]) if row[5] else [],
                    "timestamp": str(row[6])
                })
            cursor.close()
        except Exception as e:
            print(f"[ChatHistory Error] Failed to retrieve history: {str(e)}")
        return history

    def close(self):
        """Closes database connection."""
        if self.connection:
            try:
                self.connection.close()
                print("[ChatHistory] Database connection closed.")
            except Exception:
                pass
