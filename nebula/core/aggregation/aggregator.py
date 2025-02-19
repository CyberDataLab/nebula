import asyncio
import logging
from abc import ABC, abstractmethod
from functools import partial
from nebula.core.utils.locker import Locker
from nebula.core.aggregation.updatehandlers.updatehandler import factory_update_handler

from typing import TYPE_CHECKING
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
        self._aggregation_done_lock = Locker(name="aggregation_done_lock", async_lock=True)
        self._aggregation_waiting_skip = asyncio.Event()
        
        scenario = self.config.participant["scenario_args"]["federation"]
        self._update_storage = factory_update_handler(scenario, self, self._addr)

    def __str__(self):
        return self.__class__.__name__

    def __repr__(self):
        return self.__str__()

    @property
    def cm(self):
        return self.engine.cm
    
    @property
    def us(self):
        return self._update_storage

    @abstractmethod
    def run_aggregation(self, models):
        if len(models) == 0:
            logging.error("Trying to aggregate models when there are no models")
            return None

    async def update_federation_nodes(self, federation_nodes: set):
        await self.us.round_expected_updates(federation_nodes=federation_nodes)

        if not self._aggregation_done_lock.locked():
            self._federation_nodes = federation_nodes
            self._pending_models_to_aggregate.clear()
            await self._aggregation_done_lock.acquire_async(
                timeout=self.config.participant["aggregator_args"]["aggregation_timeout"]
            )
        else:
            raise Exception("It is not possible to set nodes to aggregate when the aggregation is running.")

    async def update_received_from_source(self, model, weight, source, round, local=False):
        await self.us.storage_update(model, weight, source, round, local=False)

    async def notify_federation_nodes_removed(self, federation_node, remove=False):
        await self.us.notify_federation_update(federation_node, remove=remove)
        
    def get_nodes_pending_models_to_aggregate(self):
        return self._federation_nodes

    def set_waiting_global_update(self):
        self._waiting_global_update = True

    # async def reset(self):
    #     await self._add_model_lock.acquire_async()
    #     self._federation_nodes.clear()
    #     self._pending_models_to_aggregate.clear()
    #     try:
    #         await self._aggregation_done_lock.release_async()
    #     except:
    #         pass
    #     await self._add_model_lock.release_async()

    async def get_aggregation(self):
        try:
            timeout = self.config.participant["aggregator_args"]["aggregation_timeout"]
            logging.info(f"Aggregation timeout: {timeout} starts...")
            await self.us.notify_if_all_updates_received()
            lock_task = asyncio.create_task(self._aggregation_done_lock.acquire_async(timeout=timeout))
            skip_task = asyncio.create_task(self._aggregation_waiting_skip.wait())
            done, pending = await asyncio.wait(
                [lock_task, skip_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            lock_acquired = lock_task in done
            if skip_task in done:
                logging.info("Skipping aggregation timeout, updates received before grace time")
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
            if lock_acquired or self._aggregation_done_lock.locked():
                await self._aggregation_done_lock.release_async()

        await self.us.stop_notifying_updates()
        updates = await self.us.get_round_updates()
        
        missing_nodes = await self.us.get_round_missing_nodes()
        
        if missing_nodes:
            logging.info(f"🔄  get_aggregation | Aggregation incomplete, missing models from: {missing_nodes}")
        else:
            logging.info("🔄  get_aggregation | All models accounted for, proceeding with aggregation.")
        
        logging.info(
                f"🔄  Broadcasting MODELS_INCLUDED for round {self.engine.get_round()}"
            )    
        message = self.cm.create_message(
                "federation", "federation_models_included", [str(arg) for arg in [self.engine.get_round()]]
            )
        await self.cm.send_message_to_neighbors(message)
       
        updates = await self.engine.apply_weight_strategy(updates)
        aggregated_result = self.run_aggregation(updates)
        return aggregated_result


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

    async def notify_all_updates_received(self):
        self._aggregation_waiting_skip.set()

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
