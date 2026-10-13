"""Explicitly local, deterministic supervisor status responder.

No external inference providers are implemented in this repository.
"""
from .base import PHIGuard


class MockLLM:
    def __init__(self, system_name: str = "Puf Physically Unclonable Agent"):
        self.system_name = system_name

    def invoke(self, prompt: str) -> str:
        PHIGuard.assert_no_phi(prompt)
        return (
            f"[{self.system_name} mock responder] "
            "No model inference or independent verification was performed. "
            "Use the audit API for rule-based task evaluations."
        )


class LLMFactory:
    """Creates only the locally implemented mock responder."""

    @staticmethod
    def create(provider: str = "mock", system_name: str = "Puf Physically Unclonable Agent"):
        prov = str(provider).lower()
        if prov in ("mock", "deterministic", "test"):
            return MockLLM(system_name)
        raise ValueError(
            f"Unsupported provider {provider!r}: only the local mock responder is implemented"
        )
