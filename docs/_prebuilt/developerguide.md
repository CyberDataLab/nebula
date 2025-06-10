# **Developer Guide**

This guide is designed to help developers understand and contribute to the project. It provides detailed instructions on navigating the codebase, and implementing new features. Whether you're looking to fix bugs, add enhancements, or better understand the architecture, this guide will walk you through the essential processes and best practices for development.


## **NEBULA Frontend**

This section explains the structure of the frontend and provides instructions on how to add new parameters or sections.

### **Frontend Structure**

??? info "Structure"
    ```
    /nebula/
      addons/
      config/
      core/
      frontend/
        config/
          nebula
          participant.json.example
        databases/
          participants.db
          notes.db
          scenarios.db
          users.db
        static/
        templates/
          401.html
          403.html
          404.html
          405.html
          413.html
          admin.html
          dashboard.html
          deployment.html
          index.html
          layout.html
          monitor.html
          private.html
          statistics.html
        app.py
        database.py
        Dockerfile
        start_services.sh
    ```

The frontend is organized within the `frontend/` directory. Key files and folders include:

- `config/` → Contains the **participant.json.example**, the default structure for the paramteres passed to each participant.
- `databases/` → Contains the different databases for NEBULA
- `static/` → Holds static assets (CSS, images, JS, etc.).
- `templates/` → Contains HTML templates. Focus on **deployment.html**

### **Adding a New Parameter**

Define the new parameter in the **participant.json.example** file. Only create a new field if necessary

??? quote "participant.json.example"
    ```json linenums="1"
    {
        "scenario_args": {
          "name": "",
          "start_time": "",
          "federation": "DFL",
          "rounds": 10,
          "deployment": "process",
          "controller": "127.0.0.1:5000",
          "random_seed": 42,
          "n_participants": 0,
          /* New parameter in each setting */
          "new_parameter_key" : "new_parameter_value",
          "config_version": "development"
        },
        /* Add a new_field if necessary */
        "new_field": {
            "new_parameter_key" : "new_parameter_value"
        }
    }
    ```

To implement a new attack type, first locate the section where attacks are defined. Then, add the new attack option along with its corresponding parameter. Below is an example of how to integrate the attack and its associated parameter.

??? quote "deployment.html"
    ```html linenums="140"
    <div class="form-group row container-shadow tiny grey">
        <h5 class="step-number">Robustness <i class="fa fa-shield"></i>
            <input type="checkbox" tyle="display: none;">
            <label for="robustness-lock" class="icon-container" style="float: right;">
                <i class="fa fa-lock"></i>
            </label>
        </h5>
        <h5 class="step-title">Attack Type</h5>
        <div class="form-check form-check-inline">
            <select class="form-control" id="poisoning-attack-select" name="poisoning-attack">
                <option selected>No Attack</option>
                <option>New Attack</option> <!-- Add this -->
            </select>
            <h5 id="poisoned-participant-title" class="step-title">
                % Malicious participants
            </h5>
            <div class="form-check form-check-inline" style="display: none;" id="poisoned-participant-percent-container">
                <input type="number" class="form-control" id="poisoned-participant-percent"
                    placeholder="% malicious participants" min="0" value="0">
                    <select class="form-control" id="malicious-participants-select" name="malicious-participants-select">
                    <option selected>Percentage</option>
                    <option>Manual</option>
                </select>
            </div>
            <h5 id="poisoned-participant-title" class="step-title">
                % Malicious participants
            </h5>
            <div class="form-check form-check-inline" style="display: none;" id="poisoned-participant-percent-container">
                <input type="number" class="form-control" id="poisoned-participant-percent"
                    placeholder="% malicious participants" min="0" value="0">
            </div>
            <h5 id="new-parameter-title" class="step-title"> <!-- Add this -->
                New parameter
            </h5>
            <div class="form-check form-check-inline" style="display: none;" id="new-parameter-container">
                <input type="number" class="form-control" id="new-parameter-value"
                    placeholder="new parameter value" min="0" value="0">
            </div>
        </div>
    </div>
    ```

To receive the parameter in **nebula/scenarios.py**, you need to modify the Scenario class to accept the new parameter. This involves updating the **Scenario class** constructor and possibly the relevant methods to handle the new parameter accordingly.

??? quote "Class Scenario"
    ```python linenums="24"
    class Scenario:
        def __init__(
            self,
            scenario_title,
            scenario_description,
            new_paramater, # <--- Add this
        ):
            self.scenario_title = scenario_title
            self.scenario_description = scenario_description
            self.new_parameter = new_parameter # <--- Add this
    ```

Now you must save the parameter in the **participant configuration**.

The participant configuration files are located in the **/app/config/** directory. Ensure that the new parameter is added to the participant's JSON file, so it can be accessed later when the configuration is loaded.

??? quote "Class ScenarioManagement"
    ```python linenums="246"
        class ScenarioManagement:
        def __init__(self, scenario, user=None):
            # Save participant settings
            for participant in self.scenario.participants:
                participant_config = self.scenario.participants[participant]
                participant_file = os.path.join(self.config_dir, f"participant_{participant_config['id']}.json")
                os.makedirs(os.path.dirname(participant_file), exist_ok=True)
                shutil.copy(
                    os.path.join(
                        os.path.dirname(__file__),
                        "./frontend/config/participant.json.example",
                    ),
                    participant_file,
                )
                os.chmod(participant_file, 0o777)
                with open(participant_file) as f:
                    participant_config = json.load(f)

                participant_config["network_args"]["ip"] = participant_config["ip"]
                participant_config["network_args"]["port"] = int(participant_config["port"])
                # In case you are adding a parameter to a previously defined functionality
                participant_config["data_args"]["new_parameter"] = self.scenario.new_parameter
                # In case you are creating a new functionality
                participant_config["new_field"]["new_parameter"] = self.scenario.new_parameter
    ```

## **NEBULA Backend**

To view the documentation of functions in more detail, you must go to the **NEBULA API Reference**. This reference will provide you with comprehensive details about the available functions, their parameters, return types, and usage examples, allowing you to understand how to properly implement and interact with them.

### **Backend Structure**

??? info "Structure"
    ```
    /nebula/
      addons/
        attacks/
        trustworthiness/
        waf/
      core/
        aggregation/
        datasets/
        models/
        network/
        pb/
        training/
        utils/
        engine.py
        eventmanager.py
        role.py
      controller.py
      participant.py
      scenarios.py
      utils.py
    ```

The backend is organized within the `/nebula/` directory. Key files and folders include:

**Addons/**

The `addons/` directory contains extended functionalities that can be integrated into the core system.

- **`attacks/`** → Simulates attacks, primarily for security purposes, including adversarial attacks in machine learning.
- **`trustworthiness/`** → Evaluates the trustworthiness and reliability of participants, focusing on security and ethical considerations.
- **`waf/`** → Implements a Web Application Firewall (WAF) to filter and monitor HTTP traffic for potential threats.

**Core/**

The `core/` directory contains the essential components for the backend operation.

- **`aggregation/`** → Manages the aggregation of data from different nodes.
- **`datasets/`** → Handles dataset management, including loading and preprocessing data.
- **`models/`** → Defines machine learning model architectures and related functionalities, such as training and evaluation.
- **`network/`** → Manages communication between participants in a distributed system.
- **`pb/`** → Implements Protocol Buffers (PB) for efficient data serialization and communication.
- **`training/`** → Contains the logic for model training, optimization, and evaluation.
- **`utils/`** → Provides utility functions for file handling, logging, and common tasks.

**Files**

- **`engine.py`** → The main engine orchestrating participant communications, training, and overall behavior.
- **`eventmanager.py`** → Handles event management, logging, and notifications within the system.
- **`role.py`** → Defines participant roles and their interactions.

**Standalone Scripts**

These scripts act as entry points or controllers for various backend functionalities.

- **`controller.py`** → Manages the flow of operations, coordinating tasks and interactions.
- **`participant.py`** → Represents a participant in the decentralized network, handling computations and communication.
- **`scenarios.py`** → Defines different simulation scenarios for testing and running participants under specific conditions.
- **`utils.py`** → Contains helper functions that simplify development and maintenance.


### **Adding new Datasets**

#### Add the Dataset option in the front

First, you must add the Dataset option in the frontend. Adding the Dataset option to the scenario generated by the frontend requires a slightly different approach.

??? quote "Datasets in Deployment.html"
    ``` javascript linenums="997"
    <script>
        // Add the dataset with each model here
        var datasets = {
            "MNIST": ["MLP", "CNN"],
            "FashionMNIST": ["MLP", "CNN"],
            "EMNIST": ["MLP", "CNN"],
            "CIFAR10": ["CNN", "CNNv2", "CNNv3", "ResNet9", "fastermobilenet", "simplemobilenet"],
            "CIFAR100": ["CNN"],
        }
        var datasetSelect = document.getElementById("datasetSelect");
        var modelSelect = document.getElementById("modelSelect");
    </script>
    ```

If you want to add a new Dataset you can implement this in two ways on the folder **/nebula/core/datasets/new_dataset/new_dataset.py**

#### Import the Dataset from Torchvision

You can use the **MNIST Dataset** as a code example to demonstrate how to import the dataset from torchvision, initialize it, and load its configuration.

??? quote "MNIST Code example"
    ```python linenums="1"
    import os

    from torchvision import transforms
    from torchvision.datasets import MNIST

    from nebula.core.datasets.nebuladataset import NebulaDataset


    class MNISTDataset(NebulaDataset):
        def __init__(
            self,
            num_classes=10,
            partition_id=0,
            partitions_number=1,
            batch_size=32,
            num_workers=4,
            iid=True,
            partition="dirichlet",
            partition_parameter=0.5,
            seed=42,
            config=None,
        ):
            super().__init__(
                num_classes=num_classes,
                partition_id=partition_id,
                partitions_number=partitions_number,
                batch_size=batch_size,
                num_workers=num_workers,
                iid=iid,
                partition=partition,
                partition_parameter=partition_parameter,
                seed=seed,
                config=config,
            )
            if partition_id < 0 or partition_id >= partitions_number:
                raise ValueError(f"partition_id {partition_id} is out of range for partitions_number {partitions_number}")

        def initialize_dataset(self):
            if self.train_set is None:
                self.train_set = self.load_mnist_dataset(train=True)
            if self.test_set is None:
                self.test_set = self.load_mnist_dataset(train=False)

            self.test_indices_map = list(range(len(self.test_set)))

            # Depending on the iid flag, generate a non-iid or iid map of the train set
            if self.iid:
                self.train_indices_map = self.generate_iid_map(self.train_set, self.partition, self.partition_parameter)
                self.local_test_indices_map = self.generate_iid_map(self.test_set, self.partition, self.partition_parameter)
            else:
                self.train_indices_map = self.generate_non_iid_map(self.train_set, self.partition, self.partition_parameter)
                self.local_test_indices_map = self.generate_non_iid_map(
                    self.test_set, self.partition, self.partition_parameter
                )

            print(f"Length of train indices map: {len(self.train_indices_map)}")
            print(f"Lenght of test indices map (global): {len(self.test_indices_map)}")
            print(f"Length of test indices map (local): {len(self.local_test_indices_map)}")

        def load_mnist_dataset(self, train=True):
            apply_transforms = transforms.Compose([
                transforms.ToTensor(),
                transforms.Normalize((0.5,), (0.5,), inplace=True),
            ])
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(data_dir, exist_ok=True)
            return MNIST(
                data_dir,
                train=train,
                download=True,
                transform=apply_transforms,
            )
    ```

#### Import the Dataset from your own

If you want to import a dataset, you must first create a folder named **data** where you will store the **image_list**. Then, create a **Dataset** class similar to the one in the MilitarySAR code example.

??? quote "MilitarySAR Code Example"
    ```python linenums="66"
    class MilitarySAR(Dataset):
    def __init__(self, name="soc", is_train=False, transform=None):
        self.is_train = is_train
        self.name = name

        self.data = []
        self.targets = []
        self.serial_numbers = []

        # Path to data is "data" folder in the same directory as this file
        self.path_to_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

        self.transform = transform

        # self._load_data(self.path_to_data)

        mode = "train" if self.is_train else "test"
        self.image_list = glob.glob(os.path.join(self.path_to_data, f"{self.name}/{mode}/*/*.npy"))
        self.label_list = glob.glob(os.path.join(self.path_to_data, f"{self.name}/{mode}/*/*.json"))
        self.image_list = sorted(self.image_list, key=os.path.basename)
        self.label_list = sorted(self.label_list, key=os.path.basename)
        assert len(self.image_list) == len(self.label_list)

    def __len__(self):

    def __getitem__(self, idx):

    def _load_metadata(self):

    def get_targets(self):
    ```

Then you must create a **MilitarySARDataset** class in order to use it, as shown in the example below

??? quote "MilitarySARDataset Code example"
    ```python linenums="144"
    class MilitarySARDataset(NebulaDataset):
        def __init__(
            self,
            num_classes=10,
            partition_id=0,
            partitions_number=1,
            batch_size=32,
            num_workers=4,
            iid=True,
            partition="dirichlet",
            partition_parameter=0.5,
            seed=42,
            config=None,
        ):
            super().__init__(
                num_classes=num_classes,
                partition_id=partition_id,
                partitions_number=partitions_number,
                batch_size=batch_size,
                num_workers=num_workers,
                iid=iid,
                partition=partition,
                partition_parameter=partition_parameter,
                seed=seed,
                config=config,
            )

        def initialize_dataset(self):

        def load_militarysar_dataset(self, train=True):
    ```

#### Define transforms

You can apply transformations like cropping and normalization using `torchvision.transforms`.

For example, the **MilitarySAR** dataset uses **RandomCrop** for training and **CenterCrop** for testing.

??? quote "MilitarySAR"
    ```python linenums="17"
    class RandomCrop:
        def __init__(self, size):
            if isinstance(size, int):
                self.size = (size, size)
            else:
                assert len(size) == 2
                self.size = size

        def __call__(self, sample):
            _input = sample

            if len(_input.shape) < 3:
                _input = np.expand_dims(_input, axis=2)

            h, w, _ = _input.shape
            oh, ow = self.size

            dh = h - oh
            dw = w - ow
            y = np.random.randint(0, dh) if dh > 0 else 0
            x = np.random.randint(0, dw) if dw > 0 else 0
            oh = oh if dh > 0 else h
            ow = ow if dw > 0 else w

            return _input[y : y + oh, x : x + ow, :]


    class CenterCrop:
        def __init__(self, size):
            if isinstance(size, int):
                self.size = (size, size)
            else:
                assert len(size) == 2
                self.size = size

        def __call__(self, sample):
            _input = sample

            if len(_input.shape) < 3:
                _input = np.expand_dims(_input, axis=2)

            h, w, _ = _input.shape
            oh, ow = self.size
            y = (h - oh) // 2
            x = (w - ow) // 2

            return _input[y : y + oh, x : x + ow, :]

    class MilitarySARDataset(NebulaDataset):
        def load_militarysar_dataset(self, train=True):
            apply_transforms = [CenterCrop(88), transforms.ToTensor()]
            if train:
                apply_transforms = [RandomCrop(88), transforms.ToTensor()]

            return MilitarySAR(name="soc", is_train=train, transform=transforms.Compose(apply_transforms))
    ```

#### Associate the Model with the new Dataset

Now, you need to add the model you want to use with the dataset in the **/nebula/core/models/** folder, by creating a file named **new_dataset/new_model.py**

The model must inherit from the **NebulaModel** class

??? quote "MLP Code example"
    ```python linenums="1"
    import torch

    from nebula.core.models.nebulamodel import NebulaModel


    class MNISTModelMLP(NebulaModel):
        def __init__(
            self,
            input_channels=1,
            num_classes=10,
            learning_rate=1e-3,
            metrics=None,
            confusion_matrix=None,
            seed=None,
        ):
            super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)

            self.example_input_array = torch.zeros(1, 1, 28, 28)
            self.learning_rate = learning_rate
            self.criterion = torch.nn.CrossEntropyLoss()
            self.l1 = torch.nn.Linear(28 * 28, 256)
            self.l2 = torch.nn.Linear(256, 128)
            self.l3 = torch.nn.Linear(128, num_classes)

        def forward(self, x):
            batch_size, channels, width, height = x.size()
            x = x.view(batch_size, -1)
            x = self.l1(x)
            x = torch.relu(x)
            x = self.l2(x)
            x = torch.relu(x)
            x = self.l3(x)
            return x

        def configure_optimizers(self):
            optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
            return optimizer
    ```

### **Adding new Aggregators**

#### Adding the Aggregator in the frontend

You must add the new aggregator in the **deployment.html** file and ensure that it is correctly included in the JSON files generated within the **/app/config** folder. After making the necessary updates in the HTML, verify that the new aggregator is properly reflected in the corresponding configuration files by checking the JSON structure and values.

??? quote "deployment.html"
    ``` html linenums="632"
        <h5 class="step-title">Aggregation algorithm</h5>
        <div class="form-check form-check-inline">
            <select class="form-control" id="aggregationSelect" name="aggregation"
                style="display: inline; width: 50%">
                <option selected>FedAvg</option>
                <option>Krum</option>
                <option>TrimmedMean</option>
                <option>Median</option>
                <!--Add this-->
                <option>new_aggregation</option>
            </select>
        </div>
    ```

#### Adding the Aggregator file

You need to add the aggregator you want to use into **/nebula/core/aggregation/** by creating a file named **new_aggregator.py**

The new aggregator must inherit from the **Aggregator** class. You can use **FedAvg** as an example to guide your implementation

??? quote "Aggregator class"
    ``` python linenums="1"
    class Aggregator(ABC):
        def __init__(self, config=None, engine=None):
            self.config = config
            self.engine = engine
            self._addr = config.participant["network_args"]["addr"]
            logging.info(f"[{self.__class__.__name__}] Starting Aggregator")
            self._federation_nodes = set()
            self._waiting_global_update = False
            self._pending_models_to_aggregate = {}
            self._future_models_to_aggregate = {}
            self._add_model_lock = Locker(name="add_model_lock", async_lock=True)
            self._aggregation_done_lock = Locker(name="aggregation_done_lock", async_lock=True)

        def __str__(self):
            return self.__class__.__name__

        def __repr__(self):
            return self.__str__()

        @property
        def cm(self):
            return self.engine.cm

        @abstractmethod
        def run_aggregation(self, models):
            if len(models) == 0:
                logging.error("Trying to aggregate models when there are no models")
                return None

        async def update_federation_nodes(self, federation_nodes):
            if not self._aggregation_done_lock.locked():
                self._federation_nodes = federation_nodes
                self._pending_models_to_aggregate.clear()
                await self._aggregation_done_lock.acquire_async(
                    timeout=self.config.participant["aggregator_args"]["aggregation_timeout"]
                )
            else:
                raise Exception("It is not possible to set nodes to aggregate when the aggregation is running.")

        def set_waiting_global_update(self):
            self._waiting_global_update = True

        async def reset(self):
            await self._add_model_lock.acquire_async()
            self._federation_nodes.clear()
            self._pending_models_to_aggregate.clear()
            try:
                await self._aggregation_done_lock.release_async()
            except:
                pass
            await self._add_model_lock.release_async()

        def get_nodes_pending_models_to_aggregate(self):
            return {node for key in self._pending_models_to_aggregate.keys() for node in key.split()}

        async def _handle_global_update(self, model, source):
            logging.info(f"🔄  _handle_global_update | source={source}")
            logging.info(
                f"🔄  _handle_global_update | Received a model from {source}. Overwriting __models with the aggregated model."
            )
            self._pending_models_to_aggregate.clear()
            self._pending_models_to_aggregate = {source: (model, 1)}
            self._waiting_global_update = False
            await self._add_model_lock.release_async()
            await self._aggregation_done_lock.release_async()

        async def _add_pending_model(self, model, weight, source):
            if len(self._federation_nodes) <= len(self.get_nodes_pending_models_to_aggregate()):
                logging.info("🔄  _add_pending_model | Ignoring model...")
                await self._add_model_lock.release_async()
                return None

            if source not in self._federation_nodes:
                logging.info(f"🔄  _add_pending_model | Can't add a model from ({source}), which is not in the federation.")
                await self._add_model_lock.release_async()
                return None

            elif source not in self.get_nodes_pending_models_to_aggregate():
                logging.info(
                    "🔄  _add_pending_model | Node is not in the aggregation buffer --> Include model in the aggregation buffer."
                )
                self._pending_models_to_aggregate.update({source: (model, weight)})

            logging.info(
                f"🔄  _add_pending_model | Model added in aggregation buffer ({len(self.get_nodes_pending_models_to_aggregate())!s}/{len(self._federation_nodes)!s}) | Pending nodes: {self._federation_nodes - self.get_nodes_pending_models_to_aggregate()}"
            )

            # Check if _future_models_to_aggregate has models in the current round to include in the aggregation buffer
            if self.engine.get_round() in self._future_models_to_aggregate:
                logging.info(
                    f"🔄  _add_pending_model | Including next models in the aggregation buffer for round {self.engine.get_round()}"
                )
                for future_model in self._future_models_to_aggregate[self.engine.get_round()]:
                    if future_model is None:
                        continue
                    future_model, future_weight, future_source = future_model
                    if (
                        future_source in self._federation_nodes
                        and future_source not in self.get_nodes_pending_models_to_aggregate()
                    ):
                        self._pending_models_to_aggregate.update({future_source: (future_model, future_weight)})
                        logging.info(
                            f"🔄  _add_pending_model | Next model added in aggregation buffer ({len(self.get_nodes_pending_models_to_aggregate())!s}/{len(self._federation_nodes)!s}) | Pending nodes: {self._federation_nodes - self.get_nodes_pending_models_to_aggregate()}"
                        )
                del self._future_models_to_aggregate[self.engine.get_round()]

                for future_round in list(self._future_models_to_aggregate.keys()):
                    if future_round < self.engine.get_round():
                        del self._future_models_to_aggregate[future_round]

            if len(self.get_nodes_pending_models_to_aggregate()) >= len(self._federation_nodes):
                logging.info("🔄  _add_pending_model | All models were added in the aggregation buffer. Run aggregation...")
                await self._aggregation_done_lock.release_async()
            await self._add_model_lock.release_async()
            return self.get_nodes_pending_models_to_aggregate()

        async def include_model_in_buffer(self, model, weight, source=None, round=None, local=False):
            await self._add_model_lock.acquire_async()
            logging.info(
                f"🔄  include_model_in_buffer | source={source} | round={round} | weight={weight} |--| __models={self._pending_models_to_aggregate.keys()} | federation_nodes={self._federation_nodes} | pending_models_to_aggregate={self.get_nodes_pending_models_to_aggregate()}"
            )
            if model is None:
                logging.info("🔄  include_model_in_buffer | Ignoring model bad formed...")
                await self._add_model_lock.release_async()
                return

            if round == -1:
                # Be sure that the model message is not from the initialization round (round = -1)
                logging.info("🔄  include_model_in_buffer | Ignoring model with round -1")
                await self._add_model_lock.release_async()
                return

            if self._waiting_global_update and not local:
                await self._handle_global_update(model, source)
                return

            await self._add_pending_model(model, weight, source)

            if len(self.get_nodes_pending_models_to_aggregate()) >= len(self._federation_nodes):
                logging.info(
                    f"🔄  include_model_in_buffer | Broadcasting MODELS_INCLUDED for round {self.engine.get_round()}"
                )
                message = self.cm.create_message("federation", "federation_models_included", [str(arg) for arg in [self.engine.get_round()]])
                await self.cm.send_message_to_neighbors(message)

            return

        async def get_aggregation(self):
            try:
                timeout = self.config.participant["aggregator_args"]["aggregation_timeout"]
                await self._aggregation_done_lock.acquire_async(timeout=timeout)
            except TimeoutError:
                logging.exception("🔄  get_aggregation | Timeout reached for aggregation")
            except asyncio.CancelledError:
                logging.exception("🔄  get_aggregation | Lock acquisition was cancelled")
            except Exception as e:
                logging.exception(f"🔄  get_aggregation | Error acquiring lock: {e}")
            finally:
                await self._aggregation_done_lock.release_async()

            if self._waiting_global_update and len(self._pending_models_to_aggregate) == 1:
                logging.info(
                    "🔄  get_aggregation | Received an global model. Overwriting my model with the aggregated model."
                )
                aggregated_model = next(iter(self._pending_models_to_aggregate.values()))[0]
                self._pending_models_to_aggregate.clear()
                return aggregated_model

            unique_nodes_involved = set(node for key in self._pending_models_to_aggregate for node in key.split())

            if len(unique_nodes_involved) != len(self._federation_nodes):
                missing_nodes = self._federation_nodes - unique_nodes_involved
                logging.info(f"🔄  get_aggregation | Aggregation incomplete, missing models from: {missing_nodes}")
            else:
                logging.info("🔄  get_aggregation | All models accounted for, proceeding with aggregation.")

            aggregated_result = self.run_aggregation(self._pending_models_to_aggregate)
            self._pending_models_to_aggregate.clear()
            return aggregated_result

        async def include_next_model_in_buffer(self, model, weight, source=None, round=None):
            logging.info(f"🔄  include_next_model_in_buffer | source={source} | round={round} | weight={weight}")
            if round not in self._future_models_to_aggregate:
                self._future_models_to_aggregate[round] = []
            decoded_model = self.engine.trainer.deserialize_model(model)
            self._future_models_to_aggregate[round].append((decoded_model, weight, source))

        def print_model_size(self, model):
            total_params = 0
            total_memory = 0

            for _, param in model.items():
                num_params = param.numel()
                total_params += num_params

                memory_usage = param.element_size() * num_params
                total_memory += memory_usage

            total_memory_in_mb = total_memory / (1024**2)
            logging.info(f"print_model_size | Model size: {total_memory_in_mb} MB")
    ```

??? quote "FedAvg.py"
    ``` python linenums="1"
    import gc

    import torch

    from nebula.core.aggregation.aggregator import Aggregator


    class FedAvg(Aggregator):
        """
        Aggregator: Federated Averaging (FedAvg)
        Authors: McMahan et al.
        Year: 2016
        """

        def __init__(self, config=None, **kwargs):
            super().__init__(config, **kwargs)

        def run_aggregation(self, models):
            super().run_aggregation(models)

            models = list(models.values())

            total_samples = float(sum(weight for _, weight in models))

            if total_samples == 0:
                raise ValueError("Total number of samples must be greater than zero.")

            last_model_params = models[-1][0]
            accum = {layer: torch.zeros_like(param, dtype=torch.float32) for layer, param in last_model_params.items()}

            with torch.no_grad():
                for model_parameters, weight in models:
                    normalized_weight = weight / total_samples
                    for layer in accum:
                        accum[layer].add_(
                            model_parameters[layer].to(accum[layer].dtype),
                            alpha=normalized_weight,
                        )

            del models
            gc.collect()

            # self.print_model_size(accum)
            return accum
    ```

### **Adding new messages**
To add a new message to the application, follow these steps:

**1.** Create your message in the **nebula.proto** file inside the **nebula/core/network/pb**. Follow the structure used by other messages. For example:

??? quote "New message example"
    ```python linenums="56"
    message FederationMessage {
      enum Action {
        FEDERATION_START = 0;
        REPUTATION = 1;
        FEDERATION_MODELS_INCLUDED = 2;
        FEDERATION_READY = 3;
      }
      Action action = 1;
      repeated string arguments = 2;
      int32 round = 3;
    }
    ```

Even if your message only has one “type,” define it in this manner so that subsequent steps stay consistent.

**2.** Once the message is created in **nebula.proto**, run the protobuf protocol as indicated in the file to generate the **nebula_2pb.py** file.

**3.** In the file **/core/network/actions.py**, add the class that represents your message, following the structure of the others, and include it in the dictionary ACTION_CLASSES as a key-value pair (message_name, created_class). The message_name should be in lowercase.

**4.** In the file **/core/network/messages.py**, add your message template in the dictionary inside the _define_message_templates() function.
Follow the existing structure, indicating in parameters the different parameters of your message.
In defaults, you can provide default values for your parameters to simplify message creation.
It is important to use the exact same parameter names you defined in nebula.proto.

**5.** In the file **core/engine.py**, define your callback that will be executed when the message is received.
Use the same naming convention used in the other callbacks:

??? quote "Naming convention example"
    ```python linenums="1"
    <message_name>_<message_action>_callback(self, source, message)
    ```

**If you have followed all the previous steps, at runtime, the events and callbacks associated with your message will automatically be registered.** The system will run the callback you defined whenever the new message is received. There is nothing else to do—your message is now implemented in the messaging protocol!

### **Event System**
An **Event-Driven Architecture (EDA)** is a design model in which system components communicate through events instead of direct calls. In this architecture, producers generate events that are consumed by other services in an asynchronous manner, allowing a high degree of decoupling, scalability, and flexibility.

#### **Events**
There are currently three different event types defined in the file **/core/nebulaevents.py**:

- **NodeEvent**: Events associated with the training-aggregation process that comprises FL.
- **MessageEvent**: Events associated with Nebula’s communication protocol.
- **AddonEvent**: Events associated with additional components that can be added to scenarios.

Each event type has a different internal structure and is managed independently by the event handler, including maintaining a separate queue for each event type. Moreover, for **NodeEvent**, there is an option to define whether the subscribed listeners should be run concurrently or not.

Meanwhile, we have the **EventManager**, which controls how events are subscribed to and published. We will first look at how to use this functionality with Nebula’s native events and then go through the steps for creating new events.

??? quote "Import"
    ```python linenums="1"
    from nebula.core.eventmanager import EventManager
    ```

Once it is imported, we can subscribe to and publish events in our **.py** files:

??? quote "Subscribing to an event"
    ```python linenums="1"
    await EventManager.get_instance().subscribe(EventType, callback_used_on_trigger)
    ```

Note that **EventType** is the class that represents the event (not a specific instance) and **callback_used_on_trigger** is a coroutine (defined with **async**). To specify **EventType**, you need to import it from **nebulaevents.py**

??? quote "Import"
    ```python linenums="1"
    from nebula.core.nebulaevents import EventType
    ```

**Publishing an event:**

1. **Import the event type you want to publish.**

2. **Create an instance of that event, adhering to its definition.**

3. **Use the corresponding publish function for that event type.**

??? quote "Event example"
    ```python linenums="1"
    current_time = time.time()
    rse = RoundStartEvent(self.round, current_time)
    await EventManager.get_instance().publish_node_event(rse)
    ```

When the event is published, all subscribed listeners for that event type will be triggered. As mentioned, there are three different **publish** functions, each tied to a specific type of event.

Finally, to **create a new event**, go to the file **/core/nebulaevents.py**. Depending on the type of event you wish to implement, create a class that extends one of the three native event types. After doing this, the usage of your new event is transparent to the rest of the system, and you can use the functions described above without any issues.
