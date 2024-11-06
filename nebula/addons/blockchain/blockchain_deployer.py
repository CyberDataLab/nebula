import json
import os.path
import random
import shutil
import textwrap
from datetime import datetime

from eth_keys import keys
from web3 import Web3

w3 = Web3()


class BlockchainDeployer:
    """
    Creates files (docker-compose.yaml and genesis.json) for deploying blockchain network
    """

    def __init__(self, n_validator=3, config_dir=".", input_dir="."):
        # root dir of blockchain folder
        self.__input_dir = input_dir

        # config folder for storing generated files for deployment
        self.__config_dir = config_dir

        # random but static id of boot node to be assigned to all other nodes
        self.__boot_id = None

        # ip address of boot node (needs to be static)
        self.__boot_ip = "172.25.0.101"

        # ip address of non-validator node (needs to be static)
        self.__rpc_ip = "172.25.0.104"

        # ip address of oracle (needs to be static)
        self.__oracle_ip = "172.25.0.105"

        # temporary yaml parameter to store config before dump
        self.__yaml = ""

        # list of reserved addresses which need to be excluded in random address generation
        self.__reserved_addresses = set()

        # load original genesis dict
        self.__genesis = self.__load_genesis()

        # create blockchain directory in scenario's config directory
        self.__setup_dir()

        # add a boot node to the yaml file
        self.__add_boot_node()

        # add n validator nodes to the genesis.json and yaml file
        self.__add_validator(n_validator)

        # add non-validator node to the yaml file
        self.__add_rpc()

        # add oracle node to the genesis.json and yaml file
        self.__add_oracle()

        # dump config files into scenario's config directory
        self.__export_config()

    def __setup_dir(self) -> None:
        if not os.path.exists(self.__config_dir):
            os.makedirs(self.__config_dir, exist_ok=True)

    def __get_unreserved_address(self) -> tuple[int, int]:
        """
        Computes a randomized port and last 8 bits of an ip address, where both are not yet used
        Returns: Randomized and unreserved lat 8 bit of ip and port

        """

        # extract reserved ports and ip addresses
        reserved_ips = [address[0] for address in self.__reserved_addresses]
        reserved_ports = [address[1] for address in self.__reserved_addresses]

        # get randomized ip and port in range still unreserved
        ip = random.choice([number for number in range(10, 254) if number not in reserved_ips])
        port = random.choice([number for number in range(30310, 30360) if number not in reserved_ports])

        # add network address to list of reserved addresses
        self.__reserved_addresses.add((ip, port))
        return ip, port

    def __copy_dir(self, source_path) -> None:
        """
        Copy blockchain folder with current files such as chaincode to config folder
        Args:
            source_path: Path of dir to copy

        Returns: None

        """

        curr_path = os.path.dirname(os.path.abspath(__file__))

        if not os.path.exists(self.__config_dir):
            os.makedirs(self.__config_dir, exist_ok=True)

        target_dir = os.path.join(self.__config_dir, source_path)
        source_dir = os.path.join(curr_path, source_path)
        shutil.copytree(str(source_dir), target_dir, dirs_exist_ok=True)

    @staticmethod
    def __load_genesis() -> dict[str, int | str | dict]:
        """
        Load original genesis config
        Returns: Genesis json dict

        """
        return {
            "config": {
                "chainId": 19265019,  # unique id not used by any public Ethereum network
                # block number at which the defined EIP hard fork policies are applied
                "homesteadBlock": 0,
                "eip150Block": 0,
                "eip155Block": 0,
                "eip158Block": 0,
                "byzantiumBlock": 0,
                "constantinopleBlock": 0,
                "petersburgBlock": 0,
                "istanbulBlock": 0,
                "muirGlacierBlock": 0,
                "berlinBlock": 0,
                # Proof-of-Authority settings
                "clique": {
                    "period": 1,
                    "epoch": 10000,
                },  # block time (time in seconds between two blocks)  # number of blocks after reset the pending votes
            },
            # unique continuous id of transactions used by PoA
            "nonce": "0x0",
            # UNIX timestamp of block creation
            "timestamp": "0x5a8efd25",
            # strictly formated string containing all public wallet addresses of all validators (PoA)
            # will be replaced by public addresses of randomly generated validator node
            "extraData": "0x0000000000000000000000000000000000000000000000000000000000000000187c1c14c75bA185A59c621Fbe5dda26D488852DF20C144e8aE3e1aCF7071C4883B759D1B428e7930000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            # maximum gas (computational cost) per transaction
            "gasLimit": "9000000000000",  # "8000000" is default for Ethereum but too low for heavy load
            # difficulty for PoW
            "difficulty": "0x1",
            # root hash of block
            "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
            # validator of genesis block
            "coinbase": "0x0000000000000000000000000000000000000000",
            # prefunded public wallet addresses (Oracle)
            "alloc": {
                # will be replaced by Oracle's randomized address
                "0x61DE01FcD560da4D6e05E58bCD34C8Dc92CE36D1": {
                    "balance": "0x200000000000000000000000000000000000000000000000000000000000000"
                }
            },
            # block number of genesis block
            "number": "0x0",
            # gas used to validate genesis block
            "gasUsed": "0x0",
            # hash of parent block (0x0 since first block)
            "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
        }

    def __add_boot_node(self) -> None:
        """
        Adds boot node to docker-compose.yaml
        Returns: None

        """

        # create random private key and create account from it
        acc = w3.eth.account.create()

        # store id of boot node to be inserted into all other nodes
        self.__boot_id = str(keys.PrivateKey(acc.key).public_key)[2:]

        # add service to yaml string
        self.__yaml += textwrap.dedent(
            f"""
            geth-bootnode:
                hostname: geth-bootnode
                environment:
                  - nodekeyhex={w3.to_hex(acc.key)[2:]}
                build:
                  dockerfile: {self.__input_dir}/geth/boot.dockerfile
                container_name: boot
                networks:
                  chainnet:
                    ipv4_address: {self.__boot_ip}
            """
        )

    def __add_validator(self, cnt) -> None:
        """
        Randomly generates and adds number(cnt) of validator nodes to yaml and genesis.json
        Args:
            cnt: number of validator nodes to cresate

        Returns: None

        """
        validator_addresses = list()

        for id in range(cnt):
            # create random private key and create account from it
            acc = w3.eth.account.create()
            validator_addresses.append(acc.address[2:])

            # get random network address
            ip, port = self.__get_unreserved_address()

            self.__yaml += textwrap.dedent(
                f"""
                geth-validator-{id}:
                    hostname: geth-validator-{id}
                    depends_on:
                      - geth-bootnode
                    environment:
                      - address={acc.address}
                      - bootnodeId={self.__boot_id}
                      - bootnodeIp={self.__boot_ip}
                      - port={port}
                    build:
                      dockerfile: {self.__input_dir}/geth/validator.dockerfile
                      args:
                        privatekey: {w3.to_hex(acc.key)[2:]}
                        password: {w3.to_hex(w3.eth.account.create().key)}
                    container_name: validator_{id}
                    networks:
                      chainnet:
                        ipv4_address: 172.25.0.{ip}
                """
            )

        # create specific Ethereum extra data string for PoA with all public addresses of validators
        extra_data = "0x" + "0" * 64 + "".join([a for a in validator_addresses]) + 65 * "0" + 65 * "0"
        self.__genesis["extraData"] = extra_data

    def __add_oracle(self) -> None:
        """
        Adds Oracle node to yaml and genesis.json
        Returns: None

        """

        # create random private key and create account from it
        acc = w3.eth.account.create()

        # prefund oracle by allocating all funds to its public wallet address
        self.__genesis["alloc"] = {
            acc.address: {"balance": "0x200000000000000000000000000000000000000000000000000000000000000"}
        }

        self.__yaml += textwrap.dedent(
            f"""
            oracle:
               hostname: oracle
               depends_on:
                 - geth-rpc
                 - geth-bootnode
               environment:
                 - PRIVATE_KEY={w3.to_hex(acc.key)[2:]}
                 - RPC_IP={self.__rpc_ip}
               build:
                 dockerfile: {self.__input_dir}/geth/oracle.dockerfile
                 context: {self.__input_dir}
               ports:
                 - 8081:8081
               container_name: oracle
               networks:
                 chainnet:
                   ipv4_address: {self.__oracle_ip}
            """
        )

    def __add_rpc(self):
        """
        Add non-validator node to yaml
        Returns: None

        """
        # create random private key and create account from it
        acc = w3.eth.account.create()

        self.__yaml += textwrap.dedent(
            f"""
            geth-rpc:
                 hostname: geth-rpc
                 depends_on:
                   - geth-bootnode
                 environment:
                   - address={acc.address}
                   - bootnodeId={self.__boot_id}
                   - bootnodeIp={self.__boot_ip}
                 build:
                   dockerfile: {self.__input_dir}/geth/rpc.dockerfile
                 ports:
                   - 8545:8545
                 container_name: rpc
                 networks:
                   chainnet:
                     ipv4_address: {self.__rpc_ip}
            """
        )

    def __add_network(self) -> None:
        """
        Adds network config to docker-compose.yaml to create a private network for docker compose
        Returns: None

        """
        self.__yaml += textwrap.dedent(
            """
            networks:
              chainnet:
                name: chainnet
                driver: bridge
                ipam:
                  config:
                  - subnet: 172.25.0.0/24
            """
        )

    def __export_config(self) -> None:
        """
        Writes configured yaml and genesis files to config folder for deplyoment
        Returns: None

        """

        # format yaml and add docker compose properties
        final_str = textwrap.indent(f"""{self.__yaml}""", "  ")

        self.__yaml = textwrap.dedent(
            """
                    version: "3.8"
                    name: blockchain
                    services:
                    """
        )

        self.__yaml += final_str

        # add network config last
        self.__add_network()

        with open(f"{self.__config_dir}/blockchain-docker-compose.yml", "w+") as file:
            file.write(self.__yaml)

        with open(f"{self.__input_dir}/geth/genesis.json", "w+") as file:
            json.dump(self.__genesis, file, indent=4)

        source = os.path.join(self.__input_dir, "geth", "genesis.json")
        shutil.copy(source, os.path.join(self.__config_dir, "genesis.json"))

        source = os.path.join(self.__input_dir, "chaincode", "reputation_system.sol")
        shutil.copy(source, os.path.join(self.__config_dir, "reputation_system.sol"))


if __name__ == "__main__":
    b = BlockchainDeployer(
        n_validator=3,
        config_dir=os.path.join("deployments", datetime.now().strftime("%Y-%m-%d_%H-%M")),
    )
