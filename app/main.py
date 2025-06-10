import argparse
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))  # Parent directory where is the NEBULA module
import nebula
from app.deployer import Deployer
from nebula.controller.scenarios import ScenarioManagement

argparser = argparse.ArgumentParser(description="Controller of NEBULA platform", add_help=False)

argparser.add_argument(
    "-cp",
    "--controllerport",
    dest="controllerport",
    default=5050,
    help="Controller port (default: 5050)",
)

argparser.add_argument(
    "--grafanaport",
    dest="grafanaport",
    default=6040,
    help="Grafana port (default: 6040)",
)

argparser.add_argument(
    "--lokiport",
    dest="lokiport",
    default=6010,
    help="Loki port (default: 6010)",
)

argparser.add_argument(
    "--wafport",
    dest="wafport",
    default=6050,
    help="WAF port (default: 6050)",
)

argparser.add_argument(
    "-wp",
    "--webport",
    dest="webport",
    default=6060,
    help="Frontend port (default: 6060)",
)

argparser.add_argument(
    "-sp",
    "--statsport",
    dest="statsport",
    default=8080,
    help="Statistics port (default: 8080)",
)

argparser.add_argument(
    "-st",
    "--stop",
    dest="stop",
    nargs="?",
    const="all",  # If no argument is given, stop all
    default=None,
    help="Stop NEBULA platform or nodes only (use '--stop nodes' to stop only the nodes)",
)

argparser.add_argument("-s", "--simulation", action="store_false", dest="simulation", help="Run simulation")

argparser.add_argument(
    "-c",
    "--config",
    dest="config",
    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config"),
    help="Config directory path",
)

argparser.add_argument(
    "-d",
    "--database",
    dest="databases",
    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "databases"),
    help="Nebula databases path",
)

argparser.add_argument(
    "-l",
    "--logs",
    dest="logs",
    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
    help="Logs directory path",
)

argparser.add_argument(
    "-ce",
    "--certs",
    dest="certs",
    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs"),
    help="Certs directory path",
)

argparser.add_argument(
    "-e",
    "--env",
    dest="env",
    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    help=".env file path",
)

argparser.add_argument("-dev", "--developement", dest="developement", default=True, help="Nebula for devs")

argparser.add_argument(
    "-p",
    "--production",
    dest="production",
    action="store_true",
    default=False,
    help="Production mode",
)

argparser.add_argument(
    "-ad",
    "--advanced",
    dest="advanced_analytics",
    action="store_true",
    default=False,
    help="Advanced analytics",
)

argparser.add_argument(
    "-v",
    "--version",
    action="version",
    version="%(prog)s " + nebula.__version__,
    help="Show version",
)

argparser.add_argument(
    "-a",
    "--about",
    action="version",
    version="Created by Enrique Tomás Martínez Beltrán",
    help="Show author",
)

argparser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="Show help")

args = argparser.parse_args()

"""
Code for deploying the controller
"""
if __name__ == "__main__":
    if args.stop == "all":
        Deployer.stop_all()
    elif args.stop == "nodes":
        ScenarioManagement.stop_nodes()

    Deployer(args).start()
