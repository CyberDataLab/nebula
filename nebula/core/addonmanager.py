from typing import TYPE_CHECKING

from nebula.addons.functions import print_msg_box
from nebula.addons.gps.gpsmodule import factory_gpsmodule
from nebula.addons.mobility import Mobility
from nebula.addons.networksimulation.networksimulator import factory_network_simulator

if TYPE_CHECKING:
    from nebula.core.engine import Engine


class AddondManager:
    def __init__(self, engine: "Engine", config):
        self._engine = engine
        self._config = config
        self._addons = []

    async def deploy_additional_services(self):
        print_msg_box(msg="Deploying Additional Services", indent=2, title="Addons Manager")
        if self._config.participant["mobility_args"]["mobility"]:
            mobility = Mobility(self._config, verbose=False)
            self._addons.append(mobility)

            update_interval = 5
            gps = factory_gpsmodule("nebula", self._config, self._engine.addr, update_interval, verbose=False)
            self._addons.append(gps)

        if self._config.participant["network_args"]["simulation"]:
            refresh_conditions_interval = 5
            network_simulation = factory_network_simulator("nebula", refresh_conditions_interval, "eth0", verbose=False)
            self._addons.append(network_simulation)

        for add in self._addons:
            await add.start()
