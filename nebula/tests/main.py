import json
import logging
import os
import sys
from datetime import datetime

import docker

# Constants
TIMEOUT = 3600


# Detect CTRL+C from parent process
def signal_handler(signal, frame):
    logging.info("You pressed Ctrl+C [test]!")
    sys.exit(0)


# Create nebula netbase if it does not exist
def create_docker_network():
    client = docker.from_env()

    try:
        ipam_pool = docker.types.IPAMPool(subnet="192.168.10.0/24", gateway="192.168.10.1")
        ipam_config = docker.types.IPAMConfig(pool_configs=[ipam_pool])

        client.networks.create("nebula-net-base", driver="bridge", ipam=ipam_config)
        print("Docker network created successfully.")
    except docker.errors.APIError as e:
        print(f"Error creating Docker network: {e}")


# To add a new test create the option in the menu and a [test].json file in tests folder
def menu():
    # clear terminal
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

    banner = """
███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
  A Platform for Decentralized Federated Learning
    Created by Enrique Tomás Martínez Beltrán
      https://github.com/CyberDataLab/nebula
                """
    print("\x1b[0;36m" + banner + "\x1b[0m")

    options = """
[1] Aggregation test
[2] Topology test
[3] Dataset test
[4] Attacks test
[5] Custom test
CTRL + C to exit
                """

    while True:
        print("\x1b[0;36m" + options + "\x1b[0m")
        selectedOption = input("\x1b[0;36m" + "> " + "\x1b[0m")
        if selectedOption == "1":
            run_test(os.path.join(os.path.dirname(__file__), "aggregation.json"))
        elif selectedOption == "2":
            run_test(os.path.join(os.path.dirname(__file__), "topology.json"))
        elif selectedOption == "3":
            run_test(os.path.join(os.path.dirname(__file__), "datasets.json"))
        elif selectedOption == "4":
            run_test(os.path.join(os.path.dirname(__file__), "attacks.json"))
        elif selectedOption == "5":
            run_test(os.path.join(os.path.dirname(__file__), "custom.json"))
        else:
            print("Choose a valid option")


# Check for error logs
def check_error_logs(test_name, scenario_name):
    try:
        log_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app", "logs"))
        current_log = os.path.join(log_dir, scenario_name)
        test_dir = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app", "tests")
        )
        output_log_path = os.path.join(test_dir, test_name + ".log")

        if not os.path.exists(test_dir):
            try:
                os.mkdir(test_dir)
            except Exception as e:
                logging.exception(f"Error creating test directory: {e}")

        with open(output_log_path, "a", encoding="utf-8") as f:
            f.write(f"Scenario: {scenario_name}\n")

            for log_file in os.listdir(current_log):
                if log_file.endswith("_error.log"):
                    log_file_path = os.path.join(current_log, log_file)
                    try:
                        with open(log_file_path, encoding="utf-8") as file:
                            content = file.read().strip()
                            if content:
                                f.write(f"{log_file} ❌ Errors found:\n{content}\n")
                            else:
                                f.write(f"{log_file} ✅ No errors found\n")
                    except Exception as e:
                        f.write(f"Error reading {log_file}: {e}\n")

            f.write("-" * os.get_terminal_size().columns + "\n")

    except Exception as e:
        print(f"Failed to write to log file {test_name + '.log'}: {e}")

    return output_log_path


# Load test from .json file
def load_test(test_path):
    with open(test_path, encoding="utf-8") as file:
        scenarios = json.load(file)
    return scenarios


# Run selected test
def run_test(test_path):
    test_name = f"test_nebula_{os.path.splitext(os.path.basename(test_path))[0]}_" + datetime.now().strftime(
        "%d_%m_%Y_%H_%M_%S"
    )

    for scenario in load_test(test_path):
        scenarioManagement = run_scenario(scenario)
        finished = scenarioManagement.scenario_finished(TIMEOUT)

        if finished:
            test_log_path = check_error_logs(test_name, scenarioManagement.scenario_name)
        else:
            test_dir = os.path.normpath(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..",
                    "..",
                    "app",
                    "tests",
                )
            )
            output_log_path = os.path.join(test_dir, test_name + ".log")

            if not os.path.exists(test_dir):
                try:
                    os.mkdir(test_dir)
                except Exception as e:
                    logging.exception(f"Error creating test directory: {e}")

            try:
                with open(output_log_path, "a", encoding="utf-8") as f:
                    f.write(f"Scenario: {scenarioManagement.scenario_name} \n")
                    f.write("🕒❌ Timeout reached \n")
                    f.write("-" * os.get_terminal_size().columns + "\n")
            except Exception as e:
                print(f"Failed to write to log file {test_name + '.log'}: {e}")
            pass

    print("Results:")
    try:
        with open(test_log_path, encoding="utf-8") as f:
            print(f.read())
    except Exception as e:
        print(f"Failed to read the log file {test_name + '.log'}: {e}")


# Run a single scenario
def run_scenario(scenario):
    import subprocess

    from nebula.scenarios import ScenarioManagement

    # Manager for the actual scenario
    scenarioManagement = ScenarioManagement(scenario, "nebula-test")

    # Run the actual scenario
    try:
        if scenarioManagement.scenario.mobility:
            additional_participants = scenario["additional_participants"]
            schema_additional_participants = scenario["schema_additional_participants"]
            scenarioManagement.load_configurations_and_start_nodes(
                additional_participants, schema_additional_participants
            )
        else:
            scenarioManagement.load_configurations_and_start_nodes()
    except subprocess.CalledProcessError as e:
        logging.exception(f"Error docker-compose up: {e}")

    return scenarioManagement


if __name__ == "__main__":
    create_docker_network()
    menu()
