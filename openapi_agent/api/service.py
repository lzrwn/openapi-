"""接入层的素材暂存与运行中任务句柄。

生成任务的执行逻辑位于 ``core/agent_workflow.py``（run_task / run_with_timeout），
本模块只保留 HTTP 层需要的东西。

素材落盘策略（为什么不是简单的 mkdtemp）：
1. 首选 `tempfile.mkdtemp()` 建独立任务目录；
2. 若目标文件系统不允许写入「运行时新建的目录」（部分容器 / 沙箱 / 只读卷会这样），
   退回到在**已存在**的临时根目录里写入带唯一前缀的文件，任务结束后逐个清理。
无论哪种方式，素材都只临时落盘，任务结束立刻删除。
"""

import logging
import os
import tempfile
import uuid
from pathlib import Path

from openapi_agent.config import settings
from openapi_agent.core.errors import BusinessException, ErrorCode

logger = logging.getLogger(__name__)

_running: dict[str, object] = {}


def _temp_root() -> Path:
    if settings.temp_root:
        root = Path(settings.temp_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("OPENAPI_AGENT_TEMP_ROOT 不可写，退回系统临时目录: %s", settings.temp_root)
            root = Path(tempfile.gettempdir())
        return root
    return Path(tempfile.gettempdir())


class TempMaterials:
    """一次任务的素材暂存区：提供写入目标路径，并负责整体清理。"""

    def __init__(self) -> None:
        self.root = _temp_root()
        self.files: list[str] = []
        self._dir: str | None = None
        self._prefix: str | None = None

    def allocate(self, filename: str, used: set[str]) -> str:
        """为一个上传文件分配落盘路径（同名文件加序号，互不覆盖）。"""
        from openapi_agent.api.validators import unique_dest

        if self._dir is None and self._prefix is None:
            self._try_make_dir()
        base = Path(self._dir) if self._dir is not None else self.root
        return unique_dest(str(base), filename, used, prefix=self._prefix)

    def _try_make_dir(self) -> None:
        try:
            self._dir = tempfile.mkdtemp(prefix="openapi-agent-", dir=str(self.root))
        except OSError as e:
            logger.warning("临时目录不可用(%s)，改为在 %s 下写入带前缀的临时文件", e, self.root)
            self._dir = None
            self._prefix = f".openapi-agent-{uuid.uuid4().hex[:12]}-"

    def _use_flat_mode(self) -> None:
        """切换到「已存在目录 + 唯一文件名前缀」模式。"""
        self.cleanup()
        self._dir = None
        self._prefix = f".openapi-agent-{uuid.uuid4().hex[:12]}-"
        logger.info("改为在 %s 下写入带前缀的临时文件", self.root)

    def write(self, filename: str, content: bytes, used: set[str]) -> str:
        dest = Path(self.allocate(filename, used))
        try:
            dest.write_bytes(content)
        except OSError:
            if self._prefix is not None:
                raise
            # 目标文件系统不允许写入「运行时新建的目录」→ 退回扁平模式重试一次
            self._use_flat_mode()
            used.discard(dest.name)
            dest = Path(self.allocate(filename, used))
            try:
                dest.write_bytes(content)
            except OSError as e:
                raise BusinessException(
                    ErrorCode.MATERIAL_ERROR,
                    "素材写入失败",
                    f"{filename}: {e}；请检查 OPENAPI_AGENT_TEMP_ROOT 是否可写",
                ) from e
        self.files.append(str(dest))
        return str(dest)

    def cleanup(self) -> None:
        if self._dir is not None:
            import shutil

            try:
                shutil.rmtree(self._dir, ignore_errors=False)
            except OSError as e:
                # 不静默：清理失败说明临时目录可能泄漏，需要运维关注
                logger.warning("临时目录清理失败: %s (%s)", self._dir, e)
        leftover: list[str] = []
        for path in self.files:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                leftover.append(f"{path} ({e})")
        if leftover:
            logger.warning("临时素材清理失败: %s", leftover)
        self.files.clear()


def register_running(task_id: str, handle) -> None:
    _running[task_id] = handle


def cancel_running(task_id: str) -> None:
    handle = _running.get(task_id)
    if handle is not None:
        handle.cancel()


def forget_running(task_id: str) -> None:
    _running.pop(task_id, None)


def running_count() -> int:
    return len(_running)


__all__ = [
    "TempMaterials",
    "register_running",
    "cancel_running",
    "forget_running",
    "running_count",
]
