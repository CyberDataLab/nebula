import logging

from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import CandidateSelector
from nebula.core.utils.locker import Locker


class STDandidateSelector(CandidateSelector):
    """
    Candidate selector for scenarios without a predefined structural topology.

    In cases where the federation topology is not explicitly structured,
    this selector chooses candidates based on the average number of neighbors 
    indicated in their offers. It selects approximately as many candidates as the 
    average neighbor count, aiming to balance connectivity dynamically.

    Attributes:
        candidates (list): List of candidate nodes available for selection.
        candidates_lock (Locker): Async lock to ensure thread-safe access to candidates.

    Methods:
        set_config(config): Optional configuration method.
        add_candidate(candidate): Adds a candidate node to the candidate list.
        select_candidates(): Selects candidates based on the average neighbor count from offers.
        remove_candidates(): Clears the candidates list.
        any_candidate(): Returns True if there is at least one candidate available.

    Inherits from:
        CandidateSelector: Base interface for candidate selection strategies.
    """
    
    def __init__(self):
        self.candidates = []
        self.candidates_lock = Locker(name="candidates_lock")

    async def set_config(self, config):
        pass

    async def add_candidate(self, candidate):
        self.candidates_lock.acquire()
        self.candidates.append(candidate)
        self.candidates_lock.release()

    async def select_candidates(self):
        """
        Select mean number of neighbors
        """
        self.candidates_lock.acquire()
        mean_neighbors = round(sum(n for _, n, _ in self.candidates) / len(self.candidates) if self.candidates else 0)
        logging.info(f"mean number of neighbors: {mean_neighbors}")
        cdts = self.candidates[:mean_neighbors]
        not_selected = set(self.candidates) - set(cdts)
        self.candidates_lock.release()
        return (cdts, not_selected)

    async def remove_candidates(self):
        self.candidates_lock.acquire()
        self.candidates = []
        self.candidates_lock.release()

    async def any_candidate(self):
        self.candidates_lock.acquire()
        any = True if len(self.candidates) > 0 else False
        self.candidates_lock.release()
        return any
