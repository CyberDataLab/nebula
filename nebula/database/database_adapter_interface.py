from abc import ABC, abstractmethod


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

    @abstractmethod
    async def _list_nodes(self, scenario_name=None, sort_by="idx"):
        """Retrieves a list of nodes."""
        raise NotImplementedError

    @abstractmethod
    async def _list_nodes_by_scenario_name(self, scenario_name):
        """Fetches all nodes for a specific scenario."""
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
        run_hash,
        malicious,
    ):
        """Inserts or updates a node record. Latitude/longitude must be included in `extras` (JSON)."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_all_nodes(self):
        """Deletes all node records."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_nodes_by_scenario_name(self, scenario_name):
        """Deletes all nodes for a specific scenario."""
        raise NotImplementedError

    # --- Scenario Management Functions ---

    @abstractmethod
    async def _get_all_scenarios(self, username, role, sort_by="start_time"):
        """Retrieves all scenarios."""
        raise NotImplementedError

    @abstractmethod
    async def _get_all_scenarios_and_check_completed(self, username, role, sort_by="start_time"):
        """Retrieves all scenarios and checks for completion."""
        raise NotImplementedError

    @abstractmethod
    async def _scenario_update_record(self, name, start_time, end_time, scenario_config, status, username):
        """Inserts or updates a scenario record."""
        raise NotImplementedError

    @abstractmethod
    async def _scenario_set_all_status_to_finished(self):
        """Sets the status of all running scenarios to 'finished'."""
        raise NotImplementedError

    @abstractmethod
    async def _scenario_set_status_to_finished(self, scenario_name):
        """Sets the status of a specific scenario to 'finished'."""
        raise NotImplementedError

    @abstractmethod
    async def _scenario_set_status_to_completed(self, scenario_name):
        """Sets the status of a specific scenario to 'completed'."""
        raise NotImplementedError

    @abstractmethod
    async def _get_running_scenario(self, username=None, get_all=False):
        """Retrieves running scenarios."""
        raise NotImplementedError

    @abstractmethod
    async def _get_completed_scenario(self):
        """Retrieves a completed scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _get_scenario_by_name(self, scenario_name):
        """Retrieves a scenario by its name."""
        raise NotImplementedError

    @abstractmethod
    async def _get_user_by_scenario_name(self, scenario_name):
        """Retrieves the user associated with a scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_scenario_by_name(self, scenario_name):
        """Deletes a scenario by its name."""
        raise NotImplementedError

    @abstractmethod
    async def _check_scenario_federation_completed(self, scenario_name):
        """Checks if a scenario's federation is complete."""
        raise NotImplementedError

    @abstractmethod
    async def _check_scenario_with_role(self, role, scenario_name, current_username=None):
        """Verifies if a user can access a scenario."""
        raise NotImplementedError

    # --- Notes Management Functions ---

    @abstractmethod
    async def _save_notes(self, scenario, notes):
        """Saves or updates notes for a scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _get_notes(self, scenario):
        """Retrieves notes for a scenario."""
        raise NotImplementedError

    @abstractmethod
    async def _remove_note(self, scenario):
        """Deletes the note for a scenario."""
        raise NotImplementedError

    # --- Scenario Finish (no API logic) ---

    @abstractmethod
    async def _finish_scenario(self, scenario_name, all: bool = False):
        """Sets status to finished for one scenario or all running scenarios."""
        raise NotImplementedError

    @abstractmethod
    async def _get_scenarios(self, user: str, role: str):
        """Return scenarios list and running scenario, given user and role."""
        raise NotImplementedError
