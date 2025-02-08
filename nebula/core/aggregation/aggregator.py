import asyncio
import logging
from abc import ABC, abstractmethod
from functools import partial
from typing import TYPE_CHECKING

from nebula.core.utils.locker import Locker

if TYPE_CHECKING:
    from nebula.core.engine import Engine


class AggregatorException(Exception):
    pass


def create_target_aggregator(config, engine):
    from nebula.core.aggregation.fedavg import FedAvg
    from nebula.core.aggregation.krum import Krum
    from nebula.core.aggregation.median import Median
    from nebula.core.aggregation.trimmedmean import TrimmedMean

    ALGORITHM_MAP = {
        "FedAvg": FedAvg,
        "Krum": Krum,
        "Median": Median,
        "TrimmedMean": TrimmedMean,
    }
    algorithm = config.participant["defense_args"]["target_aggregation"]
    aggregator = ALGORITHM_MAP.get(algorithm)
    if aggregator:
        return aggregator(config=config, engine=engine)
    else:
        raise AggregatorException(f"Aggregation algorithm {algorithm} not found.")


class Aggregator(ABC):
    def __init__(self, config=None, engine=None):
        self.config = config
        self.engine: Engine = engine
        self._addr = config.participant["network_args"]["addr"]
        logging.info(f"[{self.__class__.__name__}] Starting Aggregator")
        self._federation_nodes = set()
        self._waiting_global_update = False
        self._pending_models_to_aggregate = {}
        self._pending_models_to_aggregate_lock = Locker(name="pending_models_to_aggregate_lock", async_lock=True)
        self._future_models_to_aggregate = {}
        self._add_model_lock = Locker(name="add_model_lock", async_lock=True)
        self._add_next_model_lock = Locker(name="add_next_model_lock", async_lock=True)
        self._aggregation_done_lock = Locker(name="aggregation_done_lock", async_lock=True)
        self._aggregation_waiting_skip = asyncio.Event()
        self._push_strategy_lock = Locker(name="push_strategy_lock", async_lock=True)

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

    async def update_federation_nodes(self, federation_nodes: set):
        if not self._aggregation_done_lock.locked():
            self._federation_nodes = federation_nodes
            self._pending_models_to_aggregate.clear()
            await self._aggregation_done_lock.acquire_async(
                timeout=self.config.participant["aggregator_args"]["aggregation_timeout"]
            )  
        else:
            raise Exception("It is not possible to set nodes to aggregate when the aggregation is running.")

    async def notify_federation_nodes_removed(self, federation_nodes: set):
        # Neighbor has been removed  
        if len(self._federation_nodes) - len(federation_nodes) > 0:
            nodes_removed = self._federation_nodes.symmetric_difference(federation_nodes)
            logging.info(f"Nodes removed from aggregation: {nodes_removed}")
            pending_nodes = (self._federation_nodes - self.get_nodes_pending_models_to_aggregate())
            #logging.info(f"Pending models to aggregate: {pending_nodes}")
            shouldnt_waited_model = []
            shouldnt_waited_model = [source for source in nodes_removed if source in pending_nodes]
            logging.info(f"Waiting models from removed neighbors: {shouldnt_waited_model}")
            if shouldnt_waited_model:
                for swm in shouldnt_waited_model:
                    logging.info(f"Removing model from waiting: {swm}")
                    pending_nodes.discard(swm)
            if self._aggregation_done_lock.locked():
                if not pending_nodes:
                    logging.info("No model updates required left | releasing aggregation lock...")
                    self._federation_nodes = federation_nodes
                    await self._aggregation_done_lock.release_async()

            self._federation_nodes = federation_nodes

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
            message = self.cm.create_message(
                "federation", "federation_models_included", [str(arg) for arg in [self.engine.get_round()]]
            )
            await self.cm.send_message_to_neighbors(message)

        return

    async def get_aggregation(self):
        try:
            timeout = self.config.participant["aggregator_args"]["aggregation_timeout"]
            logging.info(f"Aggregation timeout: {timeout} starts...")
            lock_task = asyncio.create_task(self._aggregation_done_lock.acquire_async(timeout=timeout))
            skip_task = asyncio.create_task(self._aggregation_waiting_skip.wait())
            done, pending = await asyncio.wait(
                [lock_task, skip_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            lock_acquired = lock_task in done
            if skip_task in done:
                logging.info("Skipping aggregation wait due to detected desynchronization")
                self._aggregation_waiting_skip.clear()
                if not lock_acquired:
                    lock_task.cancel()
                try:
                    await lock_task  # Clean cancel
                except asyncio.CancelledError:
                    pass

        except TimeoutError:
            logging.exception("🔄  get_aggregation | Timeout reached for aggregation")
        except asyncio.CancelledError:
            logging.exception("🔄  get_aggregation | Lock acquisition was cancelled")
        except Exception as e:
            logging.exception(f"🔄  get_aggregation | Error acquiring lock: {e}")
        finally:
            if lock_acquired:
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

        self._pending_models_to_aggregate = await self.engine.apply_weight_strategy(self._pending_models_to_aggregate)
        aggregated_result = self.run_aggregation(self._pending_models_to_aggregate)
        self._pending_models_to_aggregate.clear()
        return aggregated_result

    async def include_next_model_in_buffer(self, model, weight, source=None, round=None):
        logging.info(f"🔄  include_next_model_in_buffer | source={source} | round={round} | weight={weight}")
        if round not in self._future_models_to_aggregate:
            self._future_models_to_aggregate[round] = []
        decoded_model = self.engine.trainer.deserialize_model(model)
        await self._add_next_model_lock.acquire_async()
        self._future_models_to_aggregate[round].append((decoded_model, weight, source))
        await self._add_next_model_lock.release_async()

        # Verify if we are waiting an update that maybe we wont received
        if self._aggregation_done_lock.locked():
            pending_nodes: set = self._federation_nodes - self.get_nodes_pending_models_to_aggregate()
            if pending_nodes:
                for f_round, future_updates in self._future_models_to_aggregate.items():
                    for _, _, source in future_updates:
                        if source in pending_nodes:
                            #logging.info(f"Waiting update from source: {source}, but future update storaged for round: {f_round}")
                            pending_nodes.discard(source)

                if not pending_nodes:
                    logging.info("Received advanced updates for all sources missing this round")
                    await self._aggregation_done_lock.release_async()

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

    async def aggregation_push_available(self):
        """
        If the node is not sinchronized with the federation, it may be possible to make a push
        and try to catch the federation asap.
        """

        # TODO verify if an already sinchronized node gets desinchronized
        await self._push_strategy_lock.acquire_async()

        logging.info(
            f"❗️ synchronized status: {self.engine.get_sinchronized_status()} | Analizing if an aggregation push is available..."
        )
        if (
            not self.engine.get_sinchronized_status()
            and not self.engine.get_trainning_in_progress_lock().locked()
            and not self.engine.get_synchronizing_rounds()
        ):
            n_fed_nodes = len(self._federation_nodes)
            current_round = self.engine.get_round()
            further_round = current_round
            logging.info(
                f" Pending models: {len(self.get_nodes_pending_models_to_aggregate())} | federation: {n_fed_nodes}"
            )
            if len(self.get_nodes_pending_models_to_aggregate()) < n_fed_nodes:
                n_fed_nodes -= 1
                for f_round, fm in self._future_models_to_aggregate.items():
                    # future_models dont count self node
                    if (f_round - current_round) > 1 or len(fm) == n_fed_nodes:
                        further_round = f_round
                        push = self.engine.get_push_acceleration()
                        if push == "slow":
                            logging.info("❗️ SLOW push selected")
                            logging.info(
                                f"❗️ Federation is at least {(f_round - current_round)} rounds ahead, Pushing slow..."
                            )
                            await self.engine.set_pushed_done(further_round - current_round)
                            self.engine.update_sinchronized_status(False)
                            self.engine.set_synchronizing_rounds(True)
                            self._aggregation_waiting_skip.set()
                            await self._push_strategy_lock.release_async()
                            return

                if further_round != current_round and push == "fast":
                    logging.info("❗️ FAST push selected")
                    logging.info(f"❗️ FUTURE round: {further_round} is available, Pushing fast...")

                    if further_round == (current_round + 1):
                        logging.info(f"🔄 Rounds jumped: {1}...")
                        await self.engine.set_pushed_done(further_round - current_round)
                        self.engine.update_sinchronized_status(False)
                        self.engine.set_synchronizing_rounds(True)
                        self._aggregation_waiting_skip.set()
                        await self._push_strategy_lock.release_async()
                        return

                    logging.info(f"🔄 Number of rounds jumped: {further_round - current_round}...")
                    own_update = self._pending_models_to_aggregate.get(self.engine.get_addr())
                    while own_update == None:
                        own_update = self._pending_models_to_aggregate.get(self.engine.get_addr())
                        asyncio.sleep(1)
                    (model, weight) = own_update

                    # Getting locks to avoid concurrency issues
                    await self._add_model_lock.acquire_async()
                    await self._add_next_model_lock.acquire_async()

                    # Remove all pendings updates and add own_update
                    self._pending_models_to_aggregate.clear()
                    self._pending_models_to_aggregate.update({self.engine.get_addr(): (model, weight)})

                    # Add to pendings the future round updates
                    for future_update in self._future_models_to_aggregate[further_round]:
                        (decoded_model, weight, source) = future_update
                        self._pending_models_to_aggregate.update({source: (decoded_model, weight)})

                    # Clear all rounds that are going to be jumped
                    self._future_models_to_aggregate = {
                        key: value for key, value in self._future_models_to_aggregate.items() if key > further_round
                    }

                    self.engine.update_sinchronized_status(False)
                    self.engine.set_synchronizing_rounds(True)
                    await self.engine.set_pushed_done(further_round - current_round)
                    self.engine.set_round(further_round)
                    await self._add_model_lock.release_async()
                    await self._add_next_model_lock.release_async()
                    await self._push_strategy_lock.release_async()
                    self._aggregation_waiting_skip.set()
                    return

                else:
                    if len(self._future_models_to_aggregate.items()) < 2:
                        logging.info("Info | No future rounds available, device is up to date...")
                        self.engine.update_sinchronized_status(True)
                        self.engine.set_synchronizing_rounds(False)
                    else:
                        logging.info("No rounds can be pushed...")
                    await self._push_strategy_lock.release_async()
            else:
                logging.info(
                    f"All models updates are received | models number: {len(self.get_nodes_pending_models_to_aggregate())}"
                )
                await self._push_strategy_lock.release_async()
        else:
            if not self.engine.get_sinchronized_status():
                if self.engine.get_sinchronized_status():
                    logging.info("❗️ Cannot analize push | Trainning in progress")
                elif self.engine.get_synchronizing_rounds():
                    logging.info("❗️ Cannot analize push | already pushing rounds")
            await self._push_strategy_lock.release_async()
        

def create_malicious_aggregator(aggregator, attack):
    # It creates a partial function aggregate that wraps the aggregate method of the original aggregator.
    run_aggregation = partial(aggregator.run_aggregation)  # None is the self (not used)

    # This function will replace the original aggregate method of the aggregator.
    def malicious_aggregate(self, models):
        accum = run_aggregation(models)
        logging.info(f"malicious_aggregate | original aggregation result={accum}")
        if models is not None:
            accum = attack(accum)
            logging.info(f"malicious_aggregate | attack aggregation result={accum}")
        return accum

    aggregator.run_aggregation = partial(malicious_aggregate, aggregator)
    return aggregator


def create_aggregator(config, engine) -> Aggregator:
    from nebula.core.aggregation.blockchainReputation import BlockchainReputation
    from nebula.core.aggregation.fedavg import FedAvg
    from nebula.core.aggregation.krum import Krum
    from nebula.core.aggregation.median import Median
    from nebula.core.aggregation.trimmedmean import TrimmedMean

    ALGORITHM_MAP = {
        "FedAvg": FedAvg,
        "Krum": Krum,
        "Median": Median,
        "TrimmedMean": TrimmedMean,
        "BlockchainReputation": BlockchainReputation,
    }
    algorithm = config.participant["aggregator_args"]["algorithm"]
    aggregator = ALGORITHM_MAP.get(algorithm)
    if aggregator:
        return aggregator(config=config, engine=engine)
    else:
        raise AggregatorException(f"Aggregation algorithm {algorithm} not found.")
