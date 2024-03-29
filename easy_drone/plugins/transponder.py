import asyncio
from asyncio import AbstractEventLoop
from logging import Logger
from time import sleep
from typing import List, Dict, Any, Callable

from mavsdk import System, transponder

from ..abstract_plugin import AbstractPlugin


class Transponder(AbstractPlugin):
    def __init__(self, system: System, loop: AbstractEventLoop, logger: Logger) -> None:
        super().__init__(system, loop, logger)

        self._transponder_data = None
        self._transponder_task = asyncio.ensure_future(self._system.transponder.transponder(), loop=self._loop)

    def set_rate_transponder(self, rate: float) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.transponder.set_rate_transponder(rate), loop=self._loop)
        )

    async def _transponder_update(self) -> None:
        async for transponder in self._system.transponder.transponder():
            if transponder != self._transponder_data:
                self._transponder_data = transponder

    def transponder(self) -> transponder.AdsbVehicle:
        return self._transponder_data
