from nebula.core.aggregation.updatehandlers.updatehandler import UpdateHandler
from nebula.core.nebulaevents import UpdateNeighborEvent, UpdateReceivedEvent


class SFDLUpdateHandler(UpdateHandler):
    def __init__(
        self,
        aggregator,
        addr,
    ):
        pass

    async def init():
        raise NotImplementedError

    async def round_expected_updates(self, federation_nodes: set):
        raise NotImplementedError

    async def storage_update(self, updt_received_event: UpdateReceivedEvent):
        raise NotImplementedError

    async def get_round_updates(self) -> dict[str, tuple[object, float]]:
        raise NotImplementedError

    async def notify_federation_update(self, updt_nei_event: UpdateNeighborEvent):
        raise NotImplementedError

    async def get_round_missing_nodes(self) -> set[str]:
        raise NotImplementedError

    async def notify_if_all_updates_received(self):
        raise NotImplementedError

    async def stop_notifying_updates(self):
        raise NotImplementedError
