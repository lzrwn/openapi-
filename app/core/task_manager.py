import uuid

from app.core.task import Task, TaskStatus


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def create_task(self, input_materials: list) -> Task:
        task_id = uuid.uuid4().hex
        task = Task(task_id=task_id, input_materials=input_materials)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        if task.status not in terminal:
            task.status = TaskStatus.CANCELLED
