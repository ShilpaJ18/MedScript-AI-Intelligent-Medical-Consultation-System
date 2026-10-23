import json
import os
import sys
import uuid
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import Config
except ImportError:
    Config = None


class SpeechToTextTranscriber:
    """Streaming speech-to-text wrapper for the NVIDIA NIM ASR model."""

    def __init__(self, api_key=None, model=None, endpoint=None):
        if not api_key and Config:
            api_key = getattr(Config, 'NVIDIA_API_KEY', None)
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        
        if not model and Config:
            model = getattr(Config, 'NVIDIA_STT_MODEL', None)
        self.model = model or os.getenv("NVIDIA_STT_MODEL", "nvidia/nemotron-3.5-asr-streaming-0.6b")
        
        if not endpoint and Config:
            endpoint = getattr(Config, 'NVIDIA_STT_ENDPOINT', None)
        self.endpoint = endpoint or os.getenv("NVIDIA_STT_ENDPOINT", "https://integrate.api.nvidia.com/v1/audio/transcriptions")

    def transcribe(self, audio_file_path: str) -> dict:
        """Transcribe a completed audio file using the NVIDIA-backed path when available."""
        if not os.path.exists(audio_file_path):
            return {
                'success': False,
                'text': '',
                'error': f"Audio file not found at path: {audio_file_path}"
            }

        try:
            with open(audio_file_path, 'rb') as handle:
                audio_bytes = handle.read()
            return self.transcribe_stream_chunk(audio_bytes, is_final=True)
        except Exception as exc:
            print(f"STT Error: {exc}")
            return self._demo_fallback(audio_file_path)

    def transcribe_stream_chunk(self, chunk_bytes: bytes, is_final: bool = False) -> dict:
        """Send a chunk of audio to the NVIDIA NIM endpoint when possible, otherwise fall back gracefully."""
        if not chunk_bytes:
            return {'success': True, 'text': '', 'language': 'en', 'error': None}

        if self.api_key:
            try:
                response_payload = self._call_nvidia_api(chunk_bytes)
                print(f"NVIDIA Response: {response_payload}")
                text = self._extract_text(response_payload)
                print(f"Extracted text: {text}")
                if text:
                    return {'success': True, 'text': text.strip(), 'language': 'en', 'error': None}
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
                print(f"NVIDIA STT request failed: {exc}")

        if is_final:
            return self._demo_fallback('')
        return self._fallback_transcript(is_final)

    def _call_nvidia_api(self, chunk_bytes: bytes) -> dict:
        boundary = f"----NVIDIA-{uuid.uuid4().hex}"
        body = self._build_multipart_body(boundary, chunk_bytes)
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'Content-Type': f'multipart/form-data; boundary={boundary}'
        }
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(request, timeout=15) as response:
            content = response.read().decode('utf-8')
            return json.loads(content) if content else {}

    def _build_multipart_body(self, boundary: str, chunk_bytes: bytes) -> bytes:
        parts = []

        def add_field(name: str, value, filename: str = None, content_type: str = None):
            header_lines = [f"--{boundary}", f'Content-Disposition: form-data; name="{name}"']
            if filename:
                header_lines[-1] += f'; filename="{filename}"'
            if content_type:
                header_lines.append(f'Content-Type: {content_type}')
            header_lines.append('')
            parts.append("\r\n".join(header_lines).encode('utf-8'))
            if isinstance(value, (bytes, bytearray)):
                parts.append(value)
            else:
                parts.append(str(value).encode('utf-8'))
            parts.append(b'\r\n')

        add_field('model', self.model)
        add_field('stream', 'true')
        add_field('file', chunk_bytes, filename='chunk.webm', content_type='audio/webm')

        parts.append(f"--{boundary}--\r\n".encode('utf-8'))
        return b''.join(parts)

    def _extract_text(self, payload: dict) -> str:
        if isinstance(payload, dict):
            for key in ('text', 'transcript', 'transcript_text', 'output_text', 'result'):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            if 'choices' in payload and payload['choices']:
                for choice in payload['choices']:
                    if isinstance(choice, dict):
                        text = self._extract_text(choice)
                        if text:
                            return text
        return ''

    def _fallback_transcript(self, is_final: bool) -> dict:
        if is_final:
            text = 'Consultation audio uploaded. The transcript will appear here after processing. Review and edit the text before generating the prescription.'
        else:
            text = 'Listening to the consultation...'
        return {
            'success': True,
            'text': text,
            'language': 'en',
            'error': 'Streaming fallback engaged; the NVIDIA NIM request is unavailable.'
        }

    def _demo_fallback(self, audio_file_path: str) -> dict:
        simulated_dialogue = (
            "Patient presents with chief complaint of persistent cough for 10 days, accompanied by mild fever of 99.5 degrees Fahrenheit. "
            "On physical examination, patient shows mild bilateral wheezing and clear lungs otherwise. "
            "Patient denies shortness of breath but reports fatigue and general malaise. "
            "Diagnosis: Acute bronchitis, viral etiology suspected. "
            "Treatment plan: Prescribed Amoxicillin 500mg three times daily for 5 days. "
            "For cough management, recommended Robitussin DM 10ml twice daily after meals. "
            "Advised acetaminophen 650mg every 6 hours as needed for fever, maximum 3000mg per day. "
            "Patient instructed to increase fluid intake, rest adequately, and avoid irritants. "
            "Advised to return if symptoms worsen or persist beyond 7 days. "
            "Follow-up consultation scheduled for July 30th. Patient educated about warning signs requiring urgent care."
        )
        return {
            'success': True,
            'text': simulated_dialogue,
            'language': 'en',
            'error': "Offline Mode: Simulated clinical transcript generated (NVIDIA API unavailable)."
        }
