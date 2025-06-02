from abc import ABC, abstractmethod

from nebula.core.nebulaevents import UpdateNeighborEvent, UpdateReceivedEvent


class UpdateHandlerException(Exception):
    pass


class UpdateHandler(ABC):
    """
    Abstract base class for managing update storage and retrieval in a federated learning setting.

    This class defines the required methods for handling updates from multiple sources,
    ensuring they are properly stored, retrieved, and processed during the aggregation process.
    """

    @abstractmethod
    async def init(self, config: dict):
        raise NotImplementedError

    @abstractmethod
    async def round_expected_updates(self, federation_nodes: set):
        """
        Initializes the expected updates for the current round.

        This method sets up the expected sources (`federation_nodes`) that should provide updates
        in the current training round. It ensures that each source has an entry in the storage
        and resets any previous tracking of received updates.

        Args:
            federation_nodes (set): A set of node identifiers expected to provide updates.
        """
        raise NotImplementedError

    @abstractmethod
    async def storage_update(self, updt_received_event: UpdateReceivedEvent):
        """
        Stores an update from a source in the update storage.

        This method ensures that an update received from a source is properly stored in the buffer,
        avoiding duplicates and managing update history if necessary.

        Args:
            model: The model associated with the update.
            weight: The weight assigned to the update (e.g., based on the amount of data used in training).
            source (str): The identifier of the node sending the update.
            round (int): The current device local training round when the update was done.
            local (boolean): Local update
        """
        raise NotImplementedError

    @abstractmethod
    async def get_round_updates(self) -> dict[str, tuple[object, float]]:
        """
        Retrieves the latest updates from all received sources in the current round.

        This method collects updates from all sources that have sent updates,
        prioritizing the most recent update available in the buffer.

        Returns:
            dict: A dictionary where keys are source identifiers and values are tuples `(model, weight)`,
                  representing the latest updates received from each source.
        """
        raise NotImplementedError

    @abstractmethod
    async def notify_federation_update(self, updt_nei_event: UpdateNeighborEvent):
        """
        Notifies the system of a change in the federation regarding a specific source.

        If a source leaves the federation, it is removed from the list of expected updates.
        If a source is newly added, it is registered for future updates.

        Args:
            source (str): The identifier of the source node.
            remove (bool, optional): Whether to remove the source from the federation. Defaults to `False`.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_round_missing_nodes(self) -> set[str]:
        """
        Identifies sources that have not yet provided updates in the current round.

        Returns:
            set: A set of source identifiers that are expected to send updates but have not yet been received.
        """
        raise NotImplementedError

    @abstractmethod
    async def notify_if_all_updates_received(self):
        """
        Notifies the system when all expected updates for the current round have been received.
        """
        raise NotImplementedError

    @abstractmethod
    async def stop_notifying_updates(self):
        """
        Stops notifications related to update reception.

        This method can be used to reset any notification mechanisms or stop tracking updates
        if the aggregation process is halted.
        """
        raise NotImplementedError


def factory_update_handler(updt_handler, aggregator, addr) -> UpdateHandler:
    from nebula.core.aggregation.updatehandlers.cflupdatehandler import CFLUpdateHandler
    from nebula.core.aggregation.updatehandlers.dflupdatehandler import DFLUpdateHandler
    from nebula.core.aggregation.updatehandlers.sdflupdatehandler import SFDLUpdateHandler

    UPDATE_HANDLERS = {"DFL": DFLUpdateHandler, "CFL": CFLUpdateHandler, "SDFL": SFDLUpdateHandler}

    update_handler = UPDATE_HANDLERS.get(updt_handler)

    if update_handler:
        return update_handler(aggregator, addr)
    else:
        raise UpdateHandlerException(f"Update Handler {updt_handler} not found")
