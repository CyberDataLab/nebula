import logging
import random

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")
plt.switch_backend("Agg")

import networkx as nx
import numpy as np

from nebula.core.role import Role


class TopologyManager:
    def __init__(
        self,
        scenario_name=None,
        n_nodes=5,
        b_symmetric=True,
        undirected_neighbor_num=5,
        topology=None,
    ):
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
            raise ValueError("undirected_neighbor_num must be greater than 2")
        # If the number of neighbors is larger than the number of nodes, then the topology is fully connected
        if self.undirected_neighbor_num >= self.n_nodes - 1 and self.b_symmetric:
            self.b_fully_connected = True

    def __getstate__(self):
        # Return the attributes of the class that should be serialized
        return {
            "scenario_name": self.scenario_name,
            "n_nodes": self.n_nodes,
            "topology": self.topology,
            "nodes": self.nodes,
        }

    def __setstate__(self, state):
        # Set the attributes of the class from the serialized state
        self.scenario_name = state["scenario_name"]
        self.n_nodes = state["n_nodes"]
        self.topology = state["topology"]
        self.nodes = state["nodes"]

    def draw_graph(self, plot=False, path=None):
        g = nx.from_numpy_array(self.topology)
        # pos = nx.layout.spectral_layout(g)
        # pos = nx.spring_layout(g, pos=pos, iterations=50)
        pos = nx.spring_layout(g, k=0.15, iterations=20, seed=42)

        fig = plt.figure(num="Network topology", dpi=100, figsize=(6, 6), frameon=False)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim([-1.3, 1.3])
        ax.set_ylim([-1.3, 1.3])
        # ax.axis('off')
        labels = {}
        color_map = []
        server = False
        for k in range(self.n_nodes):
            if str(self.nodes[k][2]) == Role.AGGREGATOR:
                color_map.append("orange")
            elif str(self.nodes[k][2]) == Role.SERVER:
                server = True
                color_map.append("green")
            elif str(self.nodes[k][2]) == Role.TRAINER:
                color_map.append("#6182bd")
            elif str(self.nodes[k][2]) == Role.PROXY:
                color_map.append("purple")
            else:
                color_map.append("red")
            labels[k] = f"P{k}\n" + str(self.nodes[k][0]) + ":" + str(self.nodes[k][1])
        # nx.draw_networkx_nodes(g, pos_shadow, node_color='k', alpha=0.5)
        nx.draw_networkx_nodes(g, pos, node_color=color_map, linewidths=2)
        nx.draw_networkx_labels(g, pos, labels, font_size=10, font_weight="bold")
        nx.draw_networkx_edges(g, pos, width=2)
        # plt.margins(0.0)
        roles = [str(i[2]) for i in self.nodes]
        if Role.AGGREGATOR in roles:
            plt.scatter([], [], c="orange", label="Aggregator")
        if Role.SERVER in roles:
            plt.scatter([], [], c="green", label="Server")
        if Role.TRAINER in roles:
            plt.scatter([], [], c="#6182bd", label="Trainer")
        if Role.PROXY in roles:
            plt.scatter([], [], c="purple", label="Proxy")
        if Role.IDLE in roles:
            plt.scatter([], [], c="red", label="Idle")
        # plt.scatter([], [], c="green", label='Central Server')
        # plt.scatter([], [], c="orange", label='Aggregator')
        # plt.scatter([], [], c="#6182bd", label='Trainer')
        # plt.scatter([], [], c="purple", label='Proxy')
        # plt.scatter([], [], c="red", label='Idle')
        plt.legend()
        # import sys
        # if path is None:
        #    if not os.path.exists(f"{sys.path[0]}/logs/{self.scenario_name}"):
        #        os.makedirs(f"{sys.path[0]}/logs/{self.scenario_name}")
        #    plt.savefig(f"{sys.path[0]}/logs/{self.scenario_name}/topology.png", dpi=100, bbox_inches="tight", pad_inches=0)
        # else:
        plt.savefig(f"{path}", dpi=100, bbox_inches="tight", pad_inches=0)
        # plt.gcf().canvas.draw()
        plt.close()

    def generate_topology(self):
        if self.b_fully_connected:
            self.__fully_connected()
            return

        if self.b_symmetric:
            self.__randomly_pick_neighbors_symmetric()
        else:
            self.__randomly_pick_neighbors_asymmetric()

    def generate_server_topology(self):
        self.topology = np.zeros((self.n_nodes, self.n_nodes), dtype=np.float32)
        self.topology[0, :] = 1
        self.topology[:, 0] = 1
        np.fill_diagonal(self.topology, 0)

    def generate_ring_topology(self, increase_convergence=False):
        self.__ring_topology(increase_convergence=increase_convergence)

    def generate_custom_topology(self, topology):
        self.topology = topology

    def get_matrix_adjacency_from_neighbors(self, neighbors):
        matrix_adjacency = np.zeros((self.n_nodes, self.n_nodes), dtype=np.float32)
        for i in range(self.n_nodes):
            for j in range(self.n_nodes):
                if i in neighbors[j]:
                    matrix_adjacency[i, j] = 1
        return matrix_adjacency

    def get_topology(self):
        if self.b_symmetric:
            return self.topology
        else:
            return self.topology

    def get_nodes(self):
        return self.nodes

    @staticmethod
    def get_coordinates(random_geo=True):
        if random_geo:
            if random.randint(0, 1) == 0:
                # España
                bounds = (36.0, 43.0, -9.0, 3.3)  # min_lat, max_lat, min_lon, max_lon
            else:
                # Suiza
                bounds = (45.8, 47.8, 5.9, 10.5)  # min_lat, max_lat, min_lon, max_lon

            min_latitude, max_latitude, min_longitude, max_longitude = bounds
            latitude = random.uniform(min_latitude, max_latitude)
            longitude = random.uniform(min_longitude, max_longitude)

            return latitude, longitude

    def add_nodes(self, nodes):
        self.nodes = nodes

    def update_nodes(self, config_participants):
        self.nodes = config_participants

    def get_node(self, node_idx):
        return self.nodes[node_idx]

    def get_neighbors_string(self, node_idx):
        # logging.info(f"Topology: {self.topology}")
        # logging.info(f"Nodes: {self.nodes}")
        neighbors_data = []
        for i, node in enumerate(self.topology[node_idx]):
            if node == 1:
                neighbors_data.append(self.nodes[i])

        neighbors_data_strings = [f"{i[0]}:{i[1]}" for i in neighbors_data]
        neighbors_data_string = " ".join(neighbors_data_strings)
        logging.info(f"Neighbors of node participant_{node_idx}: {neighbors_data_string}")
        return neighbors_data_string

    def __ring_topology(self, increase_convergence=False):
        topology_ring = np.array(
            nx.to_numpy_matrix(nx.watts_strogatz_graph(self.n_nodes, 2, 0)),
            dtype=np.float32,
        )

        if increase_convergence:
            # Create random links between nodes in topology_ring
            for i in range(self.n_nodes):
                for j in range(self.n_nodes):
                    if topology_ring[i][j] == 0:
                        if random.random() < 0.1:
                            topology_ring[i][j] = 1
                            topology_ring[j][i] = 1

        np.fill_diagonal(topology_ring, 0)
        self.topology = topology_ring

    def __randomly_pick_neighbors_symmetric(self):
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
