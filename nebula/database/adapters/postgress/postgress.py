import logging
import os
import datetime
import json
import asyncpg
import asyncio

from passlib.context import CryptContext

from nebula.database.database_adapter_interface import DatabaseAdapter

# --- Configuration ---
# Use environment variables for database credentials from the Docker Compose file
DATABASE_URL = f"postgresql://{os.environ.get('DB_USER')}:{os.environ.get('DB_PASSWORD')}@{os.environ.get('DB_HOST')}:{os.environ.get('DB_PORT')}/nebula"

# Password hashing context (using Argon2)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

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

    # --- User Management Functions ---

    async def _insert_default_admin(self):
        """
        Inserts a default 'ADMIN' user into the database with a hashed password.
        The password must be provided via the ADMIN_PASSWORD environment variable.
        """
        admin_password = os.environ.get("NEBULA_ADMIN_PASSWORD")

        hashed_password = pwd_context.hash(admin_password)

        query = """
        INSERT INTO users ("user", password, role)
        VALUES ($1, $2, $3)
        ON CONFLICT ("user") DO NOTHING;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, "ADMIN", hashed_password, "admin")
                logging.info("Default admin user inserted (or already exists).")
        except Exception as e:
            logging.error(f"Failed to insert default admin user: {e}", exc_info=True)

    async def _list_users(self, all_info: bool = False):
        """
        Retrieves a list of users from the users database.
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetch("SELECT * FROM users")

        if all_info:
            # Return JSON-serializable dicts with full info
            return [dict(row) for row in result]
        else:
            # Return just the list of usernames (strings)
            return [row["user"] for row in result]


    async def _get_user_info(self, user: str):
        """
        Fetches detailed information for a specific user from the users database.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM users WHERE "user" = $1', user)


    async def _verify(self, user: str, password: str):
        """
        Verifies credentials and returns user info when valid.

        Returns
        -------
        dict | None
            {"user": USER, "role": ROLE} if valid, otherwise None.
        """
        user_up = user.upper()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT password, role FROM users WHERE "user" = $1', user_up)
        if not row:
            return None
        try:
            if pwd_context.verify(password, row["password"]):
                return {"user": user_up, "role": row["role"]}
        except Exception:
            logging.error(f"Error during password verification for user {user_up}", exc_info=True)
        return None


    async def _verify_hash_algorithm(self, user: str):
        """
        Checks if the stored password hash for a user uses a supported Argon2 algorithm.
        """
        user = user.upper()
        argon2_prefixes = ("$argon2i$", "$argon2id$")
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow('SELECT password FROM users WHERE "user" = $1', user)
        if result:
            password_hash = result["password"]
            return password_hash.startswith(argon2_prefixes)
        return False


    async def _delete_user_from_db(self, user: str):
        """
        Deletes a user record from the users database.
        """
        async with self.pool.acquire() as conn:
            await conn.execute('DELETE FROM users WHERE "user" = $1', user)


    async def _add_user(self, user:str, password:str, role:str):
        """
        Adds a new user to the users database with a hashed password.
        """
        hashed_password = pwd_context.hash(password)
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO users ("user", password, role) VALUES ($1, $2, $3)',
                user.upper(), hashed_password, role,
            )


    async def _update_user(self, user:str, password:str, role:str):
        """
        Updates the password and role of an existing user in the users database.
        """
        hashed_password = pwd_context.hash(password)
        async with self.pool.acquire() as conn:
            await conn.execute(
                'UPDATE users SET password = $1, role = $2 WHERE "user" = $3',
                hashed_password, role, user.upper(),
            )

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


    async def _list_nodes_by_federation_id(self, federation_id:str):
        """
        Fetches all nodes associated with a specific scenario, ordered by their index as integers.
        """
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
            logging.error(f"Error occurred while listing nodes by scenario name: {e}")
            return None


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
    ):
        """
        Inserts or updates a node record in the database for a given scenario, ensuring thread-safe access.
        """
        async with _node_lock:
            async with self.pool.acquire() as conn:
                try:
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
                                WHERE uid = $12 AND scenario = $13;
                                """,
                                idx, ip, port, role, neighbors,
                                timestamp, federation, federation_round, extras_payload, malicious_payload,
                                node_uid, federation_id,
                            )

                        updated_row = await conn.fetchrow("SELECT * from nodes WHERE uid = $1 AND scenario = $2;", node_uid, federation_id)
                        return dict(updated_row) if updated_row else None
                except asyncpg.PostgresError as e:
                    logging.error(f"Database error during node record update: {e}", exc_info=True)
                    return None


    async def _remove_all_nodes(self):
        """
        Deletes all node records from the nodes database.
        """
        async with self.pool.acquire() as conn:
            await conn.execute("TRUNCATE nodes CASCADE;") # Use CASCADE if there are foreign key dependencies


    async def _remove_nodes_by_federation_id(self, federation_id:str):
        """
        Deletes all nodes associated with a specific scenario from the database.
        """
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM nodes WHERE federation = $1;", federation_id)

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


    async def _get_all_scenarios(self, username:str, role:str, sort_by:str="start_time"):
        """
        Retrieves all scenarios from the database, accessing fields from the 'config' (JSONB) column
        and direct columns. Filters by user role and sorts by the specified field.
        """
        order_by_clause = self._build_order_by_clause(sort_by)

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
                params.append(username)

            full_command = f"{command} {order_by_clause};"
            return await conn.fetch(full_command, *params)


    async def _get_all_scenarios_and_check_completed(self, user:str, role:str, sort_by:str="start_time"):
        """
        Retrieves all scenarios, sorts them, and updates the status if necessary.
        Returns a list of dictionaries, where each dictionary represents a scenario.
        """
        # Safe list of allowed sorting fields to prevent SQL injection.
        order_by_clause = self._build_order_by_clause(sort_by)

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


    async def _scenario_update_record(self, federation_id:str, alias:str, scenario_name:str, start_time:datetime, end_time:datetime, scenario:dict, status:str, username:str):
        """
        Inserts or updates a scenario record using the PostgreSQL "UPSERT" pattern.
        All configuration is saved in the 'config' column of type JSONB.
        Direct columns (name, start_time, end_time, username, status) are also handled.
        """
        # Ensure scenario is a dictionary before dumping to JSON
        if not isinstance(scenario, dict):
            try:
                scenario = json.loads(scenario)
            except (json.JSONDecodeError, TypeError):
                logging.error("scenario is not a valid JSON string or dict.")
                return

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
        async with self.pool.acquire() as conn:
            await conn.execute(command, federation_id, alias, scenario_name, start_time, end_time, username, status, json.dumps(scenario))


    async def _scenario_set_all_status_to_finished(self):
        """
        Sets the status of all 'running' scenarios to 'finished'
        and updates their 'end_time' (both in the direct column and within JSONB).
        """
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
        async with self.pool.acquire() as conn:
            await conn.execute(command, current_time, json.dumps(current_time))


    async def _scenario_set_status_to_finished(self, federation_id:str):
        """
        Sets the status of a specific scenario to 'finished' and updates its 'end_time'.
        Updates both the direct columns and the JSONB 'config'.
        """
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
        async with self.pool.acquire() as conn:
            await conn.execute(command, current_time, json.dumps(current_time), federation_id)


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
        async with self.pool.acquire() as conn:
            await conn.execute(command, federation_id)


    async def _finish_scenario(self, federation_id: str, all: bool = False):
        """
        Consolidated method to set scenarios to finished.
        """
        if all:
            await self._scenario_set_all_status_to_finished()
        else:
            await self._scenario_set_status_to_finished(federation_id)


    async def _get_running_scenario(self, username:str=None, get_all:bool=False):
        """
        Retrieves scenarios with a 'running' status, optionally filtered by user.
        Returns full scenario record (including direct columns and config JSONB).
        """
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
        return result


    async def _get_completed_scenario(self):
        """
        Retrieves a single scenario with a 'completed' status.
        Returns full scenario record (including direct columns and config JSONB).
        """
        async with self.pool.acquire() as conn:
            command = "SELECT name, username, status, start_time, end_time, config FROM scenarios WHERE status = $1;"
            result_row = await conn.fetchrow(command, "completed")
            return dict(result_row) if result_row else None

    async def _get_scenarios(self, user: str, role: str):
        """
        Compose scenarios list and running scenario respecting role.
        """
        scenarios = await self._get_all_scenarios_and_check_completed(user=user, role=role)
        scenario_running = await self._get_running_scenario(None if role == "admin" else user)
        return {"scenarios": scenarios, "scenario_running": scenario_running}


    async def _get_scenario_by_federation_id(self, federation_id:str):
        """
        Retrieves the complete record of a scenario by its name.
        """
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

        return result


    async def _get_user_by_federation_id(self, federation_id:str):
        """
        Retrieves the username associated with a scenario (from the direct 'username' column).
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT username FROM scenarios WHERE federation_id = $1;", federation_id)


    async def _remove_scenario_by_federation_id(self, federation_id:str):
        """
        Delete a scenario from the database by its unique name.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM scenarios WHERE federation_id = $1;", federation_id)
            logging.info(f"Scenario '{federation_id}' successfully removed.")
        except asyncpg.PostgresError as e:
            logging.error(f"Error occurred while deleting scenario '{federation_id}': {e}")


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
                try:
                    total_rounds = int(scenario_rounds_str)
                except (ValueError, TypeError):
                    logging.error(f"Invalid 'rounds' value for scenario '{federation_id}': {scenario_rounds_str}")
                    return False

                # Fetch the current round progress of all nodes in that scenario
                nodes = await conn.fetch("SELECT round FROM nodes WHERE federation = $1;", federation_id)

                if not nodes:
                    logging.info(f"No nodes found for federation '{federation_id}'. Federation not considered completed.")
                    return False

                # Check if all nodes have completed the total rounds
                return all(int(node["round"]) >= total_rounds for node in nodes)

        except asyncpg.PostgresError as e:
            logging.error(f"PostgreSQL error during check_scenario_federation_completed for '{federation_id}': {e}")
            return False
        except ValueError as e:
            logging.error(f"Data error during check_scenario_federation_completed for '{federation_id}': {e}")
            return False


    async def _check_scenario_with_role(self, role:str, federation_id:str, user:str=None):
        """
        Verify if a scenario exists that the user with the given role and username can access.
        """
        scenario_info = await self._get_scenario_by_federation_id(federation_id)

        if not scenario_info:
            return False  # Scenario does not exist

        if role == "admin":
            return True  # Admins can access any existing scenario

        if user is None:
            logging.warning(
                "check_scenario_with_role called for non-admin role without user."
            )
            return False

        return scenario_info.get("username") == user

    # --- Notes Management Functions ---

    async def _save_notes(self, federation_id: str, notes: str):
        """
        Save or update notes associated with a specific scenario.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO notes (federation_id, scenario_notes) VALUES ($1, $2)
                    ON CONFLICT(federation_id) DO UPDATE SET scenario_notes = EXCLUDED.scenario_notes;
                    """,
                    federation_id, notes,
                )
        except asyncpg.PostgresError as e:
            logging.error(f"PostgreSQL error during save_notes: {e}")


    async def _get_notes(self, federation_id: str):
        """
        Retrieve notes associated with a specific scenario.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM notes WHERE federation_id = $1;", federation_id)
            if row is None:
                # No notes stored for this scenario yet
                return None
            return dict(row)


    async def _remove_note(self, federation_id: str):
        """
        Delete the note associated with a specific scenario.
        """
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM notes WHERE federation_id = $1;", federation_id)
