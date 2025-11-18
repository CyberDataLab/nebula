from abc import ABC, abstractmethod
from typing import Any, Dict, List


class DatabaseAdapter(ABC):
    """
    Abstract base class for database operations.
    Defines a common interface for interacting with different database systems.
    """

    @abstractmethod
    async def _init_db_pool(self):
        """Initializes the database connection pool."""
        raise NotImplementedError

    @abstractmethod
    async def _close_db_pool(self):
        """Closes the database connection pool."""
        raise NotImplementedError

    # --- Node Management Functions ---
    @abstractmethod
    async def _list_nodes_by_federation_id(self, federation_id) -> List[Dict]:
        """Fetches all nodes for a specific federation."""
        raise NotImplementedError

    @abstractmethod
    async def _update_node_record(
        self,
        node_uid,
        idx,
        ip,
        port,
        role,
        neighbors,
        extras,
        timestamp,
        federation,
        federation_round,
        scenario,
        malicious,
    ) -> bool:
        """Inserts or updates a node record. Latitude/longitude must be included in `extras` (JSON)."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_nodes_by_federation_id(self, federation_id) -> bool:
        """Deletes all nodes for a specific federation."""
        raise NotImplementedError

    # --- Scenario Management Functions ---

    @abstractmethod
    async def _get_scenarios(self, user: str, role: str) -> Dict[str, Any]:
        """Return scenarios list and running scenario, given user and role."""
        raise NotImplementedError

    @abstractmethod
    async def _save_scenario(self, federation_id, name, start_time, end_time, scenario_config, status, username) -> bool:
        """Inserts or updates a scenario record."""
        raise NotImplementedError

    @abstractmethod
    async def _get_running_scenario(self, username=None, get_all=False) -> Dict | List[Dict] | None:
        """Retrieves running scenarios."""
        raise NotImplementedError

    @abstractmethod
    async def _get_scenario_by_federation_id(self, federation_id) -> Dict | None:
        """Retrieves a scenario by its federation_id."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_scenario_by_federation_id(self, federation_id) -> bool:
        """Deletes a scenario by its federation_id."""
        raise NotImplementedError

    @abstractmethod
    async def _check_scenario_with_role(self, role, federation_id, user=None) -> bool:
        """Verifies if a user can access a scenario by federation_id."""
        raise NotImplementedError

    # --- Notes Management Functions ---

    @abstractmethod
    async def _save_notes(self, scenario, notes) -> bool:
        """Saves or updates notes for a scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _get_notes(self, scenario) -> Dict | None:
        """Retrieves notes for a scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_note(self, scenario) -> bool:
        """Deletes the note for a scenario."""
        raise NotImplementedError

    # --- Scenario Finish (no API logic) ---

    @abstractmethod
    async def _finish_scenario(self, federation_id, all: bool = False) -> bool:
        """Sets status to finished for one scenario (by federation_id) or all running scenarios."""
        raise NotImplementedError

    @abstractmethod
    async def _scenario_set_status_to_completed(self, federation_id: str):
        raise NotImplementedError
