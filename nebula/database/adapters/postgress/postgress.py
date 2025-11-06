import logging
import os
import datetime
import json
from typing import List
import asyncpg
import asyncio
from typing import Any, Dict

from nebula.database.database_adapter_interface import DatabaseAdapter
from nebula.database.schemas.errors import (
    DatabaseErrorDefinition,
    POOL_NOT_INITIALIZED,
    CONNECTION_FAILED,
    CONNECTION_TIMEOUT,
    CONNECTION_CLOSED,
    TABLE_NOT_FOUND,
    COLUMN_NOT_FOUND,
    PERMISSION_DENIED,
    DATA_FORMAT_ERROR,
    QUERY_FAILED,
    UNKNOWN_DB_ERROR,
)

from nebula.database.schemas.responses import *
from nebula.database.utils.api_utils import raise_error

# --- Configuration ---
# Use environment variables for database credentials from the Docker Compose file
DATABASE_URL = f"postgresql://{os.environ.get('DB_USER')}:{os.environ.get('DB_PASSWORD')}@{os.environ.get('DB_HOST')}:{os.environ.get('DB_PORT')}/nebula"

# Asynchronous lock for node updates
_node_lock = asyncio.Lock()


class PostgresDB(DatabaseAdapter):
    """
    PostgreSQL implementation of the Database interface.
    """
    def __init__(self):
        self.pool = None

    async def _init_db_pool(self):
        """
        Initializes the asynchronous PostgreSQL connection pool.
        This should be called once when the application starts.
        Retries connection on failure to handle race conditions during startup.
        """
        if self.pool is None:
            attempts = 10
            for attempt in range(attempts):
                try:
                    self.pool = await asyncpg.create_pool(
                        dsn=DATABASE_URL,
                        min_size=5,  # Minimum number of connections in the pool
                        max_size=20, # Maximum number of connections in the pool
                    )
                    logging.info("Database connection pool successfully created.")
                    return
                except (ConnectionRefusedError, asyncpg.exceptions.CannotConnectNowError) as e:
                    if attempt < attempts - 1:
                        logging.warning(
                            f"Database connection failed. Attempt {attempt + 1}/{attempts}. Retrying in 5 seconds... "
                            f"Error: {e}"
                        )
                        await asyncio.sleep(5)
                    else:
                        logging.critical(
                            f"Failed to create database connection pool after {attempts} attempts: {e}", exc_info=True
                        )
                        raise
                except Exception as e:
                    logging.critical(
                        f"An unexpected error occurred while creating database connection pool: {e}", exc_info=True
                    )
                    raise

    async def _close_db_pool(self):
        """
        Closes the asynchronous PostgreSQL connection pool.
        This should be called once when the application shuts down gracefully.
        """
        if self.pool:
            await self.pool.close()
            logging.info("Database connection pool closed.")

    # --- Node Management Functions ---

    async def _list_nodes(self, federation_id:str=None, sort_by:str="idx"):
        """
        Retrieves a list of nodes from the nodes database, optionally filtered by scenario and sorted.
        """
        # Validate sort_by to prevent SQL injection
        allowed_sort_fields = ["uid", "idx", "ip", "port", "role", "timestamp", "federation", "round"]
        if sort_by not in allowed_sort_fields:
            sort_by = "idx" # Default to a safe field

        try:
            async with self.pool.acquire() as conn:
                if federation_id:
                    # Using f-string for column names is generally safe if validated as above
                    command = f"SELECT * FROM nodes WHERE federation = $1 ORDER BY {sort_by};"
                    result = await conn.fetch(command, federation_id)
                else:
                    command = f"SELECT * FROM nodes ORDER BY {sort_by};"
                    result = await conn.fetch(command)

                # Convert to list of dicts and expose latitude/longitude from extras for compatibility
                rows = []
                for record in result:
                    row = dict(record)
                    extras = row.get("extras")
                    if isinstance(extras, str):
                        try:
                            extras = json.loads(extras)
                        except json.JSONDecodeError:
                            extras = None
                    if isinstance(extras, dict):
                        if "latitude" in extras and "latitude" not in row:
                            row["latitude"] = extras.get("latitude")
                        if "longitude" in extras and "longitude" not in row:
                            row["longitude"] = extras.get("longitude")
                    rows.append(row)
                return rows
        except asyncpg.PostgresError as e:
            logging.error(f"Error occurred while listing nodes: {e}")
            return None


    async def _list_nodes_by_federation_id(self, federation_id:str) -> List[Dict]:
        """
        Fetches all nodes associated with a specific scenario, ordered by their index as integers.
        """
        self._verify_pool()

        try:
            async with self.pool.acquire() as conn:
                command = "SELECT * FROM nodes WHERE federation = $1 ORDER BY CAST(idx AS INTEGER) ASC;"
                result = await conn.fetch(command, federation_id)
                rows = []
                for record in result:
                    row = dict(record)
                    extras = row.get("extras")
                    if isinstance(extras, str):
                        try:
                            extras = json.loads(extras)
                        except json.JSONDecodeError:
                            extras = None
                    if isinstance(extras, dict):
                        if "latitude" in extras and "latitude" not in row:
                            row["latitude"] = extras.get("latitude")
                        if "longitude" in extras and "longitude" not in row:
                            row["longitude"] = extras.get("longitude")
                    rows.append(row)
                return rows
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)


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
        federation_id,
        malicious,
    ) -> bool:
        """
        Inserts or updates a node record in the database for a given scenario, ensuring thread-safe access.
        """
        self._verify_pool()

        try:
            async with _node_lock:
                async with self.pool.acquire() as conn:
                    # Ensure `extras` is a JSON string when provided
                    extras_payload = None
                    if extras is not None:
                        if isinstance(extras, str):
                            extras_payload = extras
                        else:
                            try:
                                extras_payload = json.dumps(extras)
                            except (TypeError, ValueError):
                                # Fallback to empty JSON object on serialization issues
                                logging.warning("Unable to serialize extras to JSON, storing as empty object.")
                                extras_payload = json.dumps({})
                    # Ensure malicious is stored as text if the column expects text
                    malicious_payload = malicious if isinstance(malicious, str) else str(malicious)
                    async with conn.transaction():
                        result = await conn.fetchrow(
                            "SELECT * FROM nodes WHERE uid = $1 AND scenario = $2 FOR UPDATE;",
                            node_uid, federation_id
                        )
                        if result is None:
                            # Insert new node
                            await conn.execute(
                                """
                                INSERT INTO nodes (uid, idx, ip, port, role, neighbors,
                                                timestamp, federation, round, scenario, extras, malicious)
                                VALUES ($1, $2, $3, $4, $5, $6,
                                        $7, $8, $9, $10, $11::jsonb, $12);
                                """,
                                node_uid, idx, ip, port, role, neighbors,
                                timestamp, federation, federation_round, federation_id, extras_payload, malicious_payload,
                            )
                        else:
                            # Update existing node
                            await conn.execute(
                                """
                                UPDATE nodes SET idx = $1, ip = $2, port = $3, role = $4, neighbors = $5,
                                timestamp = $6, federation = $7, round = $8, extras = $9::jsonb, malicious = $10
                                WHERE uid = $11 AND scenario = $12;
                                """,
                                idx, ip, port, role, neighbors,
                                timestamp, federation, federation_round, extras_payload, malicious_payload,
                                node_uid, federation_id,
                            )
                        updated_row = await conn.fetchrow("SELECT * from nodes WHERE uid = $1 AND scenario = $2;", node_uid, federation_id)
                        return True if updated_row else False
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)


    async def _remove_all_nodes(self):
        """
        Deletes all node records from the nodes database.
        """
        async with self.pool.acquire() as conn:
            await conn.execute("TRUNCATE nodes CASCADE;") # Use CASCADE if there are foreign key dependencies


    async def _remove_nodes_by_federation_id(self, federation_id:str) -> bool:
        """
        Deletes all nodes associated with a specific scenario from the database.
        """
        self._verify_pool()
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM nodes WHERE federation = $1;", federation_id)
                return True
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    # --- Scenario Management Functions ---

    def _build_order_by_clause(self, sort_by: str) -> str:
        """Build a safe ORDER BY clause supporting legacy and ISO timestamps."""
        allowed_sort_fields = ["start_time", "title", "username", "status", "name", "model", "dataset", "rounds"]
        if sort_by not in allowed_sort_fields:
            sort_by = "start_time"

        if sort_by == "start_time":
            return """
                ORDER BY
                    CASE
                        WHEN start_time IS NULL OR start_time = '' THEN 1
                        ELSE 0
                    END,
                    CASE
                        WHEN start_time IS NULL OR start_time = '' THEN NULL
                        WHEN start_time LIKE '%T%'
                            THEN to_timestamp(split_part(start_time, '.', 1), 'YYYY-MM-DD"T"HH24:MI:SS')
                        ELSE to_timestamp(start_time, 'DD/MM/YYYY HH24:MI:SS')
                    END DESC
            """

        if sort_by in {"title", "model", "dataset", "rounds"}:  # Fields in JSONB config
            return f"ORDER BY config->>'{sort_by}'"

        return f"ORDER BY {sort_by}"


    async def _get_all_scenarios_and_check_completed(
        self,
        user: str,
        role: str,
        sort_by: str = "start_time",
    ):
        """
        Retrieves all scenarios, sorts them, and updates the status if necessary.
        Returns a list of dictionaries, where each dictionary represents a scenario.
        """
        # Safe list of allowed sorting fields to prevent SQL injection.
        order_by_clause = self._build_order_by_clause(sort_by)

        try:
            async with self.pool.acquire() as conn:
                # Base query that extracts fields from the JSONB using the ->> operator
                command = f"""
                    SELECT
                        federation_id,
                        name,
                        username,
                        status,
                        start_time,
                        end_time,
                        config->>'title' AS title,
                        config->>'model' AS model,
                        config->>'dataset' AS dataset,
                        config->>'rounds' AS rounds,
                        config  -- Return the full config object
                    FROM scenarios
                """
                params = []
                if role != "admin":
                    command += " WHERE username = $1" # username is a direct column
                    params.append(user)

                command += f" {order_by_clause};"

                result_dicts = await conn.fetch(command, *params)
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

        scenarios_to_return = [dict(s) for s in result_dicts]

        re_fetch_required = False
        for scenario in scenarios_to_return:
            if scenario["status"] == "running":
                if await self._check_scenario_federation_completed(scenario["federation_id"]):
                    await self._scenario_set_status_to_completed(scenario["federation_id"])
                    re_fetch_required = True
                    break

        if re_fetch_required:
            # Recursively call to get fresh data after status update
            return await self._get_all_scenarios_and_check_completed(user, role, sort_by)

        return scenarios_to_return


    async def _save_scenario(self, federation_id:str, alias:str, scenario_name:str, start_time:datetime, end_time:datetime, scenario:dict, status:str, username:str) -> bool:
        """
        Inserts or updates a scenario record using the PostgreSQL "UPSERT" pattern.
        All configuration is saved in the 'config' column of type JSONB.
        Direct columns (name, start_time, end_time, username, status) are also handled.
        """
        self._verify_pool()

        # Ensure scenario is a dictionary before dumping to JSON
        if not isinstance(scenario, dict):
            try:
                scenario = json.loads(scenario)
            except (json.JSONDecodeError, TypeError):
                logging.error("scenario is not a valid JSON string or dict.")
                self._log_and_raise_error(DATA_FORMAT_ERROR)

        command = """
            INSERT INTO scenarios (federation_id, alias, name, start_time, end_time, username, status, config)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            ON CONFLICT (federation_id) DO UPDATE SET
                alias = EXCLUDED.alias,
                name = EXCLUDED.name,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                username = EXCLUDED.username,
                status = EXCLUDED.status,
                config = scenarios.config || EXCLUDED.config; -- Merge JSONB
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(command, federation_id, alias, scenario_name, start_time, end_time, username, status, json.dumps(scenario))
                return True
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _scenario_set_all_status_to_finished(self) -> bool:
        """
        Sets the status of all 'running' scenarios to 'finished'
        and updates their 'end_time' (both in the direct column and within JSONB).
        """
        self._verify_pool()

        current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        command = """
            UPDATE scenarios
            SET
                status = 'finished',
                end_time = $1,
                config = jsonb_set(config, '{status}', '"finished"') ||
                         jsonb_set(config, '{end_time}', $2::jsonb)
            WHERE status = 'running';
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(command, current_time, json.dumps(current_time))
                return True
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _scenario_set_status_to_finished(self, federation_id:str) -> bool:
        """
        Sets the status of a specific scenario to 'finished' and updates its 'end_time'.
        Updates both the direct columns and the JSONB 'config'.
        """
        self._verify_pool()

        current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        command = """
            UPDATE scenarios
            SET
                status = 'finished',
                end_time = $1,
                config = jsonb_set(
                             jsonb_set(config, '{status}', '"finished"'),
                             '{end_time}', $2::jsonb
                           )
            WHERE federation_id = $3;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(command, current_time, json.dumps(current_time), federation_id)
                return True
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _scenario_set_status_to_completed(self, federation_id:str):
        """
        Sets the status of a specific scenario to 'completed'.
        Updates both the direct column and the JSONB 'config'.
        """
        command = """
            UPDATE scenarios
            SET
                status = 'completed',
                config = jsonb_set(config, '{status}', '"completed"')
            WHERE federation_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(command, federation_id)
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _finish_scenario(self, federation_id: str, all: bool = False) -> bool:
        """
        Consolidated method to set scenarios to finished.
        """
        self._verify_pool()

        if all:
            return await self._scenario_set_all_status_to_finished()
        else:
            return await self._scenario_set_status_to_finished(federation_id)

    async def _get_running_scenario(self, username:str=None, get_all:bool=False) -> Dict | List[Dict] | None:
        """
        Retrieves scenarios with a 'running' status, optionally filtered by user.
        Returns full scenario record (including direct columns and config JSONB).
        """
        self._verify_pool()

        try:
            async with self.pool.acquire() as conn:
                params = ["running"]
                # Select all columns to get both direct and config data
                command = "SELECT federation_id, name, username, status, start_time, end_time, config FROM scenarios WHERE status = $1"

                if username:
                    command += " AND username = $2"
                    params.append(username)

                if get_all:
                    result = [dict(row) for row in await conn.fetch(command, *params)] # Convert records to dicts
                else:
                    result_row = await conn.fetchrow(command, *params)
                    result = dict(result_row) if result_row else None
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)
        return result

    async def _get_scenarios(self, user: str, role: str, sort_by:str="start_time") -> Dict[str, Any]:
        """
        Compose scenarios list and running scenario respecting role.
        """
        self._verify_pool()

        order_by_clause = self._build_order_by_clause(sort_by)

        try:
            async with self.pool.acquire() as conn:
                # Select direct columns and relevant fields from config JSONB
                command = """
                    SELECT
                        federation_id,
                        name,
                        username,
                        status,
                        start_time,
                        end_time,
                        config->>'title' AS title,
                        config->>'model' AS model,
                        config->>'dataset' AS dataset,
                        config->>'rounds' AS rounds,
                        config -- return the full config JSONB
                    FROM scenarios
                """
                params = []

                if role != "admin":
                    command += " WHERE username = $1" # username is a direct column now
                    params.append(user)

                full_command = f"{command} {order_by_clause};"
                return await conn.fetch(full_command, *params)
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _get_scenario_by_federation_id(self, federation_id:str) -> Dict | None:
        """
        Retrieves the complete record of a scenario by its name.
        """
        self._verify_pool()

        try:
            async with self.pool.acquire() as conn:
                result_row = await conn.fetchrow("SELECT name, start_time, end_time, username, status, config FROM scenarios WHERE federation_id = $1;", federation_id)

            result = dict(result_row) if result_row else None

            if result and result.get('config'):
                # Assuming 'config' is a JSON string from the DB, so we parse it
                # It might already be a dict if asyncpg handles JSONB conversion automatically
                config_data = result['config']
                if isinstance(config_data, str):
                    try:
                        config_data = json.loads(config_data)
                    except json.JSONDecodeError:
                        config_data = {}

                # Extract the 'scenario_title' and add it as a top-level key
                result['title'] = config_data.get('scenario_title')
                result['description'] = config_data.get('description')
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)
        return result


    async def _remove_scenario_by_federation_id(self, federation_id:str) -> bool:
        """
        Delete a scenario from the database by its unique name.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM scenarios WHERE federation_id = $1;", federation_id)
                nodes_removed = await self._remove_nodes_by_federation_id(federation_id)
            logging.info(f"Scenario '{federation_id}' successfully removed.")
            return True and nodes_removed
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)


    async def _check_scenario_federation_completed(self, federation_id:str):
        """
        Check if all nodes in a given scenario have completed the required federation rounds.
        """
        try:
            async with self.pool.acquire() as conn:
                # Retrieve the total rounds for the scenario from the 'config' JSONB column
                scenario_rounds_str = await conn.fetchval("SELECT config->>'rounds' AS rounds FROM scenarios WHERE federation_id = $1;", federation_id)

                if not scenario_rounds_str:
                    logging.warning(f"Scenario '{federation_id}' not found or 'rounds' not defined.")
                    return False

                # Ensure total_rounds is an integer for comparison
                total_rounds = int(scenario_rounds_str)

                # Fetch the current round progress of all nodes in that scenario
                nodes = await conn.fetch("SELECT round FROM nodes WHERE federation = $1;", federation_id)

                if not nodes:
                    logging.info(f"No nodes found for federation '{federation_id}'. Federation not considered completed.")
                    return False

                # Check if all nodes have completed the total rounds
                return all(int(node["round"]) >= total_rounds for node in nodes)

        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)


    async def _check_scenario_with_role(self, role:str, federation_id:str, user:str=None):
        """
        Verify if a scenario exists that the user with the given role and username can access.
        """
        self._verify_pool()

        scenario_info = await self._get_scenario_by_federation_id(federation_id)

        if not scenario_info:
            return False  # Scenario does not exist

        if role == "admin":
            return True  # Admins can access any existing scenario

        if scenario_info.get("username") == user:
            return True

    # --- Notes Management Functions ---

    async def _save_notes(self, federation_id: str, notes: str) -> bool:
        """
        Save or update notes associated with a specific scenario.
        """
        self._verify_pool()
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO notes (federation_id, scenario_notes) VALUES ($1, $2)
                    ON CONFLICT(federation_id) DO UPDATE SET scenario_notes = EXCLUDED.scenario_notes;
                    """,
                    federation_id, notes,
                )
                return True
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _get_notes(self, federation_id: str) -> Dict | None:
        """
        Retrieve notes associated with a specific scenario.
        """
        self._verify_pool()
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM notes WHERE federation_id = $1;", federation_id)
                if row is None:
                    # No notes stored for this scenario yet
                    return None
                return dict(row)
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    async def _remove_note(self, federation_id: str):
        """
        Delete the note associated with a specific scenario.
        """
        self._verify_pool()
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM notes WHERE federation_id = $1;", federation_id)
                return True
        except Exception as e:
            db_error = self._map_pg_exception_to_error(e)
            self._log_and_raise_error(db_error)

    """                                             ###############################
                                                    #       ERROR MANAGEMENT      #
                                                    ###############################
    """

    def _verify_pool(self):
        if not self.pool:
            self._log_and_raise_error(POOL_NOT_INITIALIZED)

    def _log_and_raise_error(err: DatabaseErrorDefinition):
        error_msg = f"ERROR_CODE: {err.code}\n ERROR: {err.error}\n Additional info: {err.message}"
        logging.info(error_msg)
        raise_error(err)

    def _map_pg_exception_to_error(self, exc: Exception) -> DatabaseErrorDefinition:
        """
        Maping asyncpg exceptions to DatabaseErrorDefinition.
        """
        # --- Connection errors ---
        if isinstance(exc, asyncpg.CannotConnectNowError):
            return CONNECTION_FAILED
        if isinstance(exc, asyncpg.InterfaceError):
            return CONNECTION_CLOSED
        if isinstance(exc, asyncpg.PoolAcquireTimeoutError):
            return CONNECTION_TIMEOUT

        # --- Errors SQL / query ---
        if isinstance(exc, asyncpg.UndefinedTableError):
            return TABLE_NOT_FOUND
        if isinstance(exc, asyncpg.UndefinedColumnError):
            return COLUMN_NOT_FOUND
        if isinstance(exc, asyncpg.InsufficientPrivilegeError):
            return PERMISSION_DENIED
        if isinstance(exc, asyncpg.DataError):
            return DATA_FORMAT_ERROR
        if isinstance(exc, asyncpg.PostgresError):
            return QUERY_FAILED

        # --- Default ---
        return UNKNOWN_DB_ERROR
