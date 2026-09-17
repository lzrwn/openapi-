import uuid

from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.task import Task, TaskStatus


def new_task_id() -> str:
    """生成形如 task-8a2f-4412-b71e-abc123456789 的任务 id（设计文档 2.1.1）。"""
    raw = uuid.uuid4().hex
    return f"task-{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:32]}"


class TaskManager:
    """任务管理器：负责任务创建、查询、取消，内存存储任务（设计文档 2.2.2）。"""

    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def create_task(self, task_id: str, input_materials: dict) -> Task:
        task = Task(task_id=task_id, input_materials=input_materials)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> None:
        """取消执行中的任务；task_id 不存在或已处于终态时抛 BusinessException(10002)。"""
        task = self.get_task(task_id)
        if task is None:
            raise BusinessException(ErrorCode.TASK_NOT_FOUND, "task_id不存在", task_id)
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        if task.status in terminal:
            raise BusinessException(
                ErrorCode.TASK_NOT_FOUND, "任务已结束，不可取消", f"当前状态: {task.status.value}"
            )
        task.status = TaskStatus.CANCELLED
