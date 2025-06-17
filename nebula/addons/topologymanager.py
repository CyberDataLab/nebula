import logging
import random

import matplotlib
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from nebula.core.role import Role

matplotlib.use("Agg")
plt.switch_backend("Agg")


class TopologyManager:
    def __init__(
        self,
        scenario_name=None,
        n_nodes=5,
        b_symmetric=True,
        undirected_neighbor_num=5,
        topology=None,
    ):
        """
        Initializes a network topology for the scenario.

        This constructor sets up a network topology with a given number of nodes, neighbors, and other parameters.
        It includes options to specify whether the topology should be symmetric and the number of undirected neighbors for each node.
        It also checks for constraints on the number of neighbors and the structure of the network.

        Parameters:
            - scenario_name (str, optional): Name of the scenario.
            - n_nodes (int): Number of nodes in the network (default 5).
            - b_symmetric (bool): Whether the topology is symmetric (default True).
            - undirected_neighbor_num (int): Number of undirected neighbors for each node (default 5).
            - topology (list, optional): Predefined topology, a list of nodes and connections (default None).

        Raises:
            - ValueError: If `undirected_neighbor_num` is less than 2.

        Attributes:
            - scenario_name (str): Name of the scenario.
            - n_nodes (int): Number of nodes in the network.
            - b_symmetric (bool): Whether the topology is symmetric.
            - undirected_neighbor_num (int): Number of undirected neighbors.
            - topology (list): Topology of the network.
            - nodes (np.ndarray): Array of nodes initialized with zeroes.
            - b_fully_connected (bool): Flag indicating if the topology is fully connected.
        """
        self.scenario_name = scenario_name
        if topology is None:
            topology = []
        self.n_nodes = n_nodes
        self.b_symmetric = b_symmetric
        self.undirected_neighbor_num = undirected_neighbor_num
        self.topology = topology
        # Initialize nodes with array of tuples (0,0,0) with size n_nodes
        self.nodes = np.zeros((n_nodes, 3), dtype=np.int32)

        self.b_fully_connected = False
        if self.undirected_neighbor_num < 2:
            raise ValueError("undirected_neighbor_num must be greater than 2")  # noqa: TRY003
        # If the number of neighbors is larger than the number of nodes, then the topology is fully connected
        if self.undirected_neighbor_num >= self.n_nodes - 1 and self.b_symmetric:
            self.b_fully_connected = True

    def __getstate__(self):
        """
        Serializes the object state for saving.

        This method defines which attributes of the class should be serialized when the object is pickled (saved to a file).
        It returns a dictionary containing the attributes that need to be preserved.

        Returns:
            dict: A dictionary containing the relevant attributes of the object for serialization.
                - scenario_name (str): Name of the scenario.
                - n_nodes (int): Number of nodes in the network.
                - topology (list): Topology of the network.
                - nodes (np.ndarray): Array of nodes in the network.
        """
        # Return the attributes of the class that should be serialized
        return {
            "scenario_name": self.scenario_name,
            "n_nodes": self.n_nodes,
            "topology": self.topology,
            "nodes": self.nodes,
        }

    def __setstate__(self, state):
        """
        Restores the object state from the serialized data.

        This method is called during deserialization (unpickling) to restore the object's state
        by setting the attributes using the provided state dictionary.

        Args:
            state (dict): A dictionary containing the serialized data, including:
                - scenario_name (str): Name of the scenario.
                - n_nodes (int): Number of nodes in the network.
                - topology (list): Topology of the network.
                - nodes (np.ndarray): Array of nodes in the network.
        """
        # Set the attributes of the class from the serialized state
        self.scenario_name = state["scenario_name"]
        self.n_nodes = state["n_nodes"]
        self.topology = state["topology"]
        self.nodes = state["nodes"]

    def get_node_color(self, role):
        """
        Returns the color associated with a given role.

        The method maps roles to specific colors for visualization or representation purposes.

        Args:
            role (Role): The role for which the color is to be determined.

        Returns:
            str: The color associated with the given role. Defaults to "red" if the role is not recognized.
        """
        role_colors = {
            Role.AGGREGATOR: "orange",
            Role.SERVER: "green",
            Role.TRAINER: "#6182bd",
            Role.PROXY: "purple",
        }
        return role_colors.get(role, "red")

    def add_legend(self, roles):
        """
        Adds a legend to the plot for different roles, associating each role with a color.

        The method iterates through the provided roles and assigns the corresponding color to each one.
        The colors are predefined in the legend_map, which associates each role with a specific color.

        Args:
            roles (iterable): A collection of roles for which the legend should be displayed.

        Returns:
            None: The function modifies the plot directly by adding the legend.
        """
        legend_map = {
            Role.AGGREGATOR: "orange",
            Role.SERVER: "green",
            Role.TRAINER: "#6182bd",
            Role.PROXY: "purple",
            Role.IDLE: "red",
        }
        for role, color in legend_map.items():
            if role in roles:
                plt.scatter([], [], c=color, label=role)
        plt.legend()

    def draw_graph(self, plot=False, path=None):
        """
        Draws the network graph based on the topology and saves it as an image.

        This method generates a visualization of the network's topology using NetworkX and Matplotlib.
        It assigns colors to the nodes based on their role, draws the network's nodes and edges,
        adds labels to the nodes, and includes a legend for clarity.
        The resulting plot is saved as an image file.

        Args:
            plot (bool, optional): Whether to display the plot. Default is False.
            path (str, optional): The file path where the image will be saved. If None, the image is saved
                                  to a default location based on the scenario name.

        Returns:
            None: The method saves the plot as an image at the specified path.
        """
        g = nx.from_numpy_array(self.topology)
        pos = nx.spring_layout(g, k=0.15, iterations=20, seed=42)

        fig = plt.figure(num="Network topology", dpi=100, figsize=(6, 6), frameon=False)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim([-1.3, 1.3])
        ax.set_ylim([-1.3, 1.3])
        labels = {}
        color_map = []
        for k in range(self.n_nodes):
            role = str(self.nodes[k][2])
            color_map.append(self.get_node_color(role))
            labels[k] = f"P{k}\n" + str(self.nodes[k][0]) + ":" + str(self.nodes[k][1])

        nx.draw_networkx_nodes(g, pos, node_color=color_map, linewidths=2)
        nx.draw_networkx_labels(g, pos, labels, font_size=10, font_weight="bold")
        nx.draw_networkx_edges(g, pos, width=2)

        self.add_legend([str(node[2]) for node in self.nodes])
        plt.savefig(f"{path}", dpi=100, bbox_inches="tight", pad_inches=0)
        plt.close()

    def generate_topology(self):
        """
        Generates the network topology based on the configured settings.

        This method generates the network topology for the given scenario. It checks whether the topology
        should be fully connected, symmetric, or asymmetric and then generates the network accordingly.

        - If the topology is fully connected, all nodes will be directly connected to each other.
        - If the topology is symmetric, neighbors will be chosen symmetrically between nodes.
        - If the topology is asymmetric, neighbors will be picked randomly without symmetry.

        Returns:
            None: The method modifies the internal topology of the network.
        """
        if self.b_fully_connected:
            self.__fully_connected()
            return

        if self.topology is not None and len(self.topology) > 0:
            # Topology was already provided
            return

        if self.b_symmetric:
            self.__randomly_pick_neighbors_symmetric()
        else:
            self.__randomly_pick_neighbors_asymmetric()

    def generate_server_topology(self):
        """
        Generates a server topology where the first node (usually the server) is connected to all other nodes.

        This method initializes a topology matrix where the first node (typically the server) is connected to
        every other node in the network. The first row and the first column of the matrix are set to 1, representing
        connections to and from the server. The diagonal is set to 0 to indicate that no node is connected to itself.

        Returns:
            None: The method modifies the internal `self.topology` matrix.
        """
        self.topology = np.zeros((self.n_nodes, self.n_nodes), dtype=np.float32)
        self.topology[0, :] = 1
        self.topology[:, 0] = 1
        np.fill_diagonal(self.topology, 0)

    def generate_ring_topology(self, increase_convergence=False):
        """
        Generates a ring topology for the network.

        In a ring topology, each node is connected to two other nodes in a circular fashion, forming a closed loop.
        This method uses a private method to generate the topology, with an optional parameter to control whether
        the convergence speed of the network should be increased.

        Args:
            increase_convergence (bool): Optional flag to increase the convergence speed in the topology.
                                          Defaults to False.

        Returns:
            None: The method modifies the internal `self.topology` matrix to reflect the generated ring topology.
        """
        self.__ring_topology(increase_convergence=increase_convergence)

    def generate_random_topology(self, probability):
        """
        Generates a random topology using Erdos-Renyi model with given probability.

        Args:
            probability (float): Probability of edge creation between any two nodes (0-1)

        Returns:
            None: Updates self.topology with the generated random topology
        """
        random_graph = nx.erdos_renyi_graph(self.n_nodes, probability)
        self.topology = nx.to_numpy_array(random_graph, dtype=np.float32)
        np.fill_diagonal(self.topology, 0)  # No self-loops

    @staticmethod
    def get_coordinates(random_geo=True):
        """
        Generates random geographical coordinates within predefined bounds for either Spain or Switzerland.

        The method returns a random geographical coordinate (latitude, longitude). The bounds for random coordinates are
        defined for two regions: Spain and Switzerland. The region is chosen randomly, and then the latitude and longitude
        are selected within the corresponding bounds.

        Parameters:
            random_geo (bool): If set to True, the method generates random coordinates within the predefined bounds
                                for Spain or Switzerland. If set to False, this method could be modified to return fixed
                                coordinates.

        Returns:
            tuple: A tuple containing the latitude and longitude of the generated point.
        """
        if random_geo:
            #  España min_lat, max_lat, min_lon, max_lon                  Suiza min_lat, max_lat, min_lon, max_lon
            bounds = (36.0, 43.0, -9.0, 3.3) if random.randint(0, 1) == 0 else (45.8, 47.8, 5.9, 10.5)  # noqa: S311

            min_latitude, max_latitude, min_longitude, max_longitude = bounds
            latitude = random.uniform(min_latitude, max_latitude)  # noqa: S311
            longitude = random.uniform(min_longitude, max_longitude)  # noqa: S311

            return latitude, longitude

    def add_nodes(self, nodes):
        """
        Sets the nodes of the topology.

        This method updates the `nodes` attribute with the given list or array of nodes.

        Parameters:
            nodes (array-like): The new set of nodes to be assigned to the topology. It should be in a format compatible
                                 with the existing `nodes` structure, typically an array or list.

        Returns:
            None
        """
        self.nodes = nodes

    def update_nodes(self, config_participants):
        """
        Updates the nodes of the topology based on the provided configuration.

        This method assigns a new set of nodes to the `nodes` attribute, typically based on the configuration of the participants.

        Parameters:
            config_participants (array-like): A new set of nodes, usually derived from the participants' configuration, to be assigned to the topology.

        Returns:
            None
        """
        self.nodes = config_participants

    def get_neighbors_string(self, node_idx):
        """
        Retrieves the neighbors of a given node as a string representation.

        This method checks the `topology` attribute to find the neighbors of the node at the specified index (`node_idx`). It then returns a string that lists the coordinates of each neighbor.

        Parameters:
            node_idx (int): The index of the node for which neighbors are to be retrieved.

        Returns:
            str: A space-separated string of neighbors' coordinates in the format "latitude:longitude".
        """
        logging.info(f"Getting neighbors for node {node_idx}")
        logging.info(f"Topology shape: {self.topology.shape}")

        neighbors_data = []
        for i in range(self.n_nodes):
            if self.topology[node_idx][i] == 1:
                neighbors_data.append(self.nodes[i])
                logging.info(f"Found neighbor at index {i}: {self.nodes[i]}")

        neighbors_data_strings = [f"{i[0]}:{i[1]}" for i in neighbors_data]
        neighbors_data_string = " ".join(neighbors_data_strings)
        logging.info(f"Neighbors of node participant_{node_idx}: {neighbors_data_string}")
        return neighbors_data_string

    def __ring_topology(self, increase_convergence=False):
        """
        Generates a ring topology for the nodes.

        This method creates a ring topology for the network using the Watts-Strogatz model. Each node is connected to two neighbors, forming a ring. Optionally, additional random connections are added to increase convergence, making the network more connected.

        Parameters:
            increase_convergence (bool): If set to True, random connections will be added between nodes to increase the network's connectivity.

        Returns:
            None: The `topology` attribute of the class is updated with the generated ring topology.
        """
        topology_ring = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, 2, 0)),
            dtype=np.float32,
        )

        if increase_convergence:
            # Create random links between nodes in topology_ring
            for i in range(self.n_nodes):
                for j in range(self.n_nodes):
                    if topology_ring[i][j] == 0 and random.random() < 0.1:  # noqa: S311
                        topology_ring[i][j] = 1
                        topology_ring[j][i] = 1

        np.fill_diagonal(topology_ring, 0)
        self.topology = topology_ring

    def __randomly_pick_neighbors_symmetric(self):
        """
        Generates a symmetric random topology by combining a ring topology with additional random links.

        This method first creates a ring topology using the Watts-Strogatz model, where each node is connected to two neighbors. Then, it randomly adds links to each node (up to the specified number of neighbors) to form a symmetric topology. The result is a topology where each node has a fixed number of undirected neighbors, and the connections are symmetric between nodes.

        Parameters:
            None

        Returns:
            None: The `topology` attribute of the class is updated with the generated symmetric topology.
        """
        # First generate a ring topology
        topology_ring = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, 2, 0)),
            dtype=np.float32,
        )

        np.fill_diagonal(topology_ring, 0)

        # After, randomly add some links for each node (symmetric)
        # If undirected_neighbor_num is X, then each node has X links to other nodes
        k = int(self.undirected_neighbor_num)
        topology_random_link = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, k, 0)),
            dtype=np.float32,
        )

        # generate symmetric topology
        topology_symmetric = topology_ring.copy()
        for i in range(self.n_nodes):
            for j in range(self.n_nodes):
                if topology_symmetric[i][j] == 0 and topology_random_link[i][j] == 1:
                    topology_symmetric[i][j] = topology_random_link[i][j]

        np.fill_diagonal(topology_symmetric, 0)

        self.topology = topology_symmetric

    def __randomly_pick_neighbors_asymmetric(self):
        """
        Generates an asymmetric random topology by combining a ring topology with additional random links and random deletions.

        This method first creates a ring topology using the Watts-Strogatz model, where each node is connected to two neighbors. Then, it randomly adds links to each node to create a topology with a specified number of undirected neighbors. After that, it randomly deletes some of the links to introduce asymmetry. The result is a topology where nodes have a varying number of directed and undirected links, and the structure is asymmetric.

        Parameters:
            None

        Returns:
            None: The `topology` attribute of the class is updated with the generated asymmetric topology.
        """
        # randomly add some links for each node (symmetric)
        k = self.undirected_neighbor_num
        topology_random_link = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, k, 0)),
            dtype=np.float32,
        )

        np.fill_diagonal(topology_random_link, 0)

        # first generate a ring topology
        topology_ring = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, 2, 0)),
            dtype=np.float32,
        )

        np.fill_diagonal(topology_ring, 0)

        for i in range(self.n_nodes):
            for j in range(self.n_nodes):
                if topology_ring[i][j] == 0 and topology_random_link[i][j] == 1:
                    topology_ring[i][j] = topology_random_link[i][j]

        np.fill_diagonal(topology_ring, 0)

        # randomly delete some links
        out_link_set = set()
        for i in range(self.n_nodes):
            len_row_zero = 0
            for j in range(self.n_nodes):
                if topology_ring[i][j] == 0:
                    len_row_zero += 1
            random_selection = np.random.randint(2, size=len_row_zero)
            index_of_zero = 0
            for j in range(self.n_nodes):
                out_link = j * self.n_nodes + i
                if topology_ring[i][j] == 0:
                    if random_selection[index_of_zero] == 1 and out_link not in out_link_set:
                        topology_ring[i][j] = 1
                        out_link_set.add(i * self.n_nodes + j)
                    index_of_zero += 1

        np.fill_diagonal(topology_ring, 0)

        self.topology = topology_ring

    def __fully_connected(self):
        """
        Generates a fully connected topology where each node is connected to every other node.

        This method creates a fully connected network by generating a Watts-Strogatz graph with the number of nodes set to `n_nodes` and the number of neighbors set to `n_nodes - 1`. The resulting graph is then converted into a numpy matrix and all missing links (i.e., non-ones in the adjacency matrix) are set to 1 to ensure complete connectivity. The diagonal elements are filled with zeros to avoid self-loops.

        Parameters:
            None

        Returns:
            None: The `topology` attribute of the class is updated with the generated fully connected topology.
        """
        topology_fully_connected = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, self.n_nodes - 1, 0)),
            dtype=np.float32,
        )

        np.fill_diagonal(topology_fully_connected, 0)

        for i in range(self.n_nodes):
            for j in range(self.n_nodes):
                if topology_fully_connected[i][j] != 1:
                    topology_fully_connected[i][j] = 1

        np.fill_diagonal(topology_fully_connected, 0)

        self.topology = topology_fully_connected
