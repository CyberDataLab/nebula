from abc import ABC, abstractmethod


class AddonEvent(ABC):
    """
    Abstract base class for all addon-related events in the system.
    """
    
    @abstractmethod
    async def get_event_data(self):
        """
        Retrieve the data associated with the event.

        Returns:
            Any: The event-specific data payload.
        """
        pass


class NodeEvent(ABC):
    """
    Abstract base class for all node-related events in the system.
    """
    
    @abstractmethod
    async def get_event_data(self):
        """
        Retrieve the data associated with the event.

        Returns:
            Any: The event-specific data payload.
        """
        pass

    @abstractmethod
    async def is_concurrent(self):
        """
        Indicates whether the event can be handled concurrently.

        Returns:
            bool: True if concurrent handling is allowed, False otherwise.
        """
        pass


class MessageEvent:
    """
    Event class for wrapping received messages in the system.

    Attributes:
        message_type (str): Type/category of the message.
        source (str): Address or identifier of the message sender.
        message (Any): The actual message payload.
    """
    
    def __init__(self, message_type, source, message):
        """
        Initializes a MessageEvent instance.

        Args:
            message_type (str): Type/category of the message.
            source (str): Address or identifier of the message sender.
            message (Any): The actual message payload.
        """
        self.source = source
        self.message_type = message_type
        self.message = message


"""                                                     ##############################
                                                        #         NODE EVENTS        #
                                                        ##############################
"""


class RoundStartEvent(NodeEvent):
    def __init__(self, round, start_time, expected_nodes):
        """Event triggered when round is going to start.

        Args:
            round (int): Round number.
            start_time (time): Current time when round is going to start.
        """
        self._round_start_time = start_time
        self._round = round
        self._expected_nodes = expected_nodes

    def __str__(self):
        return "Round starting"

    async def get_event_data(self):
        """Retrieves the round start event data.

        Returns:
            tuple[int, float]:
                -round (int): Round number.
                -start_time (time): Current time when round is going to start.
        """
        return (self._round, self._round_start_time, self._expected_nodes)

    async def is_concurrent(self):
        return False


class RoundEndEvent(NodeEvent):
    def __init__(self, round, end_time):
        """Event triggered when round is going to start.

        Args:
            round (int): Round number.
            end_time (time): Current time when round has ended.
        """
        self._round_end_time = end_time
        self._round = round

    def __str__(self):
        return "Round ending"

    async def get_event_data(self):
        """Retrieves the round start event data.

        Returns:
            tuple[int, float]:
                -round (int): Round number.
                -end_time (time): Current time when round has ended.
        """
        return (self._round, self._round_end_time)

    async def is_concurrent(self):
        return False


class ExperimentFinishEvent(NodeEvent):
    def __init__(self):
        """Event triggered when experiment is going to finish."""

    def __str__(self):
        return "Experiment finished"

    async def get_event_data(self):
        pass

    async def is_concurrent(self):
        return False


class AggregationEvent(NodeEvent):
    def __init__(self, updates: dict, expected_nodes: set, missing_nodes: set):
        """Event triggered when model aggregation is ready.

        Args:
            updates (dict): Dictionary containing model updates.
            expected_nodes (set): Set of nodes expected to participate in aggregation.
            missing_nodes (set): Set of nodes that did not send their update.
        """
        self._updates = updates
        self._expected_nodes = expected_nodes
        self._missing_nodes = missing_nodes

    def __str__(self):
        return "Aggregation Ready"

    def update_updates(self, new_updates: dict):
        """Allows an external module to update the updates dictionary."""
        self._updates = new_updates

    async def get_event_data(self) -> tuple[dict, set, set]:
        """Retrieves the aggregation event data.

        Returns:
            tuple[dict, set, set]:
                - updates (dict): Model updates.
                - expected_nodes (set): Expected nodes.
                - missing_nodes (set): Missing nodes.
        """
        return (self._updates, self._expected_nodes, self._missing_nodes)

    async def is_concurrent(self) -> bool:
        return False


class UpdateNeighborEvent(NodeEvent):
    def __init__(self, node_addr, removed=False, joining=False):
        """Event triggered when a neighboring node is updated.

        Args:
            node_addr (str): Address of the neighboring node.
            removed (bool, optional): Indicates whether the node was removed.
                                      Defaults to False.
        """
        self._node_addr = node_addr
        self._removed = removed
        self._joining_federation = joining

    def __str__(self):
        return f"Node addr: {self._node_addr}, removed: {self._removed}"

    async def get_event_data(self) -> tuple[str, bool]:
        """Retrieves the neighbor update event data.

        Returns:
            tuple[str, bool]:
                - node_addr (str): Address of the neighboring node.
                - removed (bool): Whether the node was removed.
        """
        return (self._node_addr, self._removed)

    async def is_concurrent(self) -> bool:
        return False

    def is_joining_federation(self):
        return self._joining_federation


class NodeBlacklistedEvent(NodeEvent):
    def __init__(self, node_addr, blacklisted: bool = False):
        """
        Initializes a NodeBlacklistedEvent.

        Args:
            node_addr (str): The address of the node.
            blacklisted (bool, optional): True if the node is blacklisted,
                                          False if it's just marked as recently disconnected.
        """
        self._node_addr = node_addr
        self._blacklisted = blacklisted

    def __str__(self):
        return f"Node addr: {self._node_addr} | Blacklisted: {self._blacklisted} | Recently disconnected: {not self._blacklisted}"

    async def get_event_data(self) -> tuple[str, bool]:
        """
        Retrieves the address of the node and its blacklist status.

        Returns:
            tuple[str, bool]: A tuple containing the node address and blacklist flag.
        """
        return (self._node_addr, self._blacklisted)

    async def is_concurrent(self):
        return True


class NodeFoundEvent(NodeEvent):
    def __init__(self, node_addr):
        """Event triggered when a new node is found.

        Args:
            node_addr (str): Address of the neighboring node.
        """
        self._node_addr = node_addr

    def __str__(self):
        return f"Node addr: {self._node_addr} found"

    async def get_event_data(self) -> tuple[str, bool]:
        """Retrieves the node found event data.

        Returns:
            tuple[str, bool]:
                - node_addr (str): Address of the node found.
        """
        return self._node_addr

    async def is_concurrent(self) -> bool:
        return True


class UpdateReceivedEvent(NodeEvent):
    def __init__(self, decoded_model, weight, source, round, local=False):
        """
        Initializes an UpdateReceivedEvent.

        Args:
            decoded_model (Any): The received model update.
            weight (float): The weight associated with the received update.
            source (str): The identifier or address of the node that sent the update.
            round (int): The round number in which the update was received.
            local (bool): Local update
        """
        self._source = source
        self._round = round
        self._model = decoded_model
        self._weight = weight
        self._local = local

    def __str__(self):
        return f"Update received from source: {self._source}, round: {self._round}"

    async def get_event_data(self) -> tuple[object, int, str, int, bool]:
        """
        Retrieves the event data.

        Returns:
            tuple[Any, float, str, int, bool]: A tuple containing:
                - The received model update.
                - The weight associated with the update.
                - The source node identifier.
                - The round number of the update.
                - If the update is local
        """
        return (self._model, self._weight, self._source, self._round, self._local)

    async def is_concurrent(self) -> bool:
        return False


class BeaconRecievedEvent(NodeEvent):
    def __init__(self, source, geoloc):
        """
        Initializes an BeaconRecievedEvent.

        Args:
            source (str): The received beacon source.
            geoloc (tuple): The geolocalzition associated with the received beacon source.
        """
        self._source = source
        self._geoloc = geoloc

    def __str__(self):
        return "Beacon recieved"

    async def get_event_data(self) -> tuple[str, tuple[float, float]]:
        """
        Retrieves the event data.

        Returns:
            tuple[str, tuple[float, float]]: A tuple containing:
                - The beacon's source.
                - the device geolocalization (latitude, longitude).
        """
        return (self._source, self._geoloc)

    async def is_concurrent(self) -> bool:
        return True
    
class DuplicatedMessageEvent(NodeEvent):
    """
    Event triggered when a message is received that has already been processed.

    Attributes:
        source (str): The address of the node that sent the duplicated message.
    """
    
    def __init__(self, source: str, message_type: str):
        self.source = source

    def __str__(self):
        return f"DuplicatedMessageEvent from {self.source}"

    async def get_event_data(self) -> tuple[str]:
        return (self.source)

    async def is_concurrent(self) -> bool:
        return True

"""                                                     ##############################
                                                        #         ADDON EVENTS       #
                                                        ##############################
"""


class GPSEvent(AddonEvent):
    """
    Event triggered by a GPS module providing distance data between nodes.

    Attributes:
        distances (dict): A dictionary mapping node addresses to their respective distances.
    """
    
    def __init__(self, distances: dict):
        """
        Initializes a GPSEvent.

        Args:
            distances (dict): Dictionary of distances from the current node to others.
        """
        self.distances = distances

    def __str__(self):
        return "GPSEvent"

    async def get_event_data(self) -> dict:
        """
        Returns the distance data associated with this event.

        Returns:
            dict: A copy of the distances dictionary.
        """
        return self.distances.copy()


class ChangeLocationEvent(AddonEvent):
    """
    Event used to signal a change in the node's geographical location.

    Attributes:
        latitude (float): New latitude of the node.
        longitude (float): New longitude of the node.
    """
    
    def __init__(self, latitude, longitude):
        """
        Initializes a ChangeLocationEvent.

        Args:
            latitude (float): The new latitude value.
            longitude (float): The new longitude value.
        """
        self.latitude = latitude
        self.longitude = longitude

    def __str__(self):
        return "ChangeLocationEvent"

    async def get_event_data(self):
        """
        Returns the new location coordinates associated with this event.

        Returns:
            tuple: A tuple containing latitude and longitude.
        """
        return (self.latitude, self.longitude)
    
class TestMetricsEvent(AddonEvent):
    def __init__(self, loss, accuracy):
        self._loss = loss
        self._accuracy = accuracy

    def __str__(self):
        return "TestMetricsEvent"

    async def get_event_data(self):
        return (self._loss, self._accuracy)
