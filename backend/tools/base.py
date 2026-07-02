from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    tool: str
    success: bool
    content: str


class Tool(ABC):
    name: str
    description: str

    def configure(self, config: dict) -> None:
        """Optional manifest-driven configuration."""

    @abstractmethod
    async def run(self, query: str) -> ToolResult: ...
