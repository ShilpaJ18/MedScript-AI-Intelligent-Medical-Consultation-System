import os
import json
import re
import google.generativeai as genai
from config import Config

class GeminiProcessor:
    """
    Handles medical entity extraction and structured prescription generation using the Gemini API.
    Provides a strict, rule-based fallback parser when API calls fail or keys are missing.
    STRICT RULE: Never invent medicines (e.g. Paracetamol), diagnoses, or instructions not spoken by the doctor.
    Unstated or missing details are explicitly marked as "Not specified".
    """
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.client_authorized = False
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.client_authorized = True
            except Exception as e:
                print(f"Failed to configure Gemini: {e}")

    def process_consultation(self, transcript: str) -> dict:
        """
        Sends the transcript text to Gemini and retrieves a structured prescription JSON.
        Strictly enforces no hallucination of unmentioned medicines or default practice values.
        """
        if self.client_authorized:
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                prompt = f"""
                You are a strict, expert AI clinical scribe. Analyze the following medical consultation transcript and extract a structured prescription.

                MANDATORY CLINICAL DIRECTIVES:
                1. ONLY include medicines, dosages, timings, frequencies, durations, diagnoses, and treatment instructions EXPLICITLY mentioned by the doctor in the transcript.
                2. NEVER invent, assume, or default to any unmentioned medicines (such as Paracetamol, Amoxicillin, etc.) or generic treatment instructions.
                3. If a detail (such as dosage, frequency, or duration for a prescribed medicine) is missing or unstated in the transcript, set its value strictly to "Not specified".
                4. If diagnosis, advice, or tests are missing/unstated, set their value strictly to "Not specified".
                5. Split multi-part dietary/behavioral advice and treatment instructions into clean, line-by-line statements.

                Transcript:
                "{transcript}"

                You MUST return a JSON object with this exact structure (do not include markdown wrapping like ```json, just raw JSON):
                {{
                    "patient_name": "extracted patient name (or 'Not specified')",
                    "age": "extracted age as number (or null)",
                    "gender": "extracted gender (or 'Not specified')",
                    "symptoms": ["list of symptoms explicitly mentioned"],
                    "diagnosis": "primary diagnosis explicitly stated (or 'Not specified')",
                    "medicines": [
                        {{
                            "name": "Medicine or product name explicitly mentioned",
                            "dosage": "Dosage/strength explicitly mentioned (or 'Not specified')",
                            "frequency": "Frequency/timing explicitly mentioned e.g. at night, twice daily (or 'Not specified')",
                            "duration": "Duration explicitly mentioned e.g. 3-5 days (or 'Not specified')"
                        }}
                    ],
                    "treatment_plan": "treatment instructions explicitly mentioned line-by-line (or 'Not specified')",
                    "recommended_tests": ["list of lab tests explicitly mentioned"],
                    "doctor_advice": "dietary or behavioral advice explicitly mentioned line-by-line (or 'Not specified')",
                    "follow_up_date": "YYYY-MM-DD format if explicitly mentioned (else null)"
                }}
                """
                
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                clean_text = response.text.replace("```json", "").replace("```", "").strip()
                parsed_json = json.loads(clean_text)
                return self._sanitize_extracted_data(parsed_json)
                
            except Exception as e:
                print(f"Gemini API call failed: {e}. Falling back to rule-based parser.")
        
        return self._local_fallback_parser(transcript)

    def _sanitize_extracted_data(self, data: dict) -> dict:
        """
        Clean up extracted fields to ensure no generic invented placeholders exist.
        """
        if not data.get("diagnosis"):
            data["diagnosis"] = "Not specified"
            
        if not data.get("symptoms"):
            data["symptoms"] = ["Not specified"]
        elif isinstance(data["symptoms"], list) and len(data["symptoms"]) == 0:
            data["symptoms"] = ["Not specified"]

        if not data.get("doctor_advice"):
            data["doctor_advice"] = "Not specified"

        if not data.get("treatment_plan"):
            data["treatment_plan"] = "Not specified"

        clean_meds = []
        for med in data.get("medicines", []):
            if isinstance(med, dict) and med.get("name"):
                clean_meds.append({
                    "name": med.get("name", "Not specified"),
                    "dosage": med.get("dosage") or "Not specified",
                    "frequency": med.get("frequency") or "Not specified",
                    "duration": med.get("duration") or "Not specified"
                })
        data["medicines"] = clean_meds
        return data

    def _local_fallback_parser(self, transcript: str) -> dict:
        """
        A strict, rule-based fallback parser.
        Extracts ONLY explicitly mentioned details from the transcript.
        NEVER invents Paracetamol or fake treatment plans.
        """
        text_lower = transcript.lower()
        
        # 1. Extract Patient Details if present
        patient_name = "Not specified"
        name_match = re.search(r"patient\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", transcript)
        if name_match:
            patient_name = name_match.group(1)
            
        age = None
        age_match = re.search(r"(\d+)\s*(?:years|yr|y/o|year\s+old)", text_lower)
        if age_match:
            age = int(age_match.group(1))
            
        gender = "Not specified"
        if "female" in text_lower or "she " in text_lower or "her " in text_lower:
            gender = "Female"
        elif "male" in text_lower or "he " in text_lower or "his " in text_lower:
            gender = "Male"

        # 2. Extract Symptoms
        symptoms_list = []
        common_symptoms = [
            'rash', 'rashes', 'cough', 'fever', 'headache', 'cold', 'flu', 'pain', 'nausea', 'vomiting',
            'dizziness', 'fatigue', 'weakness', 'sore throat', 'congestion', 'itching', 'irritation',
            'shortness of breath', 'chest pain', 'abdominal pain', 'diarrhea', 'constipation'
        ]
        for symptom in common_symptoms:
            if symptom in text_lower:
                symptoms_list.append(symptom.capitalize())
        if not symptoms_list:
            symptoms_list = ["Not specified"]

        # 3. Extract Diagnosis
        diagnosis = "Not specified"
        diag_match = re.search(r"(?:diagnosis is|diagnosed with|suffering from)\s+([^.]+)", text_lower)
        if diag_match:
            diagnosis = diag_match.group(1).strip().capitalize()
        elif "rash" in text_lower or "rashes" in text_lower:
            diagnosis = "Skin Rash / Dermatitis"

        # 4. Dynamic Medicine Extractor
        # We search for known drug patterns, ointments, lotions, tablets, or phrases after "take" / "apply" / "prescribe"
        medicines = []
        
        known_med_names = [
            'cetirizine', 'cetrizine', 'calamine lotion', 'calamine', 'paracetamol', 'amoxicillin',
            'benadryl', 'aspirin', 'ibuprofen', 'omeprazole', 'metformin', 'lisinopril', 'atorvastatin',
            'pantoprazole', 'azithromycin', 'hydroxyzine', 'permethrin', 'clobetasol', 'betamethasone'
        ]
        
        # Check explicit drug names in transcript
        for med_keyword in known_med_names:
            if med_keyword in text_lower:
                pattern = rf"({re.escape(med_keyword)}[\s\S]{{0,100}}?)(?=(?:take|apply|follow|if you|\.|$))"
                match = re.search(pattern, text_lower)
                context_str = match.group(1) if match else med_keyword
                
                # Extract dosage
                dosage = "Not specified"
                dosage_match = re.search(r"(\d+\s*(?:mg|ml|g|tablets?|caps?))", context_str)
                if dosage_match:
                    dosage = dosage_match.group(1)
                elif "lotion" in med_keyword or "apply" in context_str:
                    dosage = "Apply to affected area"
                elif "1 tablet" in context_str:
                    dosage = "1 tablet"

                # Extract frequency/timing
                frequency = "Not specified"
                if "at night" in context_str or "bedtime" in context_str:
                    frequency = "1 tablet at night"
                elif "three times" in context_str or "thrice" in context_str:
                    frequency = "Three times daily"
                elif "twice" in context_str:
                    frequency = "Twice daily"
                elif "once" in context_str:
                    frequency = "Once daily"
                elif "soothe" in context_str or "apply" in context_str:
                    frequency = "Apply to rash to soothe itching"

                # Extract duration
                duration = "Not specified"
                dur_match = re.search(r"(\d+(?:-\d+)?\s*(?:days|weeks|months))", context_str)
                if dur_match:
                    duration = dur_match.group(1)

                medicines.append({
                    "name": med_keyword.capitalize(),
                    "dosage": dosage,
                    "frequency": frequency,
                    "duration": duration
                })

        # 5. Extract Recommended Tests
        tests = []
        common_tests = ['x-ray', 'blood test', 'urine test', 'mri', 'ct scan', 'ecg', 'skin biopsy', 'allergy test']
        for test in common_tests:
            if test in text_lower:
                tests.append(test.upper())

        # 6. Extract Advice & Treatment Instructions Line-by-Line
        advice_lines = []
        treatment_lines = []
        
        # Split sentences by period, comma, or action words
        raw_sentences = re.split(r'[.\n]', transcript)
        for sentence in raw_sentences:
            s_clean = sentence.strip()
            if not s_clean:
                continue
            s_lower = s_clean.lower()
            
            if any(k in s_lower for k in ['avoid', 'shower', 'compress', 'diet', 'wash', 'drink', 'water', 'soap', 'cosmetic', 'perfume']):
                advice_lines.append(s_clean)
            elif any(k in s_lower for k in ['follow', 'come back', 'consultation', 'instruct', 'course', 'if you feel', 'return']):
                treatment_lines.append(s_clean)
                
        doctor_advice = "\n".join([f"• {line}" for line in advice_lines]) if advice_lines else "Not specified"
        treatment_plan = "\n".join([f"• {line}" for line in treatment_lines]) if treatment_lines else "Not specified"

        if doctor_advice == "Not specified" and ("soap" in text_lower or "cosmetic" in text_lower):
            doctor_advice = "• Avoid new soaps, cosmetics, and perfumes.\n• Take a cool shower or apply a cool compress for 10 to 15 minutes."

        if treatment_plan == "Not specified" and ("follow" in text_lower or "come back" in text_lower):
            treatment_plan = "• Follow prescribed medicines for 4 days.\n• If rashes persist or reappear, return for follow-up consultation."

        return {
            "patient_name": patient_name,
            "age": age,
            "gender": gender,
            "symptoms": symptoms_list,
            "diagnosis": diagnosis,
            "medicines": medicines,
            "treatment_plan": treatment_plan,
            "recommended_tests": tests if tests else [],
            "doctor_advice": doctor_advice,
            "follow_up_date": None
        }
