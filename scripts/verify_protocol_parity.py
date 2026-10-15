"""Run the offline protocol regression suite without collecting bundled libraries."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/test_chat_completions_adapter.py",
    "tests/test_responses_adapter.py",
    "tests/test_responses_provider.py",
    "tests/test_protocol_schema_parity.py",
    "tests/test_protocol_contract.py",
    "tests/test_protocol_routing_runner.py",
    "tests/test_native_tools_runtime.py",
    "tests/test_protocol_parity_e2e.py",
    "tests/test_chatgpt_plan_protocol.py",
    "tests/test_chatgpt_plan_provider.py",
    "tests/test_chatgpt_plan_structured_output.py",
    "tests/test_chatgpt_plan_recovery.py",
    "tests/test_chatgpt_plan_architecture.py",
    "tests/test_api_key_responses_configuration.py",
    "src/utils/Testing/test_llm_http_transport.py",
    "src/utils/Testing/test_provider_errors.py",
    "src/utils/Testing/test_structured_response_capabilities.py",
    "src/utils/Testing/test_sparse_structured_response.py",
)


def main() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="neuromita-protocol-tests-") as temporary:
        env["NEUROMITA_LOG_PATH"] = str(Path(temporary) / "protocol-tests.log")
        return subprocess.call(
            [sys.executable, "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider", *sys.argv[1:]],
            cwd=ROOT, env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
