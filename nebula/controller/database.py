import asyncio
import datetime
import json
import logging
import os
import sqlite3

import aiosqlite
from argon2 import PasswordHasher

user_db_file_location = None
node_db_file_location = None
scenario_db_file_location = None
notes_db_file_location = None

_node_lock = asyncio.Lock()

PRAGMA_SETTINGS = [
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA journal_size_limit=1048576;",
    "PRAGMA cache_size=10000;",
    "PRAGMA temp_store=MEMORY;",
    "PRAGMA cache_spill=0;",
]


async def setup_database(db_file_location):
    """
    Initializes the SQLite database with the required PRAGMA settings.

    This function:
        - Connects asynchronously to the specified SQLite database file.
        - Applies a predefined list of PRAGMA settings to configure the database.
        - Commits the changes after applying the settings.

    Args:
        db_file_location (str): Path to the SQLite database file.

    Exceptions:
        PermissionError: Logged if the application lacks permission to create or modify the database file.
        Exception: Logs any other unexpected error that occurs during setup.
    """
    try:
        async with aiosqlite.connect(db_file_location) as db:
            for pragma in PRAGMA_SETTINGS:
                await db.execute(pragma)
            await db.commit()
    except PermissionError:
        logging.info("No permission to create the databases. Change the default databases directory")
    except Exception as e:
        logging.exception(f"An error has ocurred during setup_database: {e}")


async def ensure_columns(conn, table_name, desired_columns):
    """
    Ensures that a table contains all the desired columns, adding any that are missing.

    This function:
        - Retrieves the current columns of the specified table.
        - Compares them with the desired columns.
        - Adds any missing columns to the table using ALTER TABLE statements.

    Args:
        conn (aiosqlite.Connection): Active connection to the SQLite database.
        table_name (str): Name of the table to check and modify.
        desired_columns (dict): Dictionary mapping column names to their SQL definitions.

    Note:
        This operation is committed immediately after all changes are applied.
    """
    _c = await conn.execute(f"PRAGMA table_info({table_name});")
    existing_columns = [row[1] for row in await _c.fetchall()]
    for column_name, column_definition in desired_columns.items():
        if column_name not in existing_columns:
            await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition};")
    await conn.commit()


async def initialize_databases(databases_dir):
    """
    Initializes all required SQLite databases and their corresponding tables for the system.

    This function:
        - Defines paths for user, node, scenario, and notes databases based on the provided directory.
        - Sets up each database with appropriate PRAGMA settings.
        - Creates necessary tables if they do not exist.
        - Ensures all expected columns are present in each table, adding any missing ones.
        - Creates a default admin user if no users are present.

    Args:
        databases_dir (str): Path to the directory where the database files will be created or accessed.

    Note:
        Default credentials (username and password) are taken from environment variables:
        - NEBULA_DEFAULT_USER
        - NEBULA_DEFAULT_PASSWORD
    """
    global user_db_file_location, node_db_file_location, scenario_db_file_location, notes_db_file_location

    user_db_file_location = os.path.join(databases_dir, "users.db")
    node_db_file_location = os.path.join(databases_dir, "nodes.db")
    scenario_db_file_location = os.path.join(databases_dir, "scenarios.db")
    notes_db_file_location = os.path.join(databases_dir, "notes.db")

    await setup_database(user_db_file_location)
    await setup_database(node_db_file_location)
    await setup_database(scenario_db_file_location)
    await setup_database(notes_db_file_location)

    async with aiosqlite.connect(user_db_file_location) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user TEXT PRIMARY KEY,
                password TEXT,
                role TEXT
            );
            """
        )
        desired_columns = {"user": "TEXT PRIMARY KEY", "password": "TEXT", "role": "TEXT"}
        await ensure_columns(conn, "users", desired_columns)

    async with aiosqlite.connect(node_db_file_location) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                uid TEXT PRIMARY KEY,
                idx TEXT,
                ip TEXT,
                port TEXT,
                role TEXT,
                neighbors TEXT,
                latitude TEXT,
                longitude TEXT,
                timestamp TEXT,
                federation TEXT,
                round TEXT,
                scenario TEXT,
                hash TEXT,
                malicious TEXT
            );
            """
        )
        desired_columns = {
            "uid": "TEXT PRIMARY KEY",
            "idx": "TEXT",
            "ip": "TEXT",
            "port": "TEXT",
            "role": "TEXT",
            "neighbors": "TEXT",
            "latitude": "TEXT",
            "longitude": "TEXT",
            "timestamp": "TEXT",
            "federation": "TEXT",
            "round": "TEXT",
            "scenario": "TEXT",
            "hash": "TEXT",
            "malicious": "TEXT",
        }
        await ensure_columns(conn, "nodes", desired_columns)

    async with aiosqlite.connect(scenario_db_file_location) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scenarios (
                name TEXT PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                title TEXT,
                description TEXT,
                deployment TEXT,
                federation TEXT,
                topology TEXT,
                nodes TEXT,
                nodes_graph TEXT,
                n_nodes TEXT,
                matrix TEXT,
                random_topology_probability TEXT,
                dataset TEXT,
                iid TEXT,
                partition_selection TEXT,
                partition_parameter TEXT,
                model TEXT,
                agg_algorithm TEXT,
                rounds TEXT,
                logginglevel TEXT,
                report_status_data_queue TEXT,
                accelerator TEXT,
                network_subnet TEXT,
                network_gateway TEXT,
                epochs TEXT,
                attack_params TEXT,
                reputation TEXT,
                random_geo TEXT,
                latitude TEXT,
                longitude TEXT,
                mobility TEXT,
                mobility_type TEXT,
                radius_federation TEXT,
                scheme_mobility TEXT,
                round_frequency TEXT,
                mobile_participants_percent TEXT,
                additional_participants TEXT,
                schema_additional_participants TEXT,
                status TEXT,
                role TEXT,
                username TEXT,
                gpu_id TEXT
            );
            """
        )
        desired_columns = {
            "name": "TEXT PRIMARY KEY",
            "start_time": "TEXT",
            "end_time": "TEXT",
            "title": "TEXT",
            "description": "TEXT",
            "deployment": "TEXT",
            "federation": "TEXT",
            "topology": "TEXT",
            "nodes": "TEXT",
            "nodes_graph": "TEXT",
            "n_nodes": "TEXT",
            "matrix": "TEXT",
            "random_topology_probability": "TEXT",
            "dataset": "TEXT",
            "iid": "TEXT",
            "partition_selection": "TEXT",
            "partition_parameter": "TEXT",
            "model": "TEXT",
            "agg_algorithm": "TEXT",
            "rounds": "TEXT",
            "logginglevel": "TEXT",
            "report_status_data_queue": "TEXT",
            "accelerator": "TEXT",
            "gpu_id": "TEXT",
            "network_subnet": "TEXT",
            "network_gateway": "TEXT",
            "epochs": "TEXT",
            "attack_params": "TEXT",
            "reputation": "TEXT",
            "random_geo": "TEXT",
            "latitude": "TEXT",
            "longitude": "TEXT",
            "mobility": "TEXT",
            "mobility_type": "TEXT",
            "radius_federation": "TEXT",
            "scheme_mobility": "TEXT",
            "round_frequency": "TEXT",
            "mobile_participants_percent": "TEXT",
            "additional_participants": "TEXT",
            "schema_additional_participants": "TEXT",
            "status": "TEXT",
            "role": "TEXT",
            "username": "TEXT",
        }
        await ensure_columns(conn, "scenarios", desired_columns)

    async with aiosqlite.connect(notes_db_file_location) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                scenario TEXT PRIMARY KEY,
                scenario_notes TEXT
            );
            """
        )
        desired_columns = {"scenario": "TEXT PRIMARY KEY", "scenario_notes": "TEXT"}
        await ensure_columns(conn, "notes", desired_columns)

    username = os.environ.get("NEBULA_DEFAULT_USER", "admin")
    password = os.environ.get("NEBULA_DEFAULT_PASSWORD", "admin")
    if not list_users():
        add_user(username, password, "admin")
    if not verify_hash_algorithm(username):
        update_user(username, password, "admin")


def list_users(all_info=False):
    """
    Retrieves a list of users from the users database.

    Args:
        all_info (bool): If True, returns full user records; otherwise, returns only usernames. Default is False.

    Returns:
        list: A list of usernames or full user records depending on the all_info flag.
    """
    with sqlite3.connect(user_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        result = c.fetchall()

    if not all_info:
        result = [user["user"] for user in result]

    return result


def get_user_info(user):
    """
    Fetches detailed information for a specific user from the users database.

    Args:
        user (str): The username to retrieve information for.

    Returns:
        sqlite3.Row or None: A row containing the user's information if found, otherwise None.
    """
    with sqlite3.connect(user_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        command = "SELECT * FROM users WHERE user = ?"
        c.execute(command, (user,))
        result = c.fetchone()

    return result


def verify(user, password):
    """
    Verifies whether the provided password matches the stored hashed password for a user.

    Args:
        user (str): The username to verify.
        password (str): The plain text password to check against the stored hash.

    Returns:
        bool: True if the password is correct, False otherwise.
    """
    ph = PasswordHasher()
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()

        c.execute("SELECT password FROM users WHERE user = ?", (user,))
        result = c.fetchone()
        if result:
            try:
                return ph.verify(result[0], password)
            except:
                return False
    return False


def verify_hash_algorithm(user):
    """
    Checks if the stored password hash for a user uses a supported Argon2 algorithm.

    Args:
        user (str): The username to check (case-insensitive, converted to uppercase).

    Returns:
        bool: True if the password hash starts with a valid Argon2 prefix, False otherwise.
    """
    user = user.upper()
    argon2_prefixes = ("$argon2i$", "$argon2id$")

    with sqlite3.connect(user_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT password FROM users WHERE user = ?", (user,))
        result = c.fetchone()
        if result:
            password_hash = result["password"]
            return password_hash.startswith(argon2_prefixes)

    return False


def delete_user_from_db(user):
    """
    Deletes a user record from the users database.

    Args:
        user (str): The username of the user to be deleted.
    """
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user = ?", (user,))


def add_user(user, password, role):
    """
    Adds a new user to the users database with a hashed password.

    Args:
        user (str): The username to add (stored in uppercase).
        password (str): The plain text password to hash and store.
        role (str): The role assigned to the user.
    """
    ph = PasswordHasher()
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users VALUES (?, ?, ?)",
            (user.upper(), ph.hash(password), role),
        )


def update_user(user, password, role):
    """
    Updates the password and role of an existing user in the users database.

    Args:
        user (str): The username to update (case-insensitive, stored as uppercase).
        password (str): The new plain text password to hash and store.
        role (str): The new role to assign to the user.
    """
    ph = PasswordHasher()
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET password = ?, role = ? WHERE user = ?",
            (ph.hash(password), role, user.upper()),
        )


def list_nodes(scenario_name=None, sort_by="idx"):
    """
    Retrieves a list of nodes from the nodes database, optionally filtered by scenario and sorted.

    Args:
        scenario_name (str, optional): Name of the scenario to filter nodes by. If None, returns all nodes.
        sort_by (str): Column name to sort the results by. Defaults to "idx".

    Returns:
        list or None: A list of sqlite3.Row objects representing nodes, or None if an error occurs.
    """
    try:
        with sqlite3.connect(node_db_file_location) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            if scenario_name:
                command = "SELECT * FROM nodes WHERE scenario = ? ORDER BY " + sort_by + ";"
                c.execute(command, (scenario_name,))
            else:
                command = "SELECT * FROM nodes ORDER BY " + sort_by + ";"
                c.execute(command)

            result = c.fetchall()

            return result
    except sqlite3.Error as e:
        print(f"Error occurred while listing nodes: {e}")
        return None


def list_nodes_by_scenario_name(scenario_name):
    """
    Fetches all nodes associated with a specific scenario, ordered by their index as integers.

    Args:
        scenario_name (str): The name of the scenario to filter nodes by.

    Returns:
        list or None: A list of sqlite3.Row objects for nodes in the scenario, or None if an error occurs.
    """
    try:
        with sqlite3.connect(node_db_file_location) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            command = "SELECT * FROM nodes WHERE scenario = ? ORDER BY CAST(idx AS INTEGER) ASC;"
            c.execute(command, (scenario_name,))
            result = c.fetchall()

            return result
    except sqlite3.Error as e:
        print(f"Error occurred while listing nodes by scenario name: {e}")
        return None


async def update_node_record(
    node_uid,
    idx,
    ip,
    port,
    role,
    neighbors,
    latitude,
    longitude,
    timestamp,
    federation,
    federation_round,
    scenario,
    run_hash,
    malicious,
):
    """
    Inserts or updates a node record in the database for a given scenario, ensuring thread-safe access.

    Args:
        node_uid (str): Unique identifier of the node.
        idx (str): Index or identifier within the scenario.
        ip (str): IP address of the node.
        port (str): Port used by the node.
        role (str): Role of the node in the federation.
        neighbors (str): Neighbors of the node (serialized).
        latitude (str): Geographic latitude of the node.
        longitude (str): Geographic longitude of the node.
        timestamp (str): Timestamp of the last update.
        federation (str): Federation identifier the node belongs to.
        federation_round (str): Current federation round.
        scenario (str): Scenario name the node is part of.
        run_hash (str): Hash of the current run/state.
        malicious (str): Indicator if the node is malicious.

    Returns:
        dict or None: The updated or inserted node record as a dictionary, or None if insertion/update failed.
    """
    global _node_lock
    async with _node_lock:
        async with aiosqlite.connect(node_db_file_location) as conn:
            conn.row_factory = aiosqlite.Row
            _c = await conn.cursor()

            # Check if the node already exists
            await _c.execute("SELECT * FROM nodes WHERE uid = ? AND scenario = ?;", (node_uid, scenario))
            result = await _c.fetchone()

            if result is None:
                # Insert new node
                await _c.execute(
                    "INSERT INTO nodes (uid, idx, ip, port, role, neighbors, latitude, longitude, timestamp, federation, round, scenario, hash, malicious) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        node_uid,
                        idx,
                        ip,
                        port,
                        role,
                        neighbors,
                        latitude,
                        longitude,
                        timestamp,
                        federation,
                        federation_round,
                        scenario,
                        run_hash,
                        malicious,
                    ),
                )
            else:
                # Update existing node
                await _c.execute(
                    "UPDATE nodes SET idx = ?, ip = ?, port = ?, role = ?, neighbors = ?, latitude = ?, longitude = ?, timestamp = ?, federation = ?, round = ?, hash = ?, malicious = ? WHERE uid = ? AND scenario = ?;",
                    (
                        idx,
                        ip,
                        port,
                        role,
                        neighbors,
                        latitude,
                        longitude,
                        timestamp,
                        federation,
                        federation_round,
                        run_hash,
                        malicious,
                        node_uid,
                        scenario,
                    ),
                )

            await conn.commit()

            # Fetch the updated or newly inserted row
            await _c.execute("SELECT * FROM nodes WHERE uid = ? AND scenario = ?;", (node_uid, scenario))
            updated_row = await _c.fetchone()
            return dict(updated_row) if updated_row else None


def remove_all_nodes():
    """
    Deletes all node records from the nodes database.

    This operation removes every entry in the nodes table.

    Returns:
        None
    """
    with sqlite3.connect(node_db_file_location) as conn:
        c = conn.cursor()
        command = "DELETE FROM nodes;"
        c.execute(command)


def remove_nodes_by_scenario_name(scenario_name):
    """
    Deletes all nodes associated with a specific scenario from the database.

    Args:
        scenario_name (str): The name of the scenario whose nodes should be removed.

    Returns:
        None
    """
    with sqlite3.connect(node_db_file_location) as conn:
        c = conn.cursor()
        command = "DELETE FROM nodes WHERE scenario = ?;"
        c.execute(command, (scenario_name,))


def get_all_scenarios(username, role, sort_by="start_time"):
    """
    Retrieve all scenarios from the database filtered by user role and sorted by a specified field.

    Parameters:
        username (str): The username of the requesting user.
        role (str): The role of the user, e.g., "admin" or regular user.
        sort_by (str, optional): The field name to sort the results by. Defaults to "start_time".

    Returns:
        list[sqlite3.Row]: A list of scenario records as SQLite Row objects.

    Behavior:
        - Admin users retrieve all scenarios.
        - Non-admin users retrieve only scenarios associated with their username.
        - Sorting by "start_time" applies custom datetime ordering.
        - Other sort fields are applied directly in the ORDER BY clause.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if role == "admin":
            if sort_by == "start_time":
                command = """
                SELECT * FROM scenarios
                ORDER BY strftime('%Y-%m-%d %H:%M:%S', substr(start_time, 7, 4) || '-' || substr(start_time, 4, 2) || '-' || substr(start_time, 1, 2) || ' ' || substr(start_time, 12, 8));
                """
                c.execute(command)
            else:
                command = "SELECT * FROM scenarios ORDER BY ?;"
                c.execute(command, (sort_by,))
        else:
            if sort_by == "start_time":
                command = """
                SELECT * FROM scenarios
                WHERE username = ?
                ORDER BY strftime('%Y-%m-%d %H:%M:%S', substr(start_time, 7, 4) || '-' || substr(start_time, 4, 2) || '-' || substr(start_time, 1, 2) || ' ' || substr(start_time, 12, 8));
                """
                c.execute(command, (username,))
            else:
                command = "SELECT * FROM scenarios WHERE username = ? ORDER BY ?;"
                c.execute(
                    command,
                    (
                        username,
                        sort_by,
                    ),
                )
        result = c.fetchall()

    return result


def get_all_scenarios_and_check_completed(username, role, sort_by="start_time"):
    """
    Retrieve all scenarios with detailed fields and update the status of running scenarios if their federation is completed.

    Parameters:
        username (str): The username of the requesting user.
        role (str): The role of the user, e.g., "admin" or regular user.
        sort_by (str, optional): The field name to sort the results by. Defaults to "start_time".

    Returns:
        list[sqlite3.Row]: A list of scenario records including name, username, title, start_time, model, dataset, rounds, and status.

    Behavior:
        - Admin users retrieve all scenarios.
        - Non-admin users retrieve only scenarios associated with their username.
        - Scenarios are sorted by start_time with special handling for null or empty values.
        - For scenarios with status "running", checks if federation is completed:
            - If completed, updates the scenario status to "completed".
            - Refreshes the returned scenario list after updates.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if role == "admin":
            if sort_by == "start_time":
                command = """
                SELECT name, username, title, start_time, model, dataset, rounds, status FROM scenarios
                ORDER BY
                    CASE
                        WHEN start_time IS NULL OR start_time = '' THEN 1
                        ELSE 0
                    END,
                    strftime(
                        '%Y-%m-%d %H:%M:%S',
                        substr(start_time, 7, 4) || '-' || substr(start_time, 4, 2) || '-' || substr(start_time, 1, 2) || ' ' || substr(start_time, 12, 8)
                    );
                """
                c.execute(command)
            else:
                command = "SELECT name, username, title, start_time, model, dataset, rounds, status FROM scenarios ORDER BY ?;"
                c.execute(command, (sort_by,))
            result = c.fetchall()
        else:
            if sort_by == "start_time":
                command = """
                SELECT name, username, title, start_time, model, dataset, rounds, status FROM scenarios
                WHERE username = ?
                ORDER BY
                    CASE
                        WHEN start_time IS NULL OR start_time = '' THEN 1
                        ELSE 0
                    END,
                    strftime(
                        '%Y-%m-%d %H:%M:%S',
                        substr(start_time, 7, 4) || '-' || substr(start_time, 4, 2) || '-' || substr(start_time, 1, 2) || ' ' || substr(start_time, 12, 8)
                    );
                """
                c.execute(command, (username,))
            else:
                command = "SELECT name, username, title, start_time, model, dataset, rounds, status FROM scenarios WHERE username = ? ORDER BY ?;"
                c.execute(
                    command,
                    (
                        username,
                        sort_by,
                    ),
                )
            result = c.fetchall()

        for scenario in result:
            if scenario["status"] == "running":
                if check_scenario_federation_completed(scenario["name"]):
                    scenario_set_status_to_completed(scenario["name"])
                    result = get_all_scenarios(username, role)

    return result


def scenario_update_record(name, start_time, end_time, scenario, status, role, username):
    """
    Insert a new scenario record or update an existing one in the database based on the scenario name.

    Parameters:
        name (str): The unique name identifier of the scenario.
        start_time (str): The start time of the scenario.
        end_time (str): The end time of the scenario.
        scenario (object): An object containing detailed scenario attributes.
        status (str): The current status of the scenario.
        role (str): The role of the user performing the operation.
        username (str): The username of the user performing the operation.

    Behavior:
        - Checks if a scenario with the given name exists.
        - If not, inserts a new record with all scenario details.
        - If exists, updates the existing record with the provided data.
        - Commits the transaction to persist changes.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        select_command = "SELECT * FROM scenarios WHERE name = ?;"
        c.execute(select_command, (name,))
        result = c.fetchone()

        if result is None:
            insert_command = """
                INSERT INTO scenarios (
                    name,
                    start_time,
                    end_time,
                    title,
                    description,
                    deployment,
                    federation,
                    topology,
                    nodes,
                    nodes_graph,
                    n_nodes,
                    matrix,
                    random_topology_probability,
                    dataset,
                    iid,
                    partition_selection,
                    partition_parameter,
                    model,
                    agg_algorithm,
                    rounds,
                    logginglevel,
                    report_status_data_queue,
                    accelerator,
                    gpu_id,
                    network_subnet,
                    network_gateway,
                    epochs,
                    attack_params,
                    reputation,
                    random_geo,
                    latitude,
                    longitude,
                    mobility,
                    mobility_type,
                    radius_federation,
                    scheme_mobility,
                    round_frequency,
                    mobile_participants_percent,
                    additional_participants,
                    schema_additional_participants,
                    status,
                    role,
                    username
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                );
            """
            c.execute(
                insert_command,
                (
                    name,
                    start_time,
                    end_time,
                    scenario.scenario_title,
                    scenario.scenario_description,
                    scenario.deployment,
                    scenario.federation,
                    scenario.topology,
                    json.dumps(scenario.nodes),
                    json.dumps(scenario.nodes_graph),
                    scenario.n_nodes,
                    json.dumps(scenario.matrix),
                    scenario.random_topology_probability,
                    scenario.dataset,
                    scenario.iid,
                    scenario.partition_selection,
                    scenario.partition_parameter,
                    scenario.model,
                    scenario.agg_algorithm,
                    scenario.rounds,
                    scenario.logginglevel,
                    scenario.report_status_data_queue,
                    scenario.accelerator,
                    json.dumps(scenario.gpu_id),
                    scenario.network_subnet,
                    scenario.network_gateway,
                    scenario.epochs,
                    json.dumps(scenario.attack_params),
                    json.dumps(scenario.reputation),
                    scenario.random_geo,
                    scenario.latitude,
                    scenario.longitude,
                    scenario.mobility,
                    scenario.mobility_type,
                    scenario.radius_federation,
                    scenario.scheme_mobility,
                    scenario.round_frequency,
                    scenario.mobile_participants_percent,
                    json.dumps(scenario.additional_participants),
                    scenario.schema_additional_participants,
                    status,
                    role,
                    username,
                ),
            )
        else:
            update_command = """
                UPDATE scenarios SET
                    start_time = ?,
                    end_time = ?,
                    title = ?,
                    description = ?,
                    deployment = ?,
                    federation = ?,
                    topology = ?,
                    nodes = ?,
                    nodes_graph = ?,
                    n_nodes = ?,
                    matrix = ?,
                    random_topology_probability = ?,
                    dataset = ?,
                    iid = ?,
                    partition_selection = ?,
                    partition_parameter = ?,
                    model = ?,
                    agg_algorithm = ?,
                    rounds = ?,
                    logginglevel = ?,
                    report_status_data_queue = ?,
                    accelerator = ?,
                    gpu_id = ?,
                    network_subnet = ?,
                    network_gateway = ?,
                    epochs = ?,
                    attack_params = ?,
                    reputation = ?,
                    random_geo = ?,
                    latitude = ?,
                    longitude = ?,
                    mobility = ?,
                    mobility_type = ?,
                    radius_federation = ?,
                    scheme_mobility = ?,
                    round_frequency = ?,
                    mobile_participants_percent = ?,
                    additional_participants = ?,
                    schema_additional_participants = ?,
                    status = ?,
                    role = ?,
                    username = ?
                WHERE name = ?;
            """
            c.execute(
                update_command,
                (
                    start_time,
                    end_time,
                    scenario.scenario_title,
                    scenario.scenario_description,
                    scenario.deployment,
                    scenario.federation,
                    scenario.topology,
                    json.dumps(scenario.nodes),
                    json.dumps(scenario.nodes_graph),
                    scenario.n_nodes,
                    json.dumps(scenario.matrix),
                    scenario.random_topology_probability,
                    scenario.dataset,
                    scenario.iid,
                    scenario.partition_selection,
                    scenario.partition_parameter,
                    scenario.model,
                    scenario.agg_algorithm,
                    scenario.rounds,
                    scenario.logginglevel,
                    scenario.report_status_data_queue,
                    scenario.accelerator,
                    json.dumps(scenario.gpu_id),
                    scenario.network_subnet,
                    scenario.network_gateway,
                    scenario.epochs,
                    json.dumps(scenario.attack_params),
                    json.dumps(scenario.reputation),
                    scenario.random_geo,
                    scenario.latitude,
                    scenario.longitude,
                    scenario.mobility,
                    scenario.mobility_type,
                    scenario.radius_federation,
                    scenario.scheme_mobility,
                    scenario.round_frequency,
                    scenario.mobile_participants_percent,
                    json.dumps(scenario.additional_participants),
                    scenario.schema_additional_participants,
                    status,
                    role,
                    username,
                    name,
                ),
            )

        conn.commit()


def scenario_set_all_status_to_finished():
    """
    Set the status of all currently running scenarios to "finished" and update their end time to the current datetime.

    Behavior:
        - Finds all scenarios with status "running".
        - Updates their status to "finished".
        - Sets the end_time to the current timestamp.
        - Commits the changes to the database.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        current_time = str(datetime.datetime.now())
        c.execute("UPDATE scenarios SET status = 'finished', end_time = ? WHERE status = 'running';", (current_time,))
        conn.commit()


def scenario_set_status_to_finished(scenario_name):
    """
    Set the status of a specific scenario to "finished" and update its end time to the current datetime.

    Parameters:
        scenario_name (str): The unique name identifier of the scenario to update.

    Behavior:
        - Updates the scenario's status to "finished".
        - Sets the end_time to the current timestamp.
        - Commits the update to the database.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        current_time = str(datetime.datetime.now())
        c.execute(
            "UPDATE scenarios SET status = 'finished', end_time = ? WHERE name = ?;", (current_time, scenario_name)
        )
        conn.commit()


def scenario_set_status_to_completed(scenario_name):
    """
    Set the status of a specific scenario to "completed".

    Parameters:
        scenario_name (str): The unique name identifier of the scenario to update.

    Behavior:
        - Updates the scenario's status to "completed".
        - Commits the change to the database.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("UPDATE scenarios SET status = 'completed' WHERE name = ?;", (scenario_name,))
        conn.commit()


def get_running_scenario(username=None, get_all=False):
    """
    Retrieve running or completed scenarios from the database, optionally filtered by username.

    Parameters:
        username (str, optional): The username to filter scenarios by. If None, no user filter is applied.
        get_all (bool, optional): If True, returns all matching scenarios; otherwise returns only one. Defaults to False.

    Returns:
        sqlite3.Row or list[sqlite3.Row]: A single scenario record or a list of scenario records matching the criteria.

    Behavior:
        - Filters scenarios with status "running" or "completed".
        - Applies username filter if provided.
        - Returns either one or all matching records depending on get_all.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if username:
            command = """
                SELECT * FROM scenarios
                WHERE (status = ? OR status = ?) AND username = ?;
            """
            c.execute(command, ("running", "completed", username))

            result = c.fetchone()
        else:
            command = "SELECT * FROM scenarios WHERE status = ? OR status = ?;"
            c.execute(command, ("running", "completed"))
            if get_all:
                result = c.fetchall()
            else:
                result = c.fetchone()

    return result


def get_completed_scenario():
    """
    Retrieve a single scenario with status "completed" from the database.

    Returns:
        sqlite3.Row: A scenario record with status "completed", or None if no such scenario exists.

    Behavior:
        - Fetches the first scenario found with status "completed".
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        command = "SELECT * FROM scenarios WHERE status = ?;"
        c.execute(command, ("completed",))
        result = c.fetchone()

    return result


def get_scenario_by_name(scenario_name):
    """
    Retrieve a scenario record by its unique name.

    Parameters:
        scenario_name (str): The unique name identifier of the scenario.

    Returns:
        sqlite3.Row: The scenario record matching the given name, or None if not found.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM scenarios WHERE name = ?;", (scenario_name,))
        result = c.fetchone()

    return result


def get_user_by_scenario_name(scenario_name):
    """
    Retrieve the username associated with a given scenario name.

    Parameters:
        scenario_name (str): The unique name identifier of the scenario.

    Returns:
        str: The username linked to the specified scenario, or None if not found.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT username FROM scenarios WHERE name = ?;", (scenario_name,))
        result = c.fetchone()

    return result["username"]


def remove_scenario_by_name(scenario_name):
    """
    Delete a scenario from the database by its unique name.

    Parameters:
        scenario_name (str): The unique name identifier of the scenario to be removed.

    Behavior:
        - Removes the scenario record matching the given name.
        - Commits the deletion to the database.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("DELETE FROM scenarios WHERE name = ?;", (scenario_name,))
        conn.commit()


def check_scenario_federation_completed(scenario_name):
    """
    Check if all nodes in a given scenario have completed the required federation rounds.

    Parameters:
        scenario_name (str): The unique name identifier of the scenario to check.

    Returns:
        bool: True if all nodes have completed the total rounds specified for the scenario, False otherwise or if an error occurs.

    Behavior:
        - Retrieves the total number of rounds defined for the scenario.
        - Fetches the current round progress of all nodes in that scenario.
        - Returns True only if every node has reached the total rounds.
        - Handles database errors and missing scenario cases gracefully.
    """
    try:
        # Connect to the scenario database to get the total rounds for the scenario
        with sqlite3.connect(scenario_db_file_location) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT rounds FROM scenarios WHERE name = ?;", (scenario_name,))
            scenario = c.fetchone()

            if not scenario:
                raise ValueError(f"Scenario '{scenario_name}' not found.")

            total_rounds = scenario["rounds"]

        # Connect to the node database to check the rounds for each node
        with sqlite3.connect(node_db_file_location) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT round FROM nodes WHERE scenario = ?;", (scenario_name,))
            nodes = c.fetchall()

            if len(nodes) == 0:
                return False

            # Check if all nodes have completed the total rounds
            return all(node["round"] == total_rounds for node in nodes)

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False


def check_scenario_with_role(role, scenario_name):
    """
    Verify if a scenario exists with a specific role and name.

    Parameters:
        role (str): The role associated with the scenario (e.g., "admin", "user").
        scenario_name (str): The unique name identifier of the scenario.

    Returns:
        bool: True if a scenario with the given role and name exists, False otherwise.
    """
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM scenarios WHERE role = ? AND name = ?;",
            (
                role,
                scenario_name,
            ),
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
        - Handles SQLite integrity and general database errors gracefully.
    """
    try:
        with sqlite3.connect(notes_db_file_location) as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO notes (scenario, scenario_notes) VALUES (?, ?)
                ON CONFLICT(scenario) DO UPDATE SET scenario_notes = excluded.scenario_notes;
                """,
                (scenario, notes),
            )
            conn.commit()
    except sqlite3.IntegrityError as e:
        print(f"SQLite integrity error: {e}")
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")


def get_notes(scenario):
    """
    Retrieve notes associated with a specific scenario.
    
    Parameters:
        scenario (str): The unique identifier of the scenario.
    
    Returns:
        sqlite3.Row or None: The notes record for the given scenario, or None if no notes exist.
    """
    with sqlite3.connect(notes_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM notes WHERE scenario = ?;", (scenario,))
        result = c.fetchone()

    return result


def remove_note(scenario):
    """
    Delete the note associated with a specific scenario.

    Parameters:
        scenario (str): The unique identifier of the scenario whose note should be removed.
    """
    with sqlite3.connect(notes_db_file_location) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM notes WHERE scenario = ?;", (scenario,))
        conn.commit()


if __name__ == "__main__":
    """
    Entry point for the script to print the list of users.
    
    When executed directly, this block calls the `list_users()` function
    and prints its returned list of users.
    """
    print(list_users())
