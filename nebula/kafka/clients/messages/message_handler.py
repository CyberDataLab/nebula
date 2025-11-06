from typing import List, Tuple, Type, Callable, Dict, Any

class KafkaMessageHandler:
    def __init__(self, log):
        self._log = log
        self._handlers: Dict[Type, Callable] = {}

    def register(self, message_type: Type, handler: Callable):
        self._handlers[message_type] = handler

    async def handle(self, message):
        handler = self._handlers.get(type(message))
        if not handler:
            return 
        await handler(message)
        
def generate_handler(
    log,
    handlers: List[Tuple[Type, Callable]]
) -> KafkaMessageHandler:
    
    handler = KafkaMessageHandler(log=log)

    for message_type, callback in handlers:
        if not callable(callback):
            raise ValueError(f"Object not callable '{callable}'")
        handler.register(message_type, callback)

    return handler
