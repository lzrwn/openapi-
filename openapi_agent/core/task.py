from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    CHUNKING = "chunking"
    EXTRACTING = "extracting"
    MERGING = "merging"
    ASSEMBLING = "assembling"
    VALIDATING = "validating"
    DIFFING = "diffing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    input_materials: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_info: dict[str, Any] | None = None
