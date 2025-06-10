import logging

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import GPSEvent
from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import CandidateSelector
from nebula.core.utils.locker import Locker


class DistanceCandidateSelector(CandidateSelector):
    """
    Selects candidate nodes based on their physical proximity.

    This selector uses geolocation data to filter candidates within a 
    maximum distance threshold. It listens for GPS updates and maintains 
    a mapping of node identifiers to their distances and coordinates.

    Attributes:
        MAX_DISTANCE_THRESHOLD (int): Maximum distance (in meters) allowed 
            for a node to be considered a valid candidate.
        candidates (list): List of candidate nodes to be evaluated.
        candidates_lock (Locker): Async lock for managing concurrent access 
            to the candidate list.
        nodes_distances (dict): Maps node IDs to a tuple containing the 
            distance and GPS coordinates.
        nodes_distances_lock (Locker): Async lock for the distance mapping.
        _verbose (bool): Flag to enable verbose logging for debugging.

    Methods:
        set_config(config): Subscribes to GPS events for distance updates.
        add_candidate(candidate): Adds a new candidate to the list.
        select_candidates(): Returns candidates within the allowed distance.
        remove_candidates(): Clears the candidate list.
        any_candidate(): Returns True if there is at least one candidate.

    Inherits from:
        CandidateSelector: Base class interface for candidate selection logic.
    """
    # INFO: This value may change according to the needs of the federation
    MAX_DISTANCE_THRESHOLD = 200

    def __init__(self):
        self.candidates = []
        self.candidates_lock = Locker(name="candidates_lock", async_lock=True)
        self.nodes_distances: dict[str, tuple[float, tuple[float, float]]] = None
        self.nodes_distances_lock = Locker("nodes_distances_lock", async_lock=True)
        self._verbose = False

    async def set_config(self, config):
        await EventManager.get_instance().subscribe_addonevent(GPSEvent, self._udpate_distances)

    async def _udpate_distances(self, gpsevent: GPSEvent):
        async with self.nodes_distances_lock:
            distances = await gpsevent.get_event_data()
            self.nodes_distances = distances

    async def add_candidate(self, candidate):
        async with self.candidates_lock:
            self.candidates.append(candidate)

    async def select_candidates(self):
        async with self.candidates_lock:
            async with self.nodes_distances_lock:
                nodes_available = [
                    candidate
                    for candidate in self.candidates
                    if candidate[0] in self.nodes_distances
                    and self.nodes_distances[candidate[0]][0] < self.MAX_DISTANCE_THRESHOLD
                ]
                if self._verbose:
                    logging.info(f"Nodes availables: {nodes_available}")
        return (nodes_available, [])

    async def remove_candidates(self):
        async with self.candidates_lock:
            self.candidates = []

    async def any_candidate(self):
        async with self.candidates_lock:
            any = True if len(self.candidates) > 0 else False
        return any
