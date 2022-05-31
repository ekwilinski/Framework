from Interfaces.DroneInterface import DroneInterface as di

# Concrete implemention of DroneInterface using HexSoon edu 450

BAUDRATE = "9600" # TODO: verify baudrate
ADDRESS = "serial://" + ID + ":" + BAUDRATE

class HexSoon(di):

    def __init__(self) -> None:
        super().__init__()
        self._serialConnection = UARTBridge()
        self._serialConnection.initializeBridge()

    # connect hexsoon to uart, and if successful,
    # connect mavsdk to flight controller
    async def connect(self):
        try:
            await self._drone.connect(ADDRESS)
        except:
            print("unable to connect mavsdk")
        
if __name__ == "__main__":
    locations = [  ]

    drone = HexSoon()

    drone.connect()
    drone.arm()
    drone.configureTracker()
    drone.startTracker()
    
    for location in locations:
        drone.updateTracker(location)

    drone.stopTracker()
    drone.land()

