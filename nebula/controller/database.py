import asyncio
import datetime
import json
import logging
import os
import sqlite3

import aiosqlite
from argon2 import PasswordHasher

user_db_file_location = "users.db"
node_db_file_location = "nodes.db"
scenario_db_file_location = "scenarios.db"
notes_db_file_location = "notes.db"

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
    _c = await conn.execute(f"PRAGMA table_info({table_name});")
    existing_columns = [row[1] for row in await _c.fetchall()]
    for column_name, column_definition in desired_columns.items():
        if column_name not in existing_columns:
            await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition};")
    await conn.commit()


async def initialize_databases(databases_dir):
    global user_db_file_location, node_db_file_location, scenario_db_file_location, notes_db_file_location
    
    user_db_file_location = os.path.join(databases_dir, user_db_file_location)
    node_db_file_location = os.path.join(databases_dir, node_db_file_location)
    scenario_db_file_location = os.path.join(databases_dir, scenario_db_file_location)
    notes_db_file_location = os.path.join(databases_dir, notes_db_file_location)

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
                attacks TEXT,
                poisoned_node_percent TEXT,
                poisoned_sample_percent TEXT,
                poisoned_noise_percent TEXT,
                attack_params TEXT,
                with_reputation TEXT,
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
            "attacks": "TEXT",
            "poisoned_node_percent": "TEXT",
            "poisoned_sample_percent": "TEXT",
            "poisoned_noise_percent": "TEXT",
            "attack_params": "TEXT",
            "with_reputation": "TEXT",
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
            "username": "TEXT"
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
    with sqlite3.connect(user_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        result = c.fetchall()

    if not all_info:
        result = [user["user"] for user in result]

    return result


def get_user_info(user):
    with sqlite3.connect(user_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        command = "SELECT * FROM users WHERE user = ?"
        c.execute(command, (user,))
        result = c.fetchone()

    return result


def verify(user, password):
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
    user = user.upper()
    argon2_prefixes = ("$argon2i$", "$argon2id$")

    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()

        c.execute("SELECT password FROM users WHERE user = ?", (user,))
        result = c.fetchone()
        if result:
            password_hash = result[0]
            return password_hash.startswith(argon2_prefixes)

    return False


def delete_user_from_db(user):
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user = ?", (user,))


def add_user(user, password, role):
    ph = PasswordHasher()
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users VALUES (?, ?, ?)",
            (user.upper(), ph.hash(password), role),
        )


def update_user(user, password, role):
    ph = PasswordHasher()
    with sqlite3.connect(user_db_file_location) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET password = ?, role = ? WHERE user = ?",
            (ph.hash(password), role, user.upper()),
        )


def list_nodes(scenario_name=None, sort_by="idx"):
    # list all nodes in the database
    try:
        with sqlite3.connect(node_db_file_location) as conn:
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
    try:
        with sqlite3.connect(node_db_file_location) as conn:
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
    # Check if the node record with node_uid and scenario already exists in the database
    # If it does, update the record
    # If it does not, create a new record
    # _conn = sqlite3.connect(node_db_file_location)
    global _node_lock
    async with _node_lock:
        async with aiosqlite.connect(node_db_file_location) as conn:
            _c = await conn.cursor()

            command = "SELECT * FROM nodes WHERE uid = ? AND scenario = ?;"
            await _c.execute(command, (node_uid, scenario))
            result = await _c.fetchone()

            if result is None:
                # Create a new record
                await _c.execute(
                    "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                # Update the record
                command = "UPDATE nodes SET idx = ?, ip = ?, port = ?, role = ?, neighbors = ?, latitude = ?, longitude = ?, timestamp = ?, federation = ?, round = ?, hash = ?, malicious = ? WHERE uid = ? AND scenario = ?;"
                await _c.execute(
                    command,
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


def remove_all_nodes():
    with sqlite3.connect(node_db_file_location) as conn:
        c = conn.cursor()
        command = "DELETE FROM nodes;"
        c.execute(command)


def remove_nodes_by_scenario_name(scenario_name):
    with sqlite3.connect(node_db_file_location) as conn:
        c = conn.cursor()
        command = "DELETE FROM nodes WHERE scenario = ?;"
        c.execute(command, (scenario_name,))


def get_run_hashes_scenario(scenario_name):
    with sqlite3.connect(node_db_file_location) as conn:
        c = conn.cursor()
        command = "SELECT DISTINCT idx, hash FROM nodes WHERE scenario = ?;"
        c.execute(command, (scenario_name,))
        result = c.fetchall()
        result_hashes = [(f"participant_{node[0]}", node[1]) for node in result]

        return result_hashes


def get_all_scenarios(username, role, sort_by="start_time"):
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
    with sqlite3.connect(scenario_db_file_location) as _conn:
        _conn.row_factory = sqlite3.Row
        _c = _conn.cursor()

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
                _c.execute(command)
            else:
                command = "SELECT name, username, title, start_time, model, dataset, rounds, status FROM scenarios ORDER BY ?;"
                _c.execute(command, (sort_by,))
            # _c.execute(command)
            result = _c.fetchall()
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
                _c.execute(command, (username,))
            else:
                command = "SELECT name, username, title, start_time, model, dataset, rounds, status FROM scenarios WHERE username = ? ORDER BY ?;"
                _c.execute(
                    command,
                    (
                        username,
                        sort_by,
                    ),
                )
            # _c.execute(command)
            result = _c.fetchall()

        for scenario in result:
            if scenario["status"] == "running":
                if check_scenario_federation_completed(scenario["name"]):
                    scenario_set_status_to_completed(scenario["name"])
                    result = get_all_scenarios(username, role)

    return result


def scenario_update_record(
    name,
    start_time,
    end_time,
    scenario,
    status,
    role,
    username
):
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()

    select_command = "SELECT * FROM scenarios WHERE name = ?;"
    _c.execute(select_command, (name,))
    result = _c.fetchone()

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
                attacks,
                poisoned_node_percent,
                poisoned_sample_percent,
                poisoned_noise_percent,
                attack_params,
                with_reputation,
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
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            );
        """
        _c.execute(insert_command, (
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
            json.dumps(scenario.attacks),
            scenario.poisoned_node_percent,
            scenario.poisoned_sample_percent,
            scenario.poisoned_noise_percent,
            json.dumps(scenario.attack_params),
            scenario.with_reputation,
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
            username
        ))
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
                attacks = ?,
                poisoned_node_percent = ?,
                poisoned_sample_percent = ?,
                poisoned_noise_percent = ?,
                attack_params = ?,
                with_reputation = ?,
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
        _c.execute(update_command, (
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
            json.dumps(scenario.attacks),
            scenario.poisoned_node_percent,
            scenario.poisoned_sample_percent,
            scenario.poisoned_noise_percent,
            json.dumps(scenario.attack_params),
            scenario.with_reputation,
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
            name
        ))
    
    _conn.commit()
    _conn.close()


def scenario_set_all_status_to_finished():
    # Set all running scenarios to finished and update the end_time to the current time
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()

    command = "UPDATE scenarios SET status = 'finished', end_time = ? WHERE status = 'running';"
    current_time = str(datetime.datetime.now())
    _c.execute(command, (current_time,))

    _conn.commit()
    _conn.close()


def scenario_set_status_to_finished(scenario_name):
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()

    command = "UPDATE scenarios SET status = 'finished', end_time = ? WHERE name = ?;"
    current_time = str(datetime.datetime.now())
    _c.execute(command, (current_time, scenario_name))

    _conn.commit()
    _conn.close()


def scenario_set_status_to_completed(scenario_name):
    try:
        with sqlite3.connect(scenario_db_file_location) as _conn:
            _c = _conn.cursor()
            command = "UPDATE scenarios SET status = 'completed' WHERE name = ?;"
            _c.execute(command, (scenario_name,))
            _conn.commit()
            _conn.close()
    except sqlite3.Error as e:
        print(f"Database error: {e}")


def get_running_scenario(username=None, get_all=False):
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
    with sqlite3.connect(scenario_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        command = "SELECT * FROM scenarios WHERE status = ?;"
        c.execute(command, ("completed",))
        result = c.fetchone()

    return result


def get_scenario_by_name(scenario_name):
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()
    command = "SELECT * FROM scenarios WHERE name = ?;"
    _c.execute(command, (scenario_name,))
    result = _c.fetchone()

    _conn.commit()
    _conn.close()

    return result


def get_user_by_scenario_name(scenario_name):
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()
    command = "SELECT username FROM scenarios WHERE name = ?;"
    _c.execute(command, (scenario_name,))
    result = _c.fetchone()

    _conn.commit()
    _conn.close()

    return result[0] if result else None


def remove_scenario_by_name(scenario_name):
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()

    command = "DELETE FROM scenarios WHERE name = ?;"
    _c.execute(command, (scenario_name,))

    _conn.commit()
    _conn.close()


def check_scenario_federation_completed(scenario_name):
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
    _conn = sqlite3.connect(scenario_db_file_location)
    _c = _conn.cursor()
    command = "SELECT * FROM scenarios WHERE role = ? AND name = ?;"
    _c.execute(command, (role, scenario_name))
    result = _c.fetchone()

    _conn.commit()
    _conn.close()

    return result


def save_notes(scenario, notes):
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
    with sqlite3.connect(notes_db_file_location) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM notes WHERE scenario = ?;", (scenario,))
        result = c.fetchone()

    return result


def remove_note(scenario):
    with sqlite3.connect(notes_db_file_location) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM notes WHERE scenario = ?;", (scenario,))
        conn.commit()


if __name__ == "__main__":
    print(list_users())
