from types import SimpleNamespace

from app.services.gemini import GeminiSupportService
from app.services.tracing import redact_sensitive_text


def test_redact_sensitive_text() -> None:
    text = "demo@example.com 010-1234-5678 4111 1111 1111 1111"
    assert redact_sensitive_text(text) == ("[REDACTED EMAIL] [REDACTED PHONE] [REDACTED CARD]")


def test_gemini_usage_is_mapped_to_exclusive_langfuse_buckets() -> None:
    usage = SimpleNamespace(
        total_cached_tokens=20,
        total_input_tokens=100,
        total_output_tokens=30,
        total_thought_tokens=10,
        total_tool_use_tokens=5,
        total_tokens=145,
    )

    assert GeminiSupportService._usage_details(usage) == {
        "input": 80,
        "input_cached_tokens": 20,
        "output": 30,
        "output_reasoning_tokens": 10,
        "input_tool_use_tokens": 5,
        "total": 145,
    }
