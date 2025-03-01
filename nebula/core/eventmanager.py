import asyncio
import inspect
import logging
from collections import defaultdict
from functools import wraps

from nebula.core.network.messages import MessageEvent


def event_handler(message_type, action):
    """Decorator for registering an event handler."""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        action_name = message_type.Action.Name(action) if action is not None else "None"
        wrapper._event_handler = (message_type.DESCRIPTOR.full_name, action_name)
        return wrapper

    return decorator


class EventManager:
    def __init__(self, default_callbacks=None):
        self._event_callbacks = defaultdict(list)
        self._register_default_callbacks(default_callbacks or [])
        self._subscribers: dict[tuple[str, str], list] = {}

    def subscribe(self, event_type: tuple[str, str], callback: callable):
        """Register a callback for a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logging.info(f"EventManager | Subscribed callback for event: {event_type}")

    async def publish(self, message_event: MessageEvent):
        """Trigger all callbacks registered for a specific event type."""
        event_type = message_event.message_type
        if event_type not in self._subscribers:
            logging.error(f"EventManager | No subscribers for event: {event_type}")
            return

        for callback in self._subscribers[event_type]:
            try:
                logging.info(
                    f"EventManager | Triggering callback for event: {event_type}, from source: {message_event.source}"
                )
                await callback(message_event.source, message_event.message)
            except Exception as e:
                logging.exception(f"EventManager | Error in callback for event {event_type}: {e}")

    def _register_default_callbacks(self, default_callbacks):
        """Registers default callbacks for events."""
        for callback in default_callbacks:
            handler_info = getattr(callback, "_event_handler", None)
            if handler_info is not None:
                self.register_event(handler_info, callback)
            else:
                raise ValueError("The callback must be decorated with @event_handler.")

    def register_callback(self, callback):
        """Registers a callback for an event."""
        handler_info = getattr(callback, "_event_handler", None)
        if handler_info is not None:
            self.register_event(handler_info, callback)
        else:
            raise ValueError("The callback must be decorated with @event_handler.")

    def register_event(self, handler_info, callback):
        """Records a callback for a specific event."""
        if callable(callback):
            self._event_callbacks[handler_info].append(callback)
        else:
            raise ValueError("The callback must be a callable function.")

    def unregister_event(self, handler_info, callback):
        """Unregisters a previously registered callback for an event."""
        if callback in self._event_callbacks[handler_info]:
            self._event_callbacks[handler_info].remove(callback)

    async def trigger_event(self, source, message, *args, **kwargs):
        """Triggers an event, executing all associated callbacks."""
        message_type = message.DESCRIPTOR.full_name
        if hasattr(message, "action"):
            action_name = message.Action.Name(message.action)
        else:
            action_name = "None"

        handler_info = (message_type, action_name)

        if handler_info in self._event_callbacks:
            for callback in self._event_callbacks[handler_info]:
                try:
                    if asyncio.iscoroutinefunction(callback) or inspect.iscoroutine(callback):
                        await callback(source, message, *args, **kwargs)
                    else:
                        callback(source, message, *args, **kwargs)
                except Exception as e:
                    logging.exception(f"Error executing callback for {handler_info}: {e}")
        else:
            logging.error(f"No callbacks registered for event {handler_info}")

    async def get_event_callbacks(self, event_name):
        """Returns the callbacks for a specific event."""
        return self._event_callbacks[event_name]

    def get_event_callbacks_names(self):
        """Returns the names of the registered events."""
        return self._event_callbacks.keys()
