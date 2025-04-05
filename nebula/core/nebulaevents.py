from abc import ABC, abstractmethod
import asyncio

class AddonEvent(ABC):
    @abstractmethod
    async def get_event_data(self):
        pass
    
class NodeEvent(ABC):
    @abstractmethod
    async def get_event_data(self):
        pass
    
    @abstractmethod
    async def is_concurrent(self):
        pass

class MessageEvent():
    def __init__(self, message_type, source, message):
        self.source = source
        self.message_type = message_type
        self.message = message

"""                                                     ##############################
                                                        #         NODE EVENTS        #
                                                        ##############################
"""

class RoundStartEvent(NodeEvent):
    def __init__(self, round, start_time):
        """Event triggered when round is going to start.

        Args:
            round (int): Round number.
            start_time (time): Current time when round is going to start.
        """
        self._round_start_time = start_time
        self._round = round

    def __str__(self):
        return "Round starting"

    async def get_event_data(self):
        """Retrieves the round start event data.

        Returns:
            tuple[int, float]:
                -round (int): Round number.
                -start_time (time): Current time when round is going to start.
        """
        return (self._round, self._round_start_time)
    
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
        pass

    def __str__(self):
        return "Experiment finished"

    async def get_event_data(self):
        pass
    
    async def is_concurrent(self):
        return False   

class AggregationEvent(NodeEvent):
    def __init__(self, updates : dict, expected_nodes : set, missing_nodes : set):
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
    def __init__(self, node_addr, removed=False):
        """Event triggered when a neighboring node is updated.

        Args:
            node_addr (str): Address of the neighboring node.
            removed (bool, optional): Indicates whether the node was removed. 
                                      Defaults to False.
        """
        self._node_addr = node_addr
        self._removed = removed
        
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
    
    
"""                                                     ##############################
                                                        #         ADDON EVENTS       #
                                                        ##############################
"""    
    
class GPSEvent(AddonEvent):
    def __init__(self, distances : dict):
        self.distances = distances
    
    def __str__(self):
        return "GPSEvent"    
        
    async def get_event_data(self) -> dict:
        return self.distances.copy()