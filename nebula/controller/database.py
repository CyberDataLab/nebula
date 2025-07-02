import logging
import os
import psycopg2
import psycopg2.extras
from passlib.context import CryptContext
import datetime
import json
import asyncpg
import asyncio

from nebula.controller.scenarios import Scenario

# --- Configuration ---
# Use environment variables for database credentials from the Docker Compose file
DATABASE_URL = f"postgresql://{os.environ.get('DB_USER')}:{os.environ.get('DB_PASSWORD')}@{os.environ.get('DB_HOST')}:{os.environ.get('DB_PORT')}/nebula"

# Password hashing context (using Argon2)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# Asynchronous lock for node updates
_node_lock = asyncio.Lock()


# --- Connection Management Helper Functions ---

def get_sync_conn():
    """Establishes a synchronous PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL)


async def get_async_conn():
    """Establishes an asynchronous PostgreSQL connection."""
    return await asyncpg.connect(DATABASE_URL)


# --- User Management Functions ---

def list_users(all_info=False):
    """
    Retrieves a list of users from the users database.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT * FROM users")
            result = c.fetchall()

    if not all_info:
        # In PostgreSQL, you can access columns by key from DictCursor
        result = [user["user"] for user in result]

    return result


def get_user_info(user):
    """
    Fetches detailed information for a specific user from the users database.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT * FROM users WHERE \"user\" = %s", (user,))
            result = c.fetchone()
    return result


def verify(user, password):
    """
    Verifies whether the provided password matches the stored hashed password for a user.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT password FROM users WHERE \"user\" = %s", (user,))
            result = c.fetchone()
            if result:
                try:
                    return pwd_context.verify(password, result[0])
                except:
                    return False
    return False


def verify_hash_algorithm(user):
    """
    Checks if the stored password hash for a user uses a supported Argon2 algorithm.
    """
    user = user.upper()
    argon2_prefixes = ("$argon2i$", "$argon2id$")
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT password FROM users WHERE \"user\" = %s", (user,))
            result = c.fetchone()
            if result:
                password_hash = result["password"]
                return password_hash.startswith(argon2_prefixes)
    return False


def delete_user_from_db(user):
    """
    Deletes a user record from the users database.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM users WHERE \"user\" = %s", (user,))
        conn.commit()


def add_user(user, password, role):
    """
    Adds a new user to the users database with a hashed password.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            hashed_password = pwd_context.hash(password)
            c.execute(
                "INSERT INTO users (\"user\", password, role) VALUES (%s, %s, %s)",
                (user.upper(), hashed_password, role),
            )
        conn.commit()


def update_user(user, password, role):
    """
    Updates the password and role of an existing user in the users database.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            hashed_password = pwd_context.hash(password)
            c.execute(
                "UPDATE users SET password = %s, role = %s WHERE \"user\" = %s",
                (hashed_password, role, user.upper()),
            )
        conn.commit()

# --- Node Management Functions ---

def list_nodes(scenario_name=None, sort_by="idx"):
    """
    Retrieves a list of nodes from the nodes database, optionally filtered by scenario and sorted.
    """
    try:
        with get_sync_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                if scenario_name:
                    command = f"SELECT * FROM nodes WHERE scenario = %s ORDER BY {psycopg2.extensions.AsIs(sort_by)};"
                    c.execute(command, (scenario_name,))
                else:
                    command = f"SELECT * FROM nodes ORDER BY {psycopg2.extensions.AsIs(sort_by)};"
                    c.execute(command)

                result = c.fetchall()
            return result
    except psycopg2.Error as e:
        print(f"Error occurred while listing nodes: {e}")
        return None


def list_nodes_by_scenario_name(scenario_name):
    """
    Fetches all nodes associated with a specific scenario, ordered by their index as integers.
    """
    try:
        with get_sync_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
                # Use a specific cast in PostgreSQL to order by integer value of idx
                command = "SELECT * FROM nodes WHERE scenario = %s ORDER BY CAST(idx AS INTEGER) ASC;"
                c.execute(command, (scenario_name,))
                result = c.fetchall()
            return result
    except psycopg2.Error as e:
        print(f"Error occurred while listing nodes by scenario name: {e}")
        return None


async def update_node_record(
    node_uid, idx, ip, port, role, neighbors, latitude, longitude,
    timestamp, federation, federation_round, scenario, run_hash, malicious,
):
    """
    Inserts or updates a node record in the database for a given scenario, ensuring thread-safe access.
    """
    async with _node_lock:
        # CORRECTED: Use get_async_conn() directly as the async context manager.
        # This assumes get_async_conn() returns a connection object that supports the
        # asynchronous context manager protocol (i.e., has __aenter__ and __aexit__).
        # A typical implementation of get_async_conn() using asyncpg would be 'return pool.acquire()'.
        async with get_async_conn() as conn: 
            # Use a connection-bound cursor
            async with conn.transaction():
                # Use a SELECT ... FOR UPDATE to lock the row and avoid race conditions
                result = await conn.fetchrow(
                    "SELECT * FROM nodes WHERE uid = $1 AND scenario = $2 FOR UPDATE;",
                    node_uid, scenario
                )

                if result is None:
                    # Insert new node
                    await conn.execute(
                        """
                        INSERT INTO nodes (uid, idx, ip, port, role, neighbors, latitude, longitude,
                                           timestamp, federation, round, scenario, hash, malicious)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14);
                        """,
                        node_uid, idx, ip, port, role, neighbors, latitude, longitude,
                        timestamp, federation, federation_round, scenario, run_hash, malicious,
                    )
                else:
                    # Update existing node
                    await conn.execute(
                        """
                        UPDATE nodes SET idx = $1, ip = $2, port = $3, role = $4, neighbors = $5,
                        latitude = $6, longitude = $7, timestamp = $8, federation = $9, round = $10,
                        hash = $11, malicious = $12
                        WHERE uid = $13 AND scenario = $14;
                        """,
                        idx, ip, port, role, neighbors, latitude, longitude,
                        timestamp, federation, federation_round, run_hash, malicious,
                        node_uid, scenario,
                    )
                
                # Fetch the updated or newly inserted row
                updated_row = await conn.fetchrow("SELECT * from nodes WHERE uid = $1 AND scenario = $2;", node_uid, scenario)
                return dict(updated_row) if updated_row else None


def remove_all_nodes():
    """
    Deletes all node records from the nodes database.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            c.execute("TRUNCATE nodes;") # TRUNCATE is faster than DELETE FROM for clearing tables
        conn.commit()


def remove_nodes_by_scenario_name(scenario_name):
    """
    Deletes all nodes associated with a specific scenario from the database.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM nodes WHERE scenario = %s;", (scenario_name,))
        conn.commit()

# --- Scenario Management Functions ---

def get_all_scenarios(username, role, sort_by="start_time"):
    """
    Retrieves all scenarios from the database, accessing the fields
    inside the 'config' (JSONB) column.
    Filters by user role and sorts by the specified field.
    """
    # Safe list of allowed sorting fields to prevent SQL injection
    allowed_sort_fields = ["start_time", "title", "username", "status", "name"]
    if sort_by not in allowed_sort_fields:
        sort_by = "start_time"  # Use a safe default value

    # Building the ORDER BY clause
    if sort_by == "start_time":
        # Special sorting for dates saved as text, handling nulls/empty strings
        order_by_clause = """
            ORDER BY
                CASE
                    WHEN start_time IS NULL OR start_time = '' THEN 1
                    ELSE 0
                END,
                to_timestamp(start_time, 'YYYY/MM/DD HH24:MI:SS') DESC
        """
    else:
        # Sorting is built dynamically but safely,
        # since 'sort_by' has been validated against the allowed list.
        order_by_clause = f"ORDER BY config->>'{sort_by}'"

    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            # Base query. It's flexible to return 'name' and the full 'config' object.
            # The code that calls this function can access any field from the config object.
            command = "SELECT name, username, start_time, end_time, status, config FROM scenarios"
            params = []

            # Conditionally add the WHERE filter if the role is not admin
            if role != "admin":
                command += " WHERE config->>'username' = %s"
                params.append(username)

            # Combine the query with the sorting clause
            full_command = f"{command} {order_by_clause};"

            c.execute(full_command, tuple(params))
            result = c.fetchall()
    
    return result


def get_all_scenarios_and_check_completed(username, role, sort_by="start_time"):
    """
    Retrieves all scenarios from the JSONB field, sorts them, and updates the status if necessary.
    Returns a list of dictionaries, where each dictionary represents a scenario.
    """
    # Safe list of allowed sorting fields to prevent SQL injection.
    allowed_sort_fields = ["start_time", "title", "username", "status", "name"]
    if sort_by not in allowed_sort_fields:
        sort_by = "start_time"  # Safe default value

    # Building the ORDER BY clause
    if sort_by == "start_time":
        order_by_clause = """
            ORDER BY
                CASE
                    WHEN start_time IS NULL OR start_time = '' THEN 1
                    ELSE 0
                END,
                to_timestamp(start_time, 'YYYY/MM/DD HH24:MI:SS') DESC
        """
    else:
        # We use a safe f-string because the value of sort_by has been validated
        order_by_clause = f"ORDER BY config->>'{sort_by}'"

    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            # Base query that extracts fields from the JSONB using the ->> operator
            command = f"""
                SELECT
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
                command += " WHERE config->>'username' = %s"
                params.append(username)

            command += f" {order_by_clause};"
            
            c.execute(command, tuple(params))
            result_dicts = c.fetchall() # This already returns a list of DictRow objects (which act like dicts)

            # Logic to check for completed scenarios and update status.
            # It's important to modify the `result_dicts` directly or handle the recursion carefully.
            
            # Create a mutable list from DictRow objects for potential status updates
            scenarios_to_return = [dict(s) for s in result_dicts]

            re_fetch_required = False
            for scenario in scenarios_to_return:
                if scenario["status"] == "running":
                    if check_scenario_federation_completed(scenario["name"]):
                        scenario_set_status_to_completed(scenario["name"])
                        # If a scenario's status changes, it's best to re-query the database
                        # to ensure the most up-to-date information is returned for ALL scenarios.
                        # This avoids inconsistencies if multiple scenarios complete in a single call.
                        re_fetch_required = True
                        break # Break after finding one completed scenario to trigger re-fetch

            if re_fetch_required:
                # If any status was updated, recursively call the function again to get the fresh data.
                # This ensures the returned list reflects the updated status from the DB.
                # Make sure `get_all_scenarios` is indeed this function if you rename it.
                return get_all_scenarios(username, role, sort_by) 
            
    return scenarios_to_return


def scenario_update_record(name, start_time, end_time, scenario, status, username):
    """
    Inserts or updates a scenario record using the PostgreSQL "UPSERT" pattern.
    All configuration is saved in the 'config' column of type JSONB.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            command = """
                INSERT INTO scenarios (name, start_time, end_time, username, status, config)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    config = scenarios.config || excluded.config;
            """
            logging.info(f"[FER] scenario database.py {json.dumps(scenario, indent=2)}")
            c.execute(command, (name, start_time, end_time, username, status, json.dumps(scenario, indent=2)))
            conn.commit()


def scenario_set_all_status_to_finished():
    """
    Sets the status of all 'running' scenarios to 'finished'
    and updates their 'end_time' within the JSONB.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            # We use jsonb_set to update specific fields within the JSONB.
            # We nest the calls to update multiple fields.
            command = """
                UPDATE scenarios
                SET status = 'finished', end_time = %s
                WHERE status = 'running';
            """
            c.execute(command, (json.dumps(current_time),))
            conn.commit()


def scenario_set_status_to_finished(scenario_name):
    """
    Sets the status of a specific scenario to 'finished' and updates its 'end_time'.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            command = """
                UPDATE scenarios
                SET config = jsonb_set(
                                 jsonb_set(config, '{status}', '"finished"'),
                                 '{end_time}', %s::jsonb
                               )
                WHERE name = %s;
            """
            c.execute(command, (json.dumps(current_time), scenario_name))
            conn.commit()


def scenario_set_status_to_completed(scenario_name):
    """
    Sets the status of a specific scenario to 'completed'.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            command = """
                UPDATE scenarios
                SET status = "completed"
                WHERE name = %s;
            """
            c.execute(command, (scenario_name,))
            conn.commit()


def get_running_scenario(username=None, get_all=False):
    """
    Retrieves scenarios with a 'running' status, optionally filtered by user.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            params = ["running"]
            command = "SELECT name, config FROM scenarios WHERE config->>'status' = %s"
            
            if username:
                command += " AND config->>'username' = %s"
                params.append(username)
                
            c.execute(command, tuple(params))
            
            if get_all: 
                raw_results = c.fetchall()
                if raw_results:
                    processed_results = []
                    for row in raw_results:
                        processed_results.append({
                            'name': row['name'],
                            'config': row['config']
                        })
                    result = processed_results
            else:
                result = c.fetchone()
                if result:
                    result = result['config']
    return result


def get_completed_scenario():
    """
    Retrieves a single scenario with a 'completed' status.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            command = "SELECT name, config FROM scenarios WHERE config->>'status' = %s;"
            c.execute(command, ("completed",))
            result = c.fetchone()
    return result


def get_scenario_by_name(scenario_name):
    """
    Retrieves the complete record of a scenario by its name.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT name, start_time, end_time, username, status, config FROM scenarios WHERE name = %s;", (scenario_name,))
            result = c.fetchone()
    return result


def get_user_by_scenario_name(scenario_name):
    """
    Retrieves the username associated with a scenario from the JSONB field.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT username FROM scenarios WHERE name = %s;", (scenario_name,))
            result = c.fetchone()
    return result["username"] if result else None

# Placeholder for `check_scenario_federation_completed`.
# You need to implement this based on your application logic.
def check_scenario_federation_completed(scenario_name):
    """
    Placeholder function to check if a scenario's federation is completed.
    This should be implemented based on your specific application logic.
    For example, it could check if the last round has been reached.
    """
    print(f"Checking if scenario '{scenario_name}' is completed...")
    # Example logic:
    # return get_current_round(scenario_name) >= get_total_rounds(scenario_name)
    return False # Placeholder value

def check_scenario_with_role(role, scenario_name):
    """
    Verify if a scenario exists with a specific role and name.

    Parameters:
        role (str): The role associated with the scenario (e.g., "admin", "user").
        scenario_name (str): The unique name identifier of the scenario.

    Returns:
        bool: True if a scenario with the given role and name exists, False otherwise.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            # Use %s placeholders for query parameters
            c.execute(
                "SELECT 1 FROM scenarios WHERE role = %s AND name = %s;",
                (role, scenario_name),
            )
            result = c.fetchone()

    return result is not None

def save_notes(scenario, notes):
    """
    Save or update notes associated with a specific scenario.

    Parameters:
        scenario (str): The unique identifier of the scenario.
        notes (str): The textual notes to be saved for the scenario.

    Behavior:
        - Inserts new notes if the scenario does not exist in the database.
        - Updates existing notes if the scenario already has notes saved.
        - Handles database errors gracefully.
    """
    try:
        with get_sync_conn() as conn:
            with conn.cursor() as c:
                # Use INSERT ... ON CONFLICT (UPSERT)
                c.execute(
                    """
                    INSERT INTO notes (scenario, scenario_notes) VALUES (%s, %s)
                    ON CONFLICT(scenario) DO UPDATE SET scenario_notes = EXCLUDED.scenario_notes;
                    """,
                    (scenario, notes),
                )
            conn.commit()
    except psycopg2.IntegrityError as e:
        print(f"PostgreSQL integrity error: {e}")
    except psycopg2.Error as e:
        print(f"PostgreSQL error: {e}")

def get_notes(scenario):
    """
    Retrieve notes associated with a specific scenario.

    Parameters:
        scenario (str): The unique identifier of the scenario.

    Returns:
        psycopg2.extras.DictRow or None: The notes record for the given scenario, or None if no notes exist.
    """
    with get_sync_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("SELECT * FROM notes WHERE scenario = %s;", (scenario,))
            result = c.fetchone()
    return result

def remove_note(scenario):
    """
    Delete the note associated with a specific scenario.

    Parameters:
        scenario (str): The unique identifier of the scenario whose note should be removed.
    """
    with get_sync_conn() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM notes WHERE scenario = %s;", (scenario,))
        conn.commit()

if __name__ == "__main__":
    """
    Entry point for the script to print the list of users.
    """
    print(list_users())