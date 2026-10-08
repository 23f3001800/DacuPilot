

"""Prompt injection detection and security guardrails for DocuPilot.

Provides input inspection, delimiter escaping, and defensive validation
to protect language models from jailbreaks, instruction overrides,
and prompt extraction attacks.
"""

import re
from typing import Tuple

# Common prompt injection, jailbreak, and instruction override signatures
_INJECTION_PATTERNS = [
    # Direct instruction overrides
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions|rules|guidelines)\b", re.IGNORECASE),
    re.compile(r"\bforget\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts|rules)\b", re.IGNORECASE),
    re.compile(r"\boverride\s+(?:system|safety|security)\s+(?:instructions|protocols|rules)\b", re.IGNORECASE),
    re.compile(r"\b(?:system|admin|root|developer)\s+override\b", re.IGNORECASE),

    # Role-play jailbreaks & unconstrained persona adoption
    re.compile(r"\byou\s+are\s+now\s+(?:in\s+)?(?:developer\s+mode|dan|jailbroken|unfiltered|unrestricted)\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(?:an?\s+)?(?:unfiltered|unrestricted|jailbroken|evil)\s+(?:ai|assistant|model)\b", re.IGNORECASE),
    re.compile(r"\bpretend\s+(?:you\s+have\s+no\s+(?:rules|restrictions|filters|limits)|you\s+are\s+dan)\b", re.IGNORECASE),

    # Prompt extraction & leakage attacks
    re.compile(r"\b(?:print|repeat|output|show|reveal|display)\s+(?:the\s+)?(?:(?:entire|whole|initial|full|system|hidden)\s+)*(?:prompt|prompts|instructions)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:are|were)\s+your\s+(?:(?:exact|initial|full|system|hidden)\s+)*(?:instructions|prompts)\b", re.IGNORECASE),
    re.compile(r"\boutput\s+everything\s+above\s+(?:this\s+line|here)\b", re.IGNORECASE),

    # Delimiter breakout attempts
    re.compile(r"</?(?:system|retrieved_evidence|instructions|context|untrusted_data)>", re.IGNORECASE),
]

# Sensitive tag patterns to sanitize
_DELIMITER_TAGS = re.compile(
    r"</?(?:system|retrieved_evidence|instructions|context|untrusted_data|prompt|admin)>",
    re.IGNORECASE,
)


def detect_prompt_injection(text: str) -> Tuple[bool, str | None]:
    """Inspect text for prompt injection, jailbreak, or system override signatures.

    Returns:
        (True, reason) if an injection attack is detected.
        (False, None) if the text passes inspection.
    """
    if not text or not isinstance(text, str):
        return False, None

    normalized = text.strip()
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return True, f"Blocked potential prompt injection pattern: '{match.group(0)}'"

    return False, None


def sanitize_user_input(text: str) -> str:
    """Sanitize user input by neutralising spoofed structural XML/prompt delimiters."""
    if not text or not isinstance(text, str):
        return ""
    # Strip or replace delimiters that mimic system message boundaries
    return _DELIMITER_TAGS.sub("", text)


def sanitize_evidence_text(text: str) -> str:
    """Sanitize retrieved evidence or OCR text to prevent indirect prompt injection."""
    if not text or not isinstance(text, str):
        return ""
    # Strip system tags and disarm instructions mimicking commands
    sanitized = _DELIMITER_TAGS.sub("", text)
    return sanitized
