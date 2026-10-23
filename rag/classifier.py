import re
from spellchecker import SpellChecker
import google.generativeai as genai
from rag_config import RAGConfig


class QueryPreprocessor:
    """
    Cleans and preprocesses user queries before sending to the RAG pipeline.
    Includes spell correction and query normalization.
    """

    def __init__(self):
        self.spell = SpellChecker()
        # Medical terms that should NOT be spell-corrected
        self.medical_whitelist = {
            "acetaminophen", "ibuprofen", "amoxicillin", "metformin", "lisinopril",
            "atorvastatin", "omeprazole", "amlodipine", "simvastatin", "losartan",
            "gabapentin", "hydrochlorothiazide", "sertraline", "pantoprazole",
            "montelukast", "escitalopram", "rosuvastatin", "bupropion",
            "tachycardia", "bradycardia", "hypertension", "hypotension",
            "dyspnea", "tachypnea", "cyanosis", "edema", "hematemesis",
            "hematuria", "epistaxis", "syncope", "vertigo", "nausea",
            "anaphylaxis", "pneumonia", "bronchitis", "asthma", "copd",
            "diabetes", "insulin", "cholesterol", "thyroid", "arthritis",
            "osteoporosis", "fibromyalgia", "migraine", "epilepsy", "stroke",
            "hemorrhage", "fracture", "sprain", "contusion", "laceration",
            "abrasion", "concussion", "tourniquet", "defibrillator", "cpr",
            "anatomy", "physiology", "cardiovascular", "respiratory", "gastrointestinal",
            "musculoskeletal", "endocrine", "nervous", "integumentary", "lymphatic",
            "urinary", "reproductive", "homeostasis", "pathophysiology",
        }
        self.spell.word_frequency.load_words(self.medical_whitelist)

    def clean_query(self, query: str) -> str:
        """Normalizes and cleans user query text."""
        if not query:
            return ""
        # Remove excessive whitespace
        query = re.sub(r'\s+', ' ', query.strip())
        # Remove special characters but preserve medical hyphens and apostrophes
        query = re.sub(r'[^\w\s\-\'/?.!,]', '', query)
        return query

    def correct_spelling(self, query: str) -> str:
        """Applies spell correction while preserving medical terminology."""
        words = query.split()
        corrected = []
        for word in words:
            lower_word = word.lower().strip(".,!?;:")
            if lower_word in self.medical_whitelist or len(lower_word) <= 2:
                corrected.append(word)
            else:
                correction = self.spell.correction(lower_word)
                corrected.append(correction if correction else word)
        return " ".join(corrected)

    def preprocess(self, query: str) -> str:
        """Full preprocessing pipeline: clean → spell correct."""
        cleaned = self.clean_query(query)
        corrected = self.correct_spelling(cleaned)
        return corrected


class MedicalIntentClassifier:
    """
    Uses Google Gemini LLM to classify medical intent and severity.
    Categories:
        Intent: first_aid, general_medical, emergency
        Severity: mild, moderate, emergency
    """

    # Keywords for fast rule-based pre-classification (before calling LLM)
    EMERGENCY_KEYWORDS = [
        "heart attack", "cardiac arrest", "stroke", "seizure", "choking",
        "severe bleeding", "unconscious", "not breathing", "anaphylaxis",
        "overdose", "poisoning", "chest pain", "difficulty breathing",
        "can't breathe", "suicidal", "suicide", "unresponsive", "drowning",
        "severe burn", "electric shock", "gunshot", "stabbing",
    ]

    FIRST_AID_KEYWORDS = [
        "first aid", "bandage", "wound care", "burn treatment", "cpr",
        "heimlich", "splint", "tourniquet", "bleeding control", "bite",
        "sting", "sprain", "bruise", "cut", "scrape", "nosebleed",
        "frostbite", "heatstroke", "heat exhaustion", "recovery position",
    ]

    def __init__(self):
        genai.configure(api_key=RAGConfig.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(RAGConfig.GEMINI_MODEL_NAME)

    def _rule_based_check(self, query: str) -> dict:
        """Fast keyword-based pre-classification."""
        query_lower = query.lower()
        for kw in self.EMERGENCY_KEYWORDS:
            if kw in query_lower:
                return {"intent": "emergency", "severity": "emergency"}
        for kw in self.FIRST_AID_KEYWORDS:
            if kw in query_lower:
                return {"intent": "first_aid", "severity": "mild"}
        return None

    def classify(self, query: str) -> dict:
        """
        Classifies medical intent and severity for a user query.
        Returns dict: {"intent": str, "severity": str, "recommendation": str}
        """
        # Try fast rule-based classification first
        rule_result = self._rule_based_check(query)
        if rule_result:
            rule_result["recommendation"] = self._get_recommendation(rule_result["severity"])
            return rule_result

        # Fallback: Use Gemini LLM classification
        try:
            prompt = f"""You are a medical triage assistant. Classify the following patient query.

Query: "{query}"

Respond ONLY in this exact format (no other text):
intent: [first_aid OR general_medical OR emergency]
severity: [mild OR moderate OR emergency]

Rules:
- "emergency": life-threatening symptoms (chest pain, severe bleeding, unconsciousness, stroke symptoms, difficulty breathing)
- "moderate": symptoms needing doctor visit (persistent pain, fever >3 days, infection signs, unusual symptoms)
- "mild": minor issues manageable with self-care (common cold, minor cuts, headache, mild allergies)
- "first_aid": injury/accident-related queries
- "general_medical": anatomy, disease info, medication questions
- "emergency" intent: any immediately life-threatening situation"""

            response = self.model.generate_content(prompt)
            text = response.text.strip().lower()

            # Parse structured response
            intent = "general_medical"
            severity = "mild"

            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("intent:"):
                    val = line.split(":", 1)[1].strip()
                    if val in ["first_aid", "general_medical", "emergency"]:
                        intent = val
                elif line.startswith("severity:"):
                    val = line.split(":", 1)[1].strip()
                    if val in ["mild", "moderate", "emergency"]:
                        severity = val

            return {
                "intent": intent,
                "severity": severity,
                "recommendation": self._get_recommendation(severity)
            }
        except Exception as e:
            print(f"[Classifier Error] LLM classification failed: {str(e)}")
            return {
                "intent": "general_medical",
                "severity": "moderate",
                "recommendation": "Please consult a healthcare professional for proper assessment."
            }

    @staticmethod
    def _get_recommendation(severity: str) -> str:
        """Maps severity to care recommendation."""
        recommendations = {
            "mild": "This appears to be a mild condition. Self-care measures may be sufficient, but consult a doctor if symptoms persist.",
            "moderate": "This condition may require medical attention. Please schedule a visit with your healthcare provider.",
            "emergency": "⚠️ EMERGENCY: This may be a life-threatening situation. Please call emergency services (911) or go to the nearest emergency room IMMEDIATELY."
        }
        return recommendations.get(severity, recommendations["moderate"])
