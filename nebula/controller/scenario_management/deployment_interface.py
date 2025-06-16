"""
deployment_interface.py – contract that all deployment strategies
(Docker, Process, …) must comply with.

Each new strategy must inherit from DeploymentInterface
and override the abstract methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..scenarios import ScenarioManagement


class DeploymentInterface(ABC):
    """
    High-level interface for the deployment layer.

    All methods receive or use `self.sm`, which is the instance
    of ScenarioManagement they are "plugged into".
    """

    def __init__(self, scenario_mgmt: ScenarioManagement):
        # store a reference to access data and helpers
        self.sm = scenario_mgmt

    # ------------------------------------------------------------------
    # These three methods **vary** depending on the specific strategy
    # ------------------------------------------------------------------

    @abstractmethod
    def start_blockchain(self) -> None:
        """
        Launches the Blockchain infrastructure (if applicable).

        • DockerDeployment: creates and starts the blockchain containers.
        • ProcessDeployment: usually calls the same private helper.
        """
        pass

    @abstractmethod
    def start_nodes(self) -> None:
        """
        Starts the participating nodes according to the selected mode
        (Docker containers, local processes, etc.).
        """
        pass

    @abstractmethod
    def stop_nodes(self) -> None:
        """
        Stops all nodes and cleans up any temporary resources
        (containers, processes, PID files…).
        It must not call `self.sm.stop_nodes()` again to avoid recursion.
        """
        pass
