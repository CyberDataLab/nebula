"""
docker_deployment.py – deployment strategy using Docker containers.
"""

from __future__ import annotations

import logging

from .deployment_interface import DeploymentInterface


class DockerDeployment(DeploymentInterface):
    """
    Implementation of DeploymentInterface for the *docker* mode.
    Reuses private helpers from ScenarioManagement.
    """

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start_blockchain(self) -> None:
        if self.sm.use_blockchain:
            self.sm._start_blockchain_impl()

    def start_nodes(self) -> None:
        self.sm._start_nodes_docker_impl()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop_nodes(self) -> None:
        """
        Stops and removes the scenario containers, deletes the
        ad-hoc network, and shuts down the blockchain if used.
        """
        logging.info("Stopping Docker nodes for scenario %s …", self.sm.scenario_name)

        # Clean up scripts/PIDs and stop blockchain if used
        self.sm.stop_participants(self.sm.scenario_name)
        if self.sm.use_blockchain:
            self.sm.stop_blockchain()
