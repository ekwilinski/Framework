from abc import ABC
from asyncio import AbstractEventLoop, Task
from logging import Logger
from collections import deque
from functools import partial

from mavsdk import System


class AbstractPlugin(ABC):
    def __init__(self, system: System, loop: AbstractEventLoop, logger: Logger) -> None:
        self._system = system
        self._loop = loop
        self._logger = logger

        self._task_cache = deque(maxlen=10)
        self._result_cache = deque(maxlen=10)

    def _task_callback(self, task: Task) -> None:
        self._logger.info(f"Task completed: {task.get_coro().__qualname__} ")
        self._result_cache.append(task.result())

    def submit_task(self, new_task: Task) -> Task:
        """
        Puts a task returned by asyncio.ensure_future to the task_cache to prevent garbage collection and allow return
        value analysis
        :param new_task: An asyncio.Task
        :return: The submitted task, if plugin specific callbacks are added
        """
        new_task.add_done_callback(partial(self._task_callback))
        self._task_cache.append(new_task)
        return new_task
