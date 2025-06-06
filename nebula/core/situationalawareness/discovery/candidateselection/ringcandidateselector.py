import random

from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import CandidateSelector
from nebula.core.utils.locker import Locker


class RINGCandidateSelector(CandidateSelector):
    """
    Candidate selector for ring topology.

    In a ring topology, each node connects to a limited set of neighbors forming a closed loop.
    This selector chooses exactly one candidate from the pool of candidates that has the fewest neighbors,
    aiming to maintain a balanced ring by connecting nodes with fewer existing connections, avoiding overcharging
    as possible.

    Attributes:
        candidates (list): List of candidate nodes available for selection.
        candidates_lock (Locker): Async lock to ensure thread-safe access to candidates.

    Methods:
        set_config(config): Optional configuration, currently unused.
        add_candidate(candidate): Adds a candidate node to the candidate list.
        select_candidates(): Selects and returns a single candidate with the minimum number of neighbors.
        remove_candidates(): Clears the candidates list.
        any_candidate(): Returns True if there is at least one candidate available.

    Inherits from:
        CandidateSelector: Base interface for candidate selection strategies.
    """
    
    def __init__(self):
        self._candidates = []
        self._rejected_candidates = []
        self.candidates_lock = Locker(name="candidates_lock")

    async def set_config(self, config):
        pass

    async def add_candidate(self, candidate):
        """
        To avoid topology problems select 1st candidate found
        """
        self.candidates_lock.acquire()
        self._candidates.append(candidate)
        self.candidates_lock.release()

    async def select_candidates(self):
        self.candidates_lock.acquire()
        cdts = []

        if self._candidates:
            min_neighbors = min(self._candidates, key=lambda x: x[1])[1]
            tied_candidates = [c for c in self._candidates if c[1] == min_neighbors]

            selected = random.choice(tied_candidates)
            cdts.append(selected)

        for cdt in self._candidates:
            if cdt not in cdts:
                self._rejected_candidates.append(cdt)

        not_cdts = self._rejected_candidates.copy()
        self.candidates_lock.release()
        return (cdts, not_cdts)

    async def remove_candidates(self):
        self.candidates_lock.acquire()
        self._candidates = []
        self.candidates_lock.release()

    async def any_candidate(self):
        self.candidates_lock.acquire()
        any = True if len(self._candidates) > 0 else False
        self.candidates_lock.release()
        return any
