import re

from langfuse.types import (
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanPatch,
)

EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:01[016789])[-. ]?\d{3,4}[-. ]?\d{4}\b")
CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact_sensitive_text(value: str) -> str:
    value = EMAIL_PATTERN.sub("[REDACTED EMAIL]", value)
    value = PHONE_PATTERN.sub("[REDACTED PHONE]", value)
    return CARD_PATTERN.sub("[REDACTED CARD]", value)


def mask_otel_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult | None:
    patches = {}
    for identifier, span in params.spans.items():
        replacements = {}
        for key, value in span.attributes.items():
            if not isinstance(value, str):
                continue
            masked = redact_sensitive_text(value)
            if masked != value:
                replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(
                set_attributes={**replacements, "masking.applied": True}
            )

    if not patches:
        return None
    return MaskOtelSpansResult(span_patches=patches)
