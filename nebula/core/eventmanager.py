import asyncio
import inspect
import logging
from collections import defaultdict
from functools import wraps
from abc import ABC, abstractmethod
from nebula.core.network.messages import MessageEvent
from nebula.core.utils.locker import Locker
from nebula.core.nebulaevents import AddonEvent, NodeEvent

class EventManager:
    _instance = None
    _lock = Locker("event_manager")  # Para evitar condiciones de carrera en entornos multihilo

    def __new__(cls, *args, **kwargs):
        """Implementación del patrón Singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize(*args, **kwargs)
        return cls._instance

    def _initialize(self, verbose=False):
        """Inicializa la instancia única (solo se ejecuta una vez)."""
        if hasattr(self, "_initialized"):  # Evita reinicialización
            return
        self._subscribers: dict[tuple[str, str], list] = {}
        self._message_events_lock = Locker("message_events_lock", async_lock=True)
        self._addons_events_subs: dict[type, list] = {}
        self._addons_event_lock = Locker("addons_event_lock", async_lock=True)
        self._node_events_subs: dict[type, list] = {}
        self._node_events_lock = Locker("node_events_lock", async_lock=True)
        self._verbose = verbose
        self._initialized = True  # Marca que ya se inicializó

    @staticmethod
    def get_instance(verbose=False):
        """Método estático para obtener la instancia única."""
        if EventManager._instance is None:
            EventManager(verbose=verbose)
        return EventManager._instance

    async def subscribe(self, event_type: tuple[str, str], callback: callable):
        """Register a callback for a specific event type."""
        async with self._message_events_lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
        logging.info(f"EventManager | Subscribed callback for event: {event_type}")

    async def publish(self, message_event: MessageEvent):
        """Trigger all callbacks registered for a specific event type."""
        if self._verbose: logging.info(f"Publishing MessageEvent: {message_event.message_type}")
        async with self._message_events_lock:
            event_type = message_event.message_type
            callbacks = self._subscribers.get(event_type, [])
        if not callbacks:
            logging.error(f"EventManager | No subscribers for event: {event_type}")
            return

        for callback in self._subscribers[event_type]:
            try:
                if self._verbose: logging.info(f"EventManager | Triggering callback for event: {event_type}, from source: {message_event.source}")
                if asyncio.iscoroutinefunction(callback) or inspect.iscoroutine(callback):
                    await callback(message_event.source, message_event.message)
                else:
                    callback(message_event.source, message_event.message)   
            except Exception as e:
                logging.exception(f"EventManager | Error in callback for event {event_type}: {e}")
                 
    async def subscribe_addonevent(self, addonEventType: type[AddonEvent], callback: callable):
        """Register a callback for a specific type of AddonEvent."""
        async with self._addons_event_lock:
            if addonEventType not in self._addons_events_subs:
                self._addons_events_subs[addonEventType] = []
            self._addons_events_subs[addonEventType].append(callback)
        logging.info(f"EventManager | Subscribed callback for AddonEvent type: {addonEventType.__name__}")    
        
    async def publish_addonevent(self, addonevent: AddonEvent):
        """Trigger all callbacks registered for a specific type of AddonEvent."""
        if self._verbose: logging.info(f"Publishing AddonEvent: {addonevent}")
        async with self._addons_event_lock:
            event_type = type(addonevent)
            callbacks = self._addons_events_subs.get(event_type, [])

        if not callbacks:
            if self._verbose: logging.error(f"EventManager | No subscribers for AddonEvent type: {event_type.__name__}")
            return

        for callback in self._addons_events_subs[event_type]:
            try:
                if self._verbose: logging.info(f"EventManager | Triggering callback for event type: {event_type.__name__}")
                if asyncio.iscoroutinefunction(callback) or inspect.iscoroutine(callback):
                    await callback(addonevent)
                else:
                    callback(addonevent)       
            except Exception as e:
                logging.exception(f"EventManager | Error in callback for AddonEvent {event_type.__name__}: {e}")
                    
                  
    async def subscribe_node_event(self, nodeEventType: type[NodeEvent], callback: callable):
        """Register a callback for a specific type of AddonEvent."""
        async with self._node_events_lock:
            if nodeEventType not in self._node_events_subs:
                self._node_events_subs[nodeEventType] = []
            self._node_events_subs[nodeEventType].append(callback)
        logging.info(f"EventManager | Subscribed callback for NodeEvent type: {nodeEventType.__name__}")
        
    async def publish_node_event(self, nodeevent: NodeEvent):
        """Trigger all callbacks registered for a specific type of AddonEvent."""
        if self._verbose: logging.info(f"Publishing NodeEvent: {nodeevent}")
        async with self._node_events_lock:
            event_type = type(nodeevent)
            callbacks = self._node_events_subs.get(event_type, [])  # Extraer la lista de callbacks

        if not callbacks:
            if self._verbose:
                logging.error(f"EventManager | No subscribers for NodeEvent type: {event_type.__name__}")
            return
        
        for callback in self._node_events_subs[event_type]:
            try:
                if self._verbose: logging.info(f"EventManager | Triggering callback for event type: {event_type.__name__}")
                if asyncio.iscoroutinefunction(callback) or inspect.iscoroutine(callback):
                    if await nodeevent.is_concurrent():
                        asyncio.create_task(callback(nodeevent))
                    else:
                        await callback(nodeevent)
                else:
                    callback(nodeevent)       
            except Exception as e:
                logging.exception(f"EventManager | Error in callback for NodeEvent {event_type.__name__}: {e}")

    async def unsubscribe_event(self, event_type, callback):
        """Unsubscribe a callback from a given event type (MessageEvent, AddonEvent, or NodeEvent)."""
        if isinstance(event_type, tuple):  # MessageEvent
            async with self._message_events_lock:
                if event_type in self._subscribers and callback in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(callback)
                    logging.info(f"EventManager | Unsubscribed callback for MessageEvent: {event_type}")
        elif issubclass(event_type, AddonEvent):  # AddonEvent
            async with self._addons_event_lock:
                if event_type in self._addons_events_subs and callback in self._addons_events_subs[event_type]:
                    self._addons_events_subs[event_type].remove(callback)
                    logging.info(f"EventManager | Unsubscribed callback for AddonEvent: {event_type.__name__}")
        elif issubclass(event_type, NodeEvent):  # NodeEvent
            async with self._node_events_lock:
                if event_type in self._node_events_subs and callback in self._node_events_subs[event_type]:
                    self._node_events_subs[event_type].remove(callback)
                    logging.info(f"EventManager | Unsubscribed callback for NodeEvent: {event_type.__name__}")
