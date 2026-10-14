"""Framework-free agent kernel for line-rca-agent.

Public surface is re-exported here so callers never reach into submodules.
"""

from line_rca_agent.contracts import (
    Completion,
    Executor,
    Goal,
    LLMProvider,
    Memory,
    MemoryItem,
    Message,
    Plan,
    Planner,
    Step,
    StepResult,
    Tool,
    ToolCall,
    ToolRegistry,
    ToolResult,
)
from line_rca_agent.kernel import AgentKernel
from line_rca_agent.trace import (
    SCHEMA_VERSION,
    EventType,
    FanOutTraceSink,
    InMemoryTraceSink,
    NullTraceSink,
    StdoutTraceSink,
    TraceEvent,
    TraceSink,
)

__all__ = [
    "SCHEMA_VERSION",
    "AgentKernel",
    "Completion",
    "EventType",
    "Executor",
    "FanOutTraceSink",
    "Goal",
    "InMemoryTraceSink",
    "LLMProvider",
    "Memory",
    "MemoryItem",
    "Message",
    "NullTraceSink",
    "Plan",
    "Planner",
    "StdoutTraceSink",
    "Step",
    "StepResult",
    "Tool",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "TraceEvent",
    "TraceSink",
]
