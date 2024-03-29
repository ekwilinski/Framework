from threading import Thread
from time import sleep, perf_counter
from collections import deque
import random
import asyncio
import atexit
from math import atan2, degrees, sqrt, pow, cos, sin, radians
from abc import abstractmethod, ABC
from typing import Union, Any, List, Tuple, Callable, Dict, Optional
import logging
import sys
import inspect

from mavsdk import System
from mavsdk.offboard import PositionNedYaw, VelocityBodyYawspeed, Attitude, OffboardError
from mavsdk.action import ActionError, OrbitYawBehavior
import mavsdk.telemetry as telemetry

from .sensors import Sensor, SensorData, SensorManager
from .plugins import *


class AbstractDrone(ABC):
    def __init__(self, address: str, sensor_list: Optional[List[Sensor]] = None, 
                 log_file_name: Optional[str] = None, time_slice=0.050, min_follow_distance=5.0):
        """
        :param address: Connection address for use with mavsdk.System.connect method
        :param time_slice: The interval to process commands in the queue
        :param min_follow_distance: The minimum distance a point must be from the drone, for a movement to take place
        in the maneuver_to method
        """
        # setup the logger first
        logger_name = "mavlog.log" if log_file_name is None else log_file_name
        self._logger = self._setup_logger(logger_name)

        # set up the instance fields
        self._stopped_mavlink = False
        self._stopped_loop = False
        self._time_slice = time_slice
        self._min_follow_distance = min_follow_distance
        self._address = address

        # tracker variables for state
        self._offboard_started = False

        # setup resources for drone control, mavsdk.System, deque, thread, etc..
        self._drone = System(port=random.randint(1000, 65535))  # cursed garbage
        self._queue = deque()
        self._loop = asyncio.get_event_loop()
        self._mavlink_thread = Thread(name="Mavlink-Command-Thread", target=self._process_command_loop)

        # make stuff for telemetry
        self._telemetry_thread = Thread(name="Mavlink-Telemetry-Thread", target=self._run_telemetry_loop)

        # register the stop method so everything cleans up
        atexit.register(self.stop)

        # connect the drone
        self._connect()

        # setup all plugins
        self._core = Core(self._drone, self._loop, self._logger)
        self._telemetry = Telemetry(self._drone, self._loop, self._logger)
        self._geofence = Geofence(self._drone, self._loop, self._logger)
        self._param = Param(self._drone, self._loop, self._logger)
        self._offboard = Offboard(self._drone, self._loop, self._logger)
        self._calibration = Calibration(self._drone, self._loop, self._logger)
        self._info = Info(self._drone, self._loop, self._logger)
        self._transponder = Transponder(self._drone, self._loop, self._logger)
        self._follow_me = FollowMe(self._drone, self._loop, self._logger)

        # setup the sensors
        self._sensor_manager = SensorManager(sensor_list)

        # after connection run setup, then initialize loop, run teardown during cleanup phase
        self._calibration.calibrate_all()  # run calibratiohn tasks before/during setup
        self.setup()
        self._loop_thread = Thread(name="Loop-Thread", target=self._loop_loop)

        # finally, start the mavlink thread
        self._mavlink_thread.start()
        self._telemetry_thread.start()
        self._sensor_manager.start_all_sensors()

    # setup the logger
    def _setup_logger(self, log_file_name: str) -> logging.Logger:
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(log_file_name)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(stdout_handler)

        return logger

    def _close_logger(self) -> None:
        handlers = self._logger.handlers[:]
        for handler in handlers:
            self._logger.removeHandler(handler)
            handler.close()

    # PLUGIN PROPERTIES
    @property
    def core(self) -> Core:
        """
        :return: The Core plugin class instance
        """
        return self._core

    @property
    def telemetry(self) -> Telemetry:
        """
        :return: The Telemetry plugin class instance
        """
        return self._telemetry

    @property
    def geofence(self) -> Geofence:
        """
        :return: The Geofence plugin class instance
        """
        return self._geofence

    @property
    def param(self) -> Param:
        """
        :return: The Param plugin class instance
        """
        return self._param

    @property
    def offboard(self) -> Offboard:
        """
        :return: The Offboard plugin class instance
        """
        return self._offboard

    @property
    def calibration(self) -> Calibration:
        """
        :return: The Calibration plugin class instance
        """
        return self._calibration

    @property
    def info(self) -> Info:
        """
        :return: The Info plugin class instance
        """
        return self._info

    @property
    def transponder(self) -> Transponder:
        """
        :return: The Transponder plugin class instance
        """
        return self._transponder

    @property
    def follow_me(self) -> FollowMe:
        """
        :return: The FollowMe plugin class instance
        """
        return self._follow_me

    @property
    def sensors(self) -> SensorManager:
        return self._sensor_manager

    # typical properties
    @property
    def logger(self) -> logging.Logger:
        """
        :return: The logger instance setup in the __init__ method of AbstractDrone
        """
        return self._logger

    @property
    def address(self) -> str:
        """
        :return: The address used to connect in mavsdk.System.connect
        """
        return self._address

    @property
    def time_slice(self) -> float:
        """
        :return: The time slice the drone is currently using
        """
        return self._time_slice

    @time_slice.setter
    def time_slice(self, val: float):
        """
        :param val: A new time slice for the drone to use
        """
        self._time_slice = val

    @property
    def min_follow_distance(self) -> float:
        """
        :return: The minimum following distance that is currently being used
        """
        return self._min_follow_distance

    @min_follow_distance.setter
    def min_follow_distance(self, dist: float):
        """
        :param dist: The new minimum distance that the drone should use in the maneuver_to method
        """
        self._min_follow_distance = dist

    # AREA TO OVERRIDE
    # abstract methods which over classes must override
    @abstractmethod
    def setup(self) -> None:
        """
        A function which takes no parameters and does not have any return value. This is implemented in the concrete
        implementations of the AbstractDrone class. This method's responsibility is to handle any one-time operations
        that need to occur. These operations could occur in the __init__, but the setup runs after a connection has
        been established to the flight controller, so methods such as start_offboard or even arm could occur here.
        Should not be called itself.
        """
        pass

    @abstractmethod
    def loop(self) -> None:
        """
        A function which takes no parameters and does not have any return value. This method is run continously once
        a call to start_loop occurs. This could handle the sending of certain sensor data to a control algorithm or
        simply print some info every so often.
        Should not be called itself.
        """
        pass

    def _loop_loop(self) -> None:
        while not self._stopped_loop:
            self.loop()

    def start_loop(self) -> None:
        """
        Begins the execution of the loop method. Starts the internal thread.
        """
        self._loop_thread.start()

    @abstractmethod
    def teardown(self) -> None:
        """
        A function which takes no parameters and does not have any return value. This method runs just before the
        mavlink thread is stopped and joined. As such it has access to calling methods such as stop_offboard and land.
        Should not be called itself.
        """
        pass

    ###############################################################################
    # internal methods for drone control, connection, threading of actions, etc..
    ###############################################################################
    def _connect(self) -> None:
        try:
            self._loop.run_until_complete(self._drone.connect(system_address=self.address))
        except KeyboardInterrupt:
            self._cleanup()
            raise KeyboardInterrupt
        finally:
            self._loop.run_until_complete(self._async_connect())

    async def _async_connect(self):
        async for state in self._drone.core.connection_state():
            if state.is_connected:
                self._logger.info("Drone connection established")
                break

    def _cleanup(self) -> None:
        self._drone.__del__()
        del self._drone

    def _process_command(self, com: Callable, args: List, kwargs: Dict) -> None:
        if com is not None:
            self._logger.info(f"Processing: {com.__module__}.{com.__qualname__} with args: {args} and kwargs: {kwargs}")
            if asyncio.iscoroutinefunction(com):  # if it is an async function
                _ = asyncio.ensure_future(com(*args, **kwargs), loop=self._loop)
            else:  # typical sync function
                _ = com(*args, **kwargs)
        else:
            pass

    # loop for processing mavlink commands. Uses the time slice determined in the contructor for its maximum rate. 
    def _process_command_loop(self) -> None:
        try:
            while not self._stopped_mavlink:
                start_time = perf_counter()
                try:
                    com, args, kwargs = self._queue.popleft()
                    if args is None:
                        args = []
                    if kwargs is None:
                        kwargs = {}
                    self._process_command(com, args, kwargs)
                # TODO, perform logging on these exceptions
                except IndexError as e:
                    # this exception is expected since we expect the deque to not have elements sometimes
                    if str(e) != "pop from an empty deque":
                        # if the exception makes it here, it is unexpected
                        print(e)
                except ActionError as e:
                    print(e)
                except OffboardError as e:
                    print(e)
                finally:
                    end_time = perf_counter() - start_time
                    if end_time < self._time_slice:
                        sleep(self._time_slice - end_time)
        finally:
            self._cleanup()

    # method for running telemetry data
    def _run_telemetry_loop(self):
        self._loop.run_forever()

    # method to stop the thread for processing mavlink commands
    def stop(self) -> None:
        """
        Clears the command queue, attempts to disarm the drone, closes all telemetry readings, stops the loop method
        execution, stops the mavlink command loop, and then joins the mavlink thread.
        :return: None
        """
        # on a stop call put a disarm call in the empty queue
        self._queue.clear()

        try:
            self.disarm()
        except AttributeError:  # means that _cleanup has already occurred
            pass

        # shutdown the any asyncgens that have been opened
        self._loop.stop()

        # stop execution of the loop
        self._stopped_loop = True
        try:
            self._loop_thread.join()  # join the loop thread first since it most likely generates mavlink commands
        except RuntimeError:  # occurs if the loop_thread was never started with self.start_loop()
            pass

        # run teardown (queue should be clean from the clear before disarm)
        self.teardown()
        while len(self._queue) > 0:  # simple spin wait to ensure any mavlink commands from teardown are run
            sleep(self._time_slice + 0.01)
        
        # finally join the mavlink thread and stop it
        self._stopped_mavlink = True
        self._mavlink_thread.join()

        # close logging
        self._close_logger()

    # method for queueing mavlink commands
    # TODO, implement a clear queue or priority flag. using deque allows these operations to be deterministic
    def put(self, obj: Callable, *args: Any, **kwargs: Any) -> None:
        """
        Used to put functions/methods in a queue for execution in a separate thread asynchronously or otherwise
        :param obj: A callable function/method which will get executed in the mavlink command loop thread
        :param args: The arguments for the function/method
        :param kwargs: The keyword arguments for the function/method
        :return: None
        """
        self._logger.info(f"User called: {obj.__module__}.{obj.__qualname__}, putting call in queue")
        self._queue.append((obj, args, kwargs))

    def get_data_async(self, obj: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Used to acquire a return value that is generated through a coroutine.
        Will wait for the coroutine to finish before returning the result.
        :param obj: A callable function/method which will get executed in the event loop
        :param args: The arguments for the function/method
        :param kwargs: The keyword arguments for the function/method
        :return: Any, the return value of the obj param
        """
        task = asyncio.ensure_future(obj(*args, **kwargs), loop=self._loop)
        while not task.done():
            sleep(0.0001)
        return task.result()

    ##################################################
    # methods which implement the mavsdk System actions
    ##################################################
    # TODO, implement the flag for put in these methods
    def arm(self) -> None:
        """
        Arms the drone.
        :return: None
        """
        self.put(self._drone.action.arm)

    def disarm(self) -> None:
        """
        Disarms the drone.
        :return: None
        """
        self.put(self._drone.action.disarm)

    def do_orbit(self, *args: Union[float, OrbitYawBehavior], **kwargs: Union[float, OrbitYawBehavior]) -> None:
        """
        Performs an orbit in midair
        :param radius_m: Radius of circle (in meters)
        :param velocity_ms: Tangential velocity (in m/s)
        :param yaw_behavior: An OrbitYawBehavior
        :param latitude_deg: Optional: Center point in latitude in degrees, uses current point as default
        :param longitude_deg: Optional: Center point in longitude in degrees, uses current point as default
        :param absolute_altitude_m: Optional: Center point altitude in meters, uses current point as default
        :return: None
        """
        self.put(self._drone.action.do_orbit, *args, **kwargs)

    def get_maximum_speed(self) -> float:
        """
        Get the vehicle maximum speed (in metres/second).
        :return: Maximum speed (in metres/second)
        """
        return self.get_data_async(self._drone.action.get_maximum_speed)

    def get_return_to_launch_altitude(self) -> float:
        """
        Get the return to launch minimum return altitude (in meters).
        :return: Return altitude relative to takeoff location (in meters)
        """
        return self.get_data_async(self._drone.action.get_return_to_launch_altitude)

    def get_takeoff_altitude(self) -> float:
        """
        Get the takeoff altitude (in meters above ground).
        :return: Takeoff altitude relative to ground/takeoff location (in meters)
        """
        return self.get_data_async(self._drone.action.get_takeoff_altitude)

    def goto_location(self, *args: float, **kwargs: float) -> None:
        """
        Send command to move the vehicle to a specific global position.
        The latitude and longitude are given in degrees (WGS84 frame) and the altitude in meters AMSL (above mean sea
        level).
        The yaw angle is in degrees (frame is NED, 0 is North, positive is clockwise).
        :param latitude_deg: Latitude (in degrees)
        :param longitude_deg: Longitude (in degrees)
        :param absolute_altitude_m: Altitude AMSL (in meters)
        :param yaw_deg: Yaw angle in degrees (0 is North, positive is clockwise)
        :return: None
        """
        self.put(self._drone.action.goto_location, *args, **kwargs)

    def hold(self) -> None:
        """
        Send command to hold current position
        Note: this command is specific to the PX4 Autopilot flight stack as it implies a change to a PX4-specific mode.
        :return: None
        """
        self.put(self._drone.action.hold)

    def kill(self) -> None:
        """
        Send command to kill the drone.
        :return: None
        """
        self.put(self._drone.action.kill)

    def land(self) -> None:
        """
        Send command to land the drone
        :return: None
        """
        self.put(self._drone.action.land)

    def reboot(self) -> None:
        """
        Send command to reboot drone components
        :return: None
        """
        self.put(self._drone.action.reboot)

    def return_to_launch(self) -> None:
        """
        Send command to return to launch (takeoff) position and land.
        :return: None
        """
        self.put(self._drone.action.return_to_launch)

    def set_actuator(self, *args: Union[int, float], **kwargs: Union[int, float]) -> None:
        """
        Uses a value to set an acuator
        :param index: Index of actuator (starting at 1)
        :param value: Value to set the acuator to (normalized from [-1..1])
        :return: None
        """
        self.put(self._drone.action.set_actuator, *args, **kwargs)

    def set_current_speed(self, *args: float, **kwargs: float) -> None:
        """
        Set current speed
        :param speed_m_s: Speed in m/s
        :return: None
        """
        self.put(self._drone.action.set_current_speed, *args, **kwargs)

    def set_maximum_speed(self, *args: float, **kwargs: float) -> None:
        """
        Set vehicle maximum speed (in metres/second).
        :param speed: Maximum speed in m/s
        :return:None
        """
        self.put(self._drone.action.set_maximum_speed, *args, **kwargs)

    def set_return_to_launch_altitude(self, *args: float, **kwargs: float) -> None:
        """
        Set the return to launch minimum return altitude (in meters).
        :param relative_altitude_m: Altitude relative to takeoff location
        :return: None
        """
        self.put(self._drone.action.set_return_to_launch_altitude, *args, **kwargs)

    def set_takeoff_altitude(self, *args: float, **kwargs: float) -> None:
        """
        Set takeoff altitude (in meters above ground).
        :param altitude: Takeoff altitude relative to ground/takeoff location
        :return: None
        """
        self.put(self._drone.action.set_takeoff_altitude, *args, **kwargs)

    def shutdown(self) -> None:
        """
        Send command to shut down the drone components.
        :return: None
        """
        self.put(self._drone.action.shutdown)

    def takeoff(self) -> None:
        """
        Send command to take off and hover.
        :return: None
        """
        self.put(self._drone.action.takeoff)

    def terminate(self) -> None:
        """
        Send command to terminate the drone.
        :return: None
        """
        self.put(self._drone.action.terminate)

    def transition_to_fixedwing(self) -> None:
        """
        Send command to transition the drone to fixedwing.
        :return: None
        """
        self.put(self._drone.action.transition_to_fixedwing)

    def transition_to_multicopter(self) -> None:
        """
        Send command to transition the drone to multicopter.
        :return: None
        """
        self.put(self._drone.action.transition_to_multicopter)

    #########################################################
    # methods for maneuvering
    #########################################################
    def maneuver_to(self, front: float, right: float, down: float, on_dimensions: Tuple = (True, True, True), test_min: bool = False):
        """
        A movement command for moving relative to the drones current position. The front direction is aligned directly with 
        the drones front as defined in the configuration.
        :param front: Relative distance in front of drone
        :param right: Relative distance to the right of drone
        :param down: Relative distance below the drone
        :param on_dimensions: A tuple of 3 boolean values. In order they represent if the drone will move
        (front, right, down). If set to False the drone will not move in that direction
        """
        self.put(self._maneuver_to, front, right, down, on_dimensions, test_min)

    async def _maneuver_to(self, front: float, right: float, down: float, on_dimensions=(True, True, True), test_min=False) -> None:
        if test_min:
            totalDistance = sqrt(pow(front, 2) + pow(right, 2) + pow(down, 2))
            if totalDistance < self._min_follow_distance:
                return await self._drone.offboard.set_velocity_body(VelocityBodyYawspeed(0, 0, 0, 0))
        return await self._maneuver_with_ned(front, right, down, on_dimensions)

    async def _maneuver_with_ned(self, front: float, right: float, down: float, on_dimensions: Tuple = (True, True, True)) -> None:
        # zero out dimensions that will not be moved
        front = 0.0 if not on_dimensions[0] else -1 * front
        right = 0.0 if not on_dimensions[1] else -1 * right
        down = 0.0 if not on_dimensions[2] else down

        # get current position
        task = self.telemetry.position_velocity_ned
        current_pos = task.position

        # get angle of rotation
        task2 = self.telemetry.attitude_euler
        angle = task2.yaw_deg
        angle_of_rotation = radians(angle)

        # convert FRD to NED 
        relative_north = right * sin(angle_of_rotation) + front * cos(angle_of_rotation)
        relative_east = right * cos(angle_of_rotation) - front * sin(angle_of_rotation)

        # get angle of yaw
        yaw = degrees(atan2(relative_east, relative_north))

        # add offset to curent position
        north = relative_north + current_pos.north_m
        east = relative_east + current_pos.east_m
        down = down + current_pos.down_m

        new_pos = PositionNedYaw(north, east, down, yaw)
        await self._drone.offboard.set_position_ned(new_pos)

    ####################
    # method for creating a relative geofence
    ######################
    def create_geofence(self, distance: float) -> None:
        """
        Creates a relative inclusive geofence around the drones home coordinates. The geofence is defined as a square
        where the distance parameter is equal to half the side length.
        :param distance: The meters from home the drone can maneuver
        :return: None
        """
        self.put(self._create_geofence, distance)

    async def _create_geofence(self, distance: float) -> None:
        latitude = self.telemetry.home.latitude_deg
        longitude = self.telemetry.home.longitude_deg

        # source for magic number
        # https://gis.stackexchange.com/questions/2951/algorithm-for-offsetting-a-latitude-longitude-by-some-amount-of
        # -meters
        offset = distance * (1 / 111111)

        # Define your geofence boundary
        p1 = Point(latitude - offset, longitude - offset)
        p2 = Point(latitude + offset, longitude - offset)
        p3 = Point(latitude + offset, longitude + offset)
        p4 = Point(latitude - offset, longitude + offset)

        # Create a polygon object using your points
        polygon = Polygon([p1, p2, p3, p4], Polygon.FenceType.INCLUSION)

        await self._drone.geofence.upload_geofence([polygon])
