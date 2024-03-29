import asyncio
from asyncio import AbstractEventLoop
from logging import Logger
from time import sleep
from typing import Callable
from functools import partial

from mavsdk import System, offboard

from ..abstract_plugin import AbstractPlugin


class Offboard(AbstractPlugin):
    def __init__(self, system: System, loop: AbstractEventLoop, logger: Logger) -> None:
        super().__init__(system, loop, logger)
        self._is_active = False

        self._is_active_task = asyncio.ensure_future(self._system.offboard.is_active(), loop=self._loop)
        self._is_active_task.add_done_callback(partial(self._is_active_callback))

    def _is_active_callback(self, task: Task) -> None:
        self._is_active = task.result()
        del self._is_active_task

    def is_active(self) -> bool:
        return self._is_active

    def set_acceleration_ned(self, accel_ned: offboard.AccelerationNed) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_acceleration_ned(accel_ned), loop=self._loop)
        )

    def set_acuator_control(self, act_ctrl: offboard.AcuatorControl) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_acuator_control(act_ctrl), loop=self._loop)
        )

    def set_attitude(self, attitude: offboard.Attitude) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_attitude(attitude), loop=self._loop)
        )

    def set_attitude_rate(self, attitude_rate: offboard.AttitudeRate) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_attitude_rate(attitude_rate), loop=self._loop)
        )

    def set_position_global(self, pos_global: offboard.PositionGlobalYaw) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_position_global(pos_global), loop=self._loop)
        )

    def set_position_ned(self, pos_ned: offboard.PositionNedYaw) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_position_ned(pos_ned), loop=self._loop)
        )

    def set_position_velocity_ned(self, pos: offboard.PositionNedYaw, vel: offboard.VelocityNedYaw) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_position_velocity_ned(pos, vel), loop=self._loop)
        )

    def set_velocity_body(self, vel_body: offboard.VelocityBodyYawSpeed) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_velocity_body(vel_body), loop=self._loop)
        )

    def set_velocity_ned(self, vel_ned: offboard.VelocityNedYaw) -> None:
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_velocity_ned(vel_ned), loop=self._loop)
        )

    def start(self) -> None:
        self._is_active = True
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, 0.0)), loop=self._loop)
        )
        self.hold()
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.start(), loop=self._loop)
        )

    def stop(self) -> None:
        self._is_active = False
        super().submit_task(
            asyncio.ensure_future(self._system.offboard.stop(), loop=self._loop)
        )

    def hold(self) -> None:
        self.set_velocity_body(VelocityBodyYawspeed(0, 0, 0, 0))
