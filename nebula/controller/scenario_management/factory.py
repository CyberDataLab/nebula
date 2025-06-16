"""
factory.py – returns the appropriate deployment strategy (class)
based on the mode indicated in ScenarioManagement.

* Add each new strategy we create here (Physical…).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .deployment_interface import DeploymentInterface
from .docker_deployment import DockerDeployment
from .physical_deployment import PhysicalDeployment
from .process_deployment import ProcessDeployment

if TYPE_CHECKING:
    from ..scenarios import ScenarioManagement


def get_deployment(sm: ScenarioManagement) -> DeploymentInterface:
    """
    Decides and instantiates the appropriate deployment class.

    Parameters
    ----------
    sm : ScenarioManagement
        The "orchestrator" instance that contains the scenario.

    Returns
    -------
    DeploymentInterface
        Object implementing start_blockchain(), start_nodes(), and stop_nodes()
        according to the selected mode.
    """
    mode = sm.scenario.deployment.lower()

    if mode == "docker":
        return DockerDeployment(sm)

    if mode == "process":
        return ProcessDeployment(sm)

    if mode == "physical":
        return PhysicalDeployment(sm)

    raise ValueError(
        f"Deployment '{sm.scenario.deployment}' not supported yet. Add it in controller/scenario_management/factory.py"
    )
