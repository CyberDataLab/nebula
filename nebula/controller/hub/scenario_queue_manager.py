import collections
import logging
from typing import Any, Dict, List, Union
from nebula.core.utils.locker import Locker

class ScenarioQueueManager():
    class Scenario():
            def __init__(self, user_id: str, federation_id: str, data: Dict[str, Any]):
                self.user_id = user_id
                self.data = data
                self.federation_id = federation_id

    class UserScenarioQueue():
        def __init__(self, user_dest: str):
            self._scenarios_queue: collections.deque[ScenarioQueueManager.Scenario] = collections.deque()
            self._current_fed_id: str = None
            self._user_dest = user_dest
            self._scenarios_qeue_lock = Locker("scenarios_qeue_lock", async_lock=True)

        async def add_scenarios(
            self,
            user_id: str,
            federation_ids: Union[str, List[str]],
            data: Union[Dict[str, Any], List[Dict[str, Any]]]
        ):
            async with self._scenarios_qeue_lock:
                if isinstance(federation_ids, str) and isinstance(data, dict):
                    # caso simple
                    scenario = ScenarioQueueManager.Scenario(user_id, federation_ids, data)
                    self._scenarios_queue.append(scenario)
                elif isinstance(federation_ids, list) and isinstance(data, list):
                    # caso mÃºltiple
                    for fed_id, d in zip(federation_ids, data):
                        scenario = ScenarioQueueManager.Scenario(user_id, fed_id, d)
                        self._scenarios_queue.append(scenario)
                else:
                    raise TypeError("Not Valid data types")

        async def next_scenario(self) -> tuple[str, str, Dict[str, Any]] | None:
            async with self._scenarios_qeue_lock:
                if self._scenarios_queue:
                    next_scenario = self._scenarios_queue.popleft()
                    self._current_fed_id = next_scenario.federation_id
                    return (next_scenario.user_id, next_scenario.federation_id, next_scenario.data)
                else:
                    self._current_fed_id = ""
                    return None

        def get_user_destination(self):
            return self._user_dest

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._active_scenarios: Dict[str, ScenarioQueueManager.Scenario] = {}                # Indexed by Federation-ID
        self._active_user_qeues: Dict[str, ScenarioQueueManager.UserScenarioQueue] = {}       # Indexed by User
        self._active_scenarios_lock = Locker("active_scenarios_lock", async_lock=True)
        self._active_user_qeues_lock = Locker("active_user_qeues_lock", async_lock=True)

    async def _get_scenario_from_id(self, federation_id: str) -> Scenario | None:
        async with self._active_scenarios_lock:
            return self._active_scenarios.get(federation_id, None)

    async def _add_scenario_from_id(self, federation_id: str, scenario: Scenario):
        async with self._active_scenarios_lock:
            self._active_scenarios[federation_id] = scenario

    async def _pop_scenario_from_id(self, federation_id: str):
        async with self._active_scenarios_lock:
            self._active_scenarios.pop(federation_id)

    async def _get_qeue_from_user(self, user: str) -> UserScenarioQueue | None:
        async with self._active_user_qeues_lock:
            return self._active_user_qeues.get(user, None)

    async def _add_qeue_from_user(self, user: str, user_dest: str):
        async with self._active_user_qeues_lock:
            self._active_user_qeues[user] = ScenarioQueueManager.UserScenarioQueue(user_dest)

    async def add_scenarios(
            self,
            user_id: str,
            user_dest: str,
            federation_ids: Union[str, List[str]],
            data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ):
        """
            Update or create UserScenarioQeue for 'user_id'
        """
        user_qeue = await self._get_qeue_from_user(user=user_id)
        if user_qeue:
            await user_qeue.add_scenarios(user_id, federation_ids, data)
        else:
            await self._add_qeue_from_user(user_id, user_dest)
            user_qeue = await self._get_qeue_from_user(user_id)
            await user_qeue.add_scenarios(user_id=user_id, federation_ids=federation_ids, data=data)

    async def get_next_scenario(self, federation_id: str = "", user: str = "") -> tuple[str, str, Dict[str, Any]] | None:
        if user:
            user_qeue = await self._get_qeue_from_user(user)
            next_scenario = await user_qeue.next_scenario()
            return next_scenario
        else:
            scenario_finished = await self._get_scenario_from_id(federation_id)
            if scenario_finished:
                user_qeue = await self._get_qeue_from_user(scenario_finished.user_id)
                next_scenario = await user_qeue.next_scenario()
                return next_scenario
            else:
                # Message ID not found
                return None

    async def get_user_destination(self, federation_id: str) -> str:
        scenario = await self._get_scenario_from_id(federation_id)
        if scenario:
            user_qeue = await self._get_qeue_from_user(scenario.user_id)
            return user_qeue.get_user_destination()
        else:
            # Message ID not found
            return ""
