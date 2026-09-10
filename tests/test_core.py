from app.core.errors import BusinessException, ErrorCode
from app.core.task import Task, TaskStatus
from app.core.task_manager import TaskManager


def test_business_exception_format():
    e = BusinessException(ErrorCode.INPUT_ERROR, "输入参数错误")
    assert e.code == 10001
    assert "输入参数错误" in str(e)

    e2 = BusinessException(10004, "大模型服务调用失败或超时", "timeout after 60s")
    assert e2.detail == "timeout after 60s"
    assert "timeout after 60s" in str(e2)


def test_task_defaults():
    t = Task(task_id="t1")
    assert t.status == TaskStatus.PENDING
    assert t.input_materials == []
    assert t.result is None
    assert t.error_info is None


def test_task_manager_lifecycle():
    tm = TaskManager()
    task = tm.create_task(["a.md", "b.zip"])
    assert tm.get_task(task.task_id) is task
    assert task.status == TaskStatus.PENDING

    tm.cancel_task(task.task_id)
    assert tm.get_task(task.task_id).status == TaskStatus.CANCELLED

    assert tm.get_task("missing") is None
    tm.cancel_task("missing")
