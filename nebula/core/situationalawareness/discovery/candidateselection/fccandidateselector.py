from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import CandidateSelector
from nebula.core.utils.locker import Locker


class FCCandidateSelector(CandidateSelector):
    """
    Candidate selector for fully-connected (FC) topologies.

    In a fully-connected network, all available candidates are accepted
    without applying any filtering criteria. This selector simply returns
    all collected candidates.

    Attributes:
        candidates (list): List of all discovered candidate nodes.
        candidates_lock (Locker): Lock to ensure thread-safe access to the candidate list.

    Methods:
        set_config(config): No-op for fully-connected mode.
        add_candidate(candidate): Adds a new candidate to the list.
        select_candidates(): Returns all currently stored candidates.
        remove_candidates(): Clears the candidate list.
        any_candidate(): Returns True if there is at least one candidate.

    Inherits from:
        CandidateSelector: Base class interface for candidate selection logic.
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
        In Fully-Connected topology all candidates should be selected
        """
        self.candidates_lock.acquire()
        cdts = self.candidates.copy()
        self.candidates_lock.release()
        return (cdts, [])

    async def remove_candidates(self):
        self.candidates_lock.acquire()
        self.candidates = []
        self.candidates_lock.release()

    async def any_candidate(self):
        self.candidates_lock.acquire()
        any = True if len(self.candidates) > 0 else False
        self.candidates_lock.release()
        return any
