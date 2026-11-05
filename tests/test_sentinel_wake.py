import unittest

from sentinel import WAKE_COOLDOWN_SECONDS, wake_phrase_matches


class WakePhraseTests(unittest.TestCase):
    def test_shutdown_cooldown_prevents_the_termination_phrase_from_retriggering(self):
        self.assertGreaterEqual(WAKE_COOLDOWN_SECONDS, 20)

    def test_accepts_only_confident_wake_phrases(self):
        self.assertTrue(wake_phrase_matches({
            "text": "hey jarvis",
            "result": [
                {"word": "hey", "conf": 0.94},
                {"word": "jarvis", "conf": 0.88},
            ],
        }))

    def test_rejects_background_words_that_only_contain_the_alias(self):
        self.assertFalse(wake_phrase_matches({
            "text": "service",
            "result": [{"word": "service", "conf": 0.99}],
        }))
        self.assertFalse(wake_phrase_matches({
            "text": "jarvis turn on",
            "result": [
                {"word": "jarvis", "conf": 0.98},
                {"word": "turn", "conf": 0.96},
                {"word": "on", "conf": 0.97},
            ],
        }))

    def test_rejects_low_confidence_or_missing_word_scores(self):
        self.assertFalse(wake_phrase_matches({
            "text": "jarvis",
            "result": [{"word": "jarvis", "conf": 0.5}],
        }))
        self.assertFalse(wake_phrase_matches({"text": "jarvis", "result": []}))


if __name__ == "__main__":
    unittest.main()
