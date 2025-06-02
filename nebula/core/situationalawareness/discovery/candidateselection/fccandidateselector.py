from nebula.core.situationalawareness.discovery.candidateselection.candidateselector import CandidateSelector
from nebula.core.utils.locker import Locker


class FCCandidateSelector(CandidateSelector):
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
