from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable

from backend.core.llm import LLMClient
from backend.core.llm_usage import LLMUsageEntry
from backend.core.message_bus import MessageBus
from backend.core.registry import AgentRegistry
from backend.core.shared_memory import SharedMemory
from backend.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from backend.core.stream_buffer import StreamBuffer
    from backend.core.task_store import TaskStore
    from backend.core.worker_dispatcher import WorkerDispatcher
    from backend.core.worker_stream import WorkerStreamHub

OnTaskFinished = Callable[[str], Awaitable[None]]
RecordLLMUsage = Callable[[str, str, LLMUsageEntry], Awaitable[None]]


@dataclass
class AgentServices:
    bus: MessageBus
    registry: AgentRegistry
    llm: LLMClient
    shared_memory: SharedMemory
    tools: ToolRegistry
    task_store: "TaskStore | None" = None
    on_task_finished: OnTaskFinished | None = None
    record_llm_usage: RecordLLMUsage | None = None
    plugin_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    worker_hub: "WorkerStreamHub | None" = None
    worker_dispatcher: "WorkerDispatcher | None" = None
    stream_buffer: "StreamBuffer | None" = None
