from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from backend.core.llm import LLMClient
from backend.core.message_bus import MessageBus
from backend.core.registry import AgentRegistry
from backend.core.shared_memory import SharedMemory
from backend.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from backend.core.task_store import TaskStore

OnTaskFinished = Callable[[str], Awaitable[None]]


@dataclass
class AgentServices:
    bus: MessageBus
    registry: AgentRegistry
    llm: LLMClient
    shared_memory: SharedMemory
    tools: ToolRegistry
    task_store: "TaskStore | None" = None
    on_task_finished: OnTaskFinished | None = None
    plugin_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
