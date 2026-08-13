from abc import ABC, abstractmethod


class LLMPort(ABC):
    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return one completion for the given chat messages."""
