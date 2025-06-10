from typing import TYPE_CHECKING
from nebula.config.config import Config
from nebula.addons.functions import print_msg_box
from nebula.addons.gps.gpsmodule import factory_gpsmodule
from nebula.addons.mobility import Mobility
from nebula.addons.networksimulation.networksimulator import factory_network_simulator

if TYPE_CHECKING:
    from nebula.core.engine import Engine


class AddondManager:
    """
    Responsible for initializing and managing system add-ons.

    This class handles the lifecycle of optional services (add-ons) such as mobility simulation,
    GPS module, and network simulation. Add-ons are conditionally deployed based on the provided configuration.
    """
    
    def __init__(self, engine: "Engine", config: Config):
        """
        Initializes the AddondManager instance.

        Args:
            engine (Engine): Reference to the main engine instance of the system.
            config (dict): Configuration object containing participant settings for enabling add-ons.

        This constructor sets up the internal references to the engine and configuration, and
        initializes the list of add-ons to be managed.
        """
        self._engine = engine
        self._config = config
        self._addons = []

    async def deploy_additional_services(self):
        """
        Deploys and starts additional services based on the participant's configuration.

        This method checks the configuration to determine which optional components should be
        activated. It supports:
            - Mobility simulation (e.g., moving node behavior).
            - GPS module (e.g., geolocation updates).
            - Network simulation (e.g., changing connectivity conditions).

        All enabled add-ons are instantiated and started asynchronously.

        Notes:
            - Add-ons are stored in the internal list `_addons` for lifecycle management.
            - Services are only launched if the corresponding configuration flags are set.
        """
        print_msg_box(msg="Deploying Additional Services", indent=2, title="Addons Manager")
        if self._config.participant["trustworthiness"]:
            from nebula.addons.trustworthiness.trustworthiness import Trustworthiness
            
            trustworthiness = Trustworthiness(self._engine, self._config)
            self._addons.append(trustworthiness)
            
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
