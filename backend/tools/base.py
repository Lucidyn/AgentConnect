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

    @abstractmethod
    async def run(self, query: str) -> ToolResult: ...
