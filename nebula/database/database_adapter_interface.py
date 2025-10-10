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

    # --- User Management Functions ---

    @abstractmethod
    async def _insert_default_admin(self):
        """Inserts a default admin user."""
        raise NotImplementedError

    @abstractmethod
    async def _list_users(self, all_info=False):
        """Retrieves a list of users."""
        raise NotImplementedError

    @abstractmethod
    async def _get_user_info(self, user):
        """Fetches detailed information for a specific user."""
        raise NotImplementedError

    @abstractmethod
    async def _verify(self, user, password):
        """Verifies user credentials."""
        raise NotImplementedError

    @abstractmethod
    async def _verify_hash_algorithm(self, user):
        """Checks the password hash algorithm for a user."""
        raise NotImplementedError

    @abstractmethod
    async def _delete_user_from_db(self, user):
        """Deletes a user from the database."""
        raise NotImplementedError

    @abstractmethod
    async def _add_user(self, user, password, role):
        """Adds a new user."""
        raise NotImplementedError

    @abstractmethod
    async def _update_user(self, user, password, role):
        """Updates an existing user."""
        raise NotImplementedError

    # --- Node Management Functions ---

    #TODO not used
    @abstractmethod
    async def _list_nodes(self, federation_id=None, sort_by="idx"):
        """Retrieves a list of nodes."""
        raise NotImplementedError

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

    #TODO not used
    @abstractmethod
    async def _remove_all_nodes(self):
        """Deletes all node records."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_nodes_by_federation_id(self, federation_id) -> bool:
        """Deletes all nodes for a specific federation."""
        raise NotImplementedError

    # --- Scenario Management Functions ---

    #TODO not used
    @abstractmethod
    async def _get_all_scenarios(self, username, role, sort_by="start_time"):
        """Retrieves all scenarios."""
        raise NotImplementedError

    #TODO not used
    @abstractmethod
    async def _get_all_scenarios_and_check_completed(self, username, role, sort_by="start_time"):
        """Retrieves all scenarios and checks for completion."""
        raise NotImplementedError

    @abstractmethod
    async def _scenario_update_record(self, federation_id, name, start_time, end_time, scenario_config, status, username) -> bool:
        """Inserts or updates a scenario record."""
        raise NotImplementedError

    #TODO not on API
    @abstractmethod
    async def _scenario_set_all_status_to_finished(self) -> bool:
        """Sets the status of all running scenarios to 'finished'."""
        raise NotImplementedError

    #TODO not on API
    @abstractmethod
    async def _scenario_set_status_to_finished(self, federation_id):
        """Sets the status of a specific scenario (by federation_id) to 'finished'."""
        raise NotImplementedError

    #TODO not on API
    @abstractmethod
    async def _scenario_set_status_to_completed(self, federation_id):
        """Sets the status of a specific scenario (by federation_id) to 'completed'."""
        raise NotImplementedError

    @abstractmethod
    async def _get_running_scenario(self, username=None, get_all=False) -> Dict | List[Dict] | None:
        """Retrieves running scenarios."""
        raise NotImplementedError

    #TODO not used
    @abstractmethod
    async def _get_completed_scenario(self):
        """Retrieves a completed scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _get_scenario_by_federation_id(self, federation_id) -> Dict | None:
        """Retrieves a scenario by its federation_id."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_scenario_by_federation_id(self, federation_id) -> bool:
        """Deletes a scenario by its federation_id."""
        raise NotImplementedError

    #TODO not on API
    @abstractmethod
    async def _check_scenario_federation_completed(self, federation_id):
        """Checks if a scenario's federation is complete."""
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
    async def _get_scenarios(self, user: str, role: str) -> Dict[str, Any]:
        """Return scenarios list and running scenario, given user and role."""
        raise NotImplementedError
