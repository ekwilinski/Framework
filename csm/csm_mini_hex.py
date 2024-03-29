import time

from easy_drone import AbstractDrone
from RealSense import RealSense


# Concrete implemention of DroneInterface using HexSoon edu 450
class CSM_Mini_Hexsoon(AbstractDrone):
    def __init__(self, min_follow_dist=5.0, time_slice=0.05) -> None:
        print("creating camera...")
        self.cam = RealSense()
        self.cam.start()
        self.frame = None

        print("running Drone.__init__ ...")
        super().__init__(address="serial:///dev/ttyACM0",time_slice=time_slice, min_follow_distance=min_follow_dist)

        print("done init")

        self.put(self._drone.param.set_param_int, "COM_ARM_WO_GPS", 1)

    def setup(self):
        self.frame, depth_image, color_frame, depth_frame = self.cam.data.value

    def loop(self):
        self.frame, depth_image, color_frame, depth_frame = self.cam.data.value

    def teardown(self):
        try:
            self.cam.stop()
        except RuntimeError:
            pass
