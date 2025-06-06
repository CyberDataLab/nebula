from abc import ABC, abstractmethod


class NeighborPolicy(ABC):
    @abstractmethod
    async def set_config(self, config):
        """Set internal configuration parameters for the neighbor policy, typically from a shared configuration object."""
        pass

    @abstractmethod
    async def need_more_neighbors(self):
        """Return True if the current node requires additional neighbors to fulfill its connectivity policy."""
        pass

    @abstractmethod
    async def get_posible_neighbors(self):
        """Return set of posible neighbors to connect to."""
        pass

    @abstractmethod
    async def any_leftovers_neighbors(self):
        """Return True if there are any neighbors that are no longer needed or should be replaced."""
        pass

    @abstractmethod
    async def get_neighbors_to_remove(self):
        """Return a list of neighbors that should be removed based on current policy constraints or evaluation."""
        pass

    @abstractmethod
    async def accept_connection(self, source, joining=False):
        """
        Determine whether to accept a connection request from a given node.

        Parameters:
            source: The identifier of the node requesting the connection.
            joining (bool): Whether this is an initial joining request.

        Returns:
            bool: True if the connection is accepted, False otherwise.
        """
        pass

    @abstractmethod
    async def get_actions(self):
        """Return a list of actions (e.g., add or remove neighbors) that should be executed to maintain the policy."""
        pass

    @abstractmethod
    async def meet_node(self, node):
        """
        Register the discovery or interaction with a new node.

        Parameters:
            node: The node being encountered or added to internal memory.
        """
        pass

    @abstractmethod
    async def forget_nodes(self, nodes, forget_all=False):
        """
        Remove the specified nodes from internal memory.

        Parameters:
            nodes: A list of node identifiers to forget.
            forget_all (bool): If True, forget all nodes.
        """
        pass

    @abstractmethod
    async def get_nodes_known(self, neighbors_too=False, neighbors_only=False):
        """
        Retrieve a list of nodes known by the current policy.

        Parameters:
            neighbors_too (bool): If True, include current neighbors in the result.
            neighbors_only (bool): If True, return only current neighbors.

        Returns:
            list: A list of node identifiers.
        """
        pass

    @abstractmethod
    async def update_neighbors(self, node, remove=False):
        """
        Add or remove a neighbor in the current neighbor set.

        Parameters:
            node: The node to be added or removed.
            remove (bool): If True, remove the node instead of adding.
        """
        pass

    @abstractmethod
    async def stricted_topology_status(stricted_topology: bool):
        """
        Update the policy with the current strict topology status.

        Parameters:
            stricted_topology (bool): True if the topology should be preserved.
        """
        pass


def factory_NeighborPolicy(topology) -> NeighborPolicy:
    from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.distanceneighborpolicy import DistanceNeighborPolicy
    from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.fcneighborpolicy import FCNeighborPolicy
    from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.idleneighborpolicy import IDLENeighborPolicy
    from nebula.core.situationalawareness.awareness.sanetwork.neighborpolicies.ringneighborpolicy import RINGNeighborPolicy

    options = {
        "random": IDLENeighborPolicy,  # default value
        "fully": FCNeighborPolicy,
        "ring": RINGNeighborPolicy,
        "star": IDLENeighborPolicy,
        "distance": DistanceNeighborPolicy,
    }

    cs = options.get(topology, IDLENeighborPolicy)
    return cs()
