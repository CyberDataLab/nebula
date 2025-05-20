from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import CandidateSelector
from nebula.core.utils.locker import Locker
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import GPSEvent
import logging

class DistanceCandidateSelector(CandidateSelector):
    MAX_DISTANCE_THRESHOLD = 100
    MIN_DISTANCE_THRESHOLD = 100

    def __init__(self):
        self.candidates = []
        self.candidates_lock = Locker(name="candidates_lock", async_lock=True)
        self.nodes_distances: dict[str, tuple[float, tuple[float, float]]] = None
        self.nodes_distances_lock = Locker("nodes_distances_lock", async_lock=True)
        
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
                # Filtrar candidatos cuya ID está en nodes_distances y su distancia < MAX_DISTANCE_THRESHOLD
                nodes_available = [
                    candidate for candidate in self.candidates
                    if candidate[0] in self.nodes_distances and
                    self.nodes_distances[candidate[0]][0] < self.MAX_DISTANCE_THRESHOLD
                ]
                logging.info(f"Nodes availables: {nodes_available}")
        return (nodes_available, [])
    
    async def remove_candidates(self):
        async with self.candidates_lock:
            self.candidates = []

    async def any_candidate(self):
        async with self.candidates_lock:
            any = True if len(self.candidates) > 0 else False
        return any