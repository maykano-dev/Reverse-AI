"""ReverseAI agent — autonomous investigation loop with policy-mediated tools."""

from .builtins import default_tools
from .evidence import Confidence, EvidenceLog, Finding
from .job import Job
from .mediator import ToolMediator
from .memory import MemoryStore
from .orchestrator import Agent
from .providers import LLMProvider, MockProvider, get_provider
from .registry import ToolRegistry
from .templates import AgentTemplate, all_templates, get_template
from .tools import Permission, Tool, ToolContext, ToolResult

__all__ = [
    "Agent",
    "Job",
    "ToolRegistry",
    "ToolMediator",
    "Tool",
    "ToolContext",
    "ToolResult",
    "Permission",
    "Confidence",
    "EvidenceLog",
    "Finding",
    "MemoryStore",
    "AgentTemplate",
    "all_templates",
    "get_template",
    "default_tools",
    "LLMProvider",
    "MockProvider",
    "get_provider",
]
