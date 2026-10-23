import unittest

from ai.speech_to_text import SpeechToTextTranscriber


class SpeechToTextTranscriberTests(unittest.TestCase):
    def test_stream_chunk_falls_back_to_live_text_when_api_is_unavailable(self):
        transcriber = SpeechToTextTranscriber(api_key="test-key")
        result = transcriber.transcribe_stream_chunk(b"fake-audio-bytes", is_final=False)

        self.assertTrue(result["success"])
        self.assertIn("Live transcription", result["text"])


if __name__ == "__main__":
    unittest.main()
