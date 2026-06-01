"""LLM client (LiteLLM, provider-agnostic) with a deterministic fallback.

The agents call `chat(...)` for free-text reasoning and `chat_json(...)` for
structured output. If a provider key is present (GEMINI/GROQ/ANTHROPIC/OPENAI via
.env), calls go to a real model through LiteLLM. If no key is set, a deterministic
fallback returns sensible, clearly-labelled stub reasoning so the entire closed
loop still runs end-to-end — and switches to the real model the moment a key
appears in aeolus/.env.
"""
from __future__ import annotations

import json
import re

from aeolus import config as C

_MODE = "llm" if C.LLM_AVAILABLE else "fallback"


def mode() -> str:
    return _MODE


def chat(system: str, user: str, max_tokens: int = 800, temperature: float = 0.2,
         fallback: str | None = None) -> str:
    """Free-text completion. Returns model text, or the fallback string."""
    if not C.LLM_AVAILABLE:
        return fallback if fallback is not None else _generic_fallback(user)
    import litellm
    litellm.drop_params = True
    try:
        r = litellm.completion(
            model=C.LLM_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature)
        return r.choices[0].message.content or ""
    except Exception as e:                                    # never break the loop
        print(f"  [llm warn] {type(e).__name__}: {str(e)[:160]} -> using fallback")
        return fallback if fallback is not None else _generic_fallback(user)


def chat_json(system: str, user: str, fallback: dict, max_tokens: int = 900) -> dict:
    """Structured completion. Returns a dict (parsed JSON) or the fallback dict."""
    if not C.LLM_AVAILABLE:
        return fallback
    sys2 = system + "\n\nRespond with ONLY a single valid JSON object, no prose, no markdown fences."
    text = chat(sys2, user, max_tokens=max_tokens, temperature=0.1, fallback="")
    parsed = _extract_json(text)
    return parsed if parsed is not None else fallback


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _generic_fallback(user: str) -> str:
    return ("[deterministic fallback — no LLM key configured] "
            "Reasoning grounded in the provided SCADA residuals, prognosis and "
            "retrieved O&M references; see structured fields for specifics.")
