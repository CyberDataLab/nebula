"""
process_deployment.py – deployment strategy using **local processes**.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .deployment_interface import DeploymentInterface


class ProcessDeployment(DeploymentInterface):
    """
    Implementation of DeploymentInterface for the *process* mode.
    Reuses private helpers from ScenarioManagement.
    """

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start_blockchain(self) -> None:
        if self.sm.use_blockchain:
            self.sm._start_blockchain_impl()

    def start_nodes(self) -> None:
        self.sm._start_nodes_process_impl()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop_nodes(self) -> None:
        """
        • Removes auxiliary scripts.  
        • Stops the blockchain if applicable.
        """
        logging.info("Stopping process-based nodes for scenario %s …", self.sm.scenario_name)

        # Remove scripts and other artifacts
        self.sm.stop_participants(self.sm.scenario_name)

        # If BlockchainReputation was used, stop its containers too
        if self.sm.use_blockchain:
            self.sm.stop_blockchain()
