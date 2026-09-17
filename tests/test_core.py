from openapi_agent.core.errors import BusinessException, ErrorCode
from openapi_agent.core.task import Task, TaskStatus
from openapi_agent.core.task_manager import TaskManager, new_task_id


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
    assert t.progress == 0
    assert t.input_materials == {}
    assert t.result is None
    assert t.error_info is None


def test_new_task_id_format():
    task_id = new_task_id()
    assert task_id.startswith("task-")
    assert len(task_id) == len("task-") + 8 + 1 + 4 + 1 + 4 + 1 + 16


def test_task_manager_lifecycle():
    tm = TaskManager()
    task = tm.create_task("task-0001", {"files": ["a.md"]})
    assert tm.get_task(task.task_id) is task
    assert task.status == TaskStatus.PENDING

    tm.cancel_task(task.task_id)
    assert tm.get_task(task.task_id).status == TaskStatus.CANCELLED

    assert tm.get_task("missing") is None

    # 设计文档 2.2.2：task_id 不存在或不可取消时抛 BusinessException(10002)
    try:
        tm.cancel_task("missing")
        raise AssertionError("应当抛出 BusinessException")
    except BusinessException as e:
        assert int(e.code) == 10002

    try:
        tm.cancel_task(task.task_id)
        raise AssertionError("终态任务应当抛出 BusinessException")
    except BusinessException as e:
        assert int(e.code) == 10002
