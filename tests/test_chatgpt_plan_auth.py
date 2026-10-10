import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from handlers.llm_providers.chatgpt_plan_auth import make_pkce_pair, validate_id_token_claims


class ChatGPTPlanAuthTests(unittest.TestCase):
    def test_pkce_pair_is_s256_and_unpadded(self):
        verifier, challenge = make_pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertNotIn("=", challenge)
        self.assertNotEqual(verifier, challenge)

    def test_id_token_claims_require_issuer_audience_nonce_and_expiry(self):
        now = int(time.time())
        claims = {
            "iss": "https://auth.openai.com",
            "aud": "oaiapp_test",
            "sub": "account-1",
            "nonce": "nonce-1",
            "exp": now + 300,
        }
        validate_id_token_claims(claims, client_id="oaiapp_test", nonce="nonce-1", now=now)
        with self.assertRaises(ValueError):
            validate_id_token_claims(claims, client_id="other", nonce="nonce-1", now=now)
        with self.assertRaises(ValueError):
            validate_id_token_claims(claims, client_id="oaiapp_test", nonce="wrong", now=now)


if __name__ == "__main__":
    unittest.main()
