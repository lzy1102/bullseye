"""
Event Engine - Event-driven core for the trading system
Inspired by VeighNa (vnpy) event engine design
"""
from typing import Callable, Dict, List, Optional, Any
from queue import Queue, Empty, Full
from threading import Thread, Lock
from enum import Enum
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Event type enumeration"""
    # Basic events
    EVENT_TIMER = "eTimer"
    EVENT_LOG = "eLog"

    # Gateway events
    EVENT_GATEWAY_CONNECT = "eGatewayConnect"
    EVENT_GATEWAY_DISCONNECT = "eGatewayDisconnect"

    # Market data events
    EVENT_TICK = "eTick"              # Tick data
    EVENT_KLINE = "eKline"            # Kline data
    EVENT_ORDERBOOK = "eOrderBook"    # Order book snapshot

    # Trading events
    EVENT_ORDER = "eOrder"            # Order status update
    EVENT_TRADE = "eTrade"            # Trade notification
    EVENT_POSITION = "ePosition"      # Position update
    EVENT_ACCOUNT = "eAccount"        # Account update
    EVENT_CONTRACT = "eContract"      # Contract information

    # Strategy events (Freqtrade compatible)
    EVENT_ENTRY_FILL = "eEntryFill"   # Entry fill
    EVENT_EXIT_FILL = "eExitFill"     # Exit fill
    EVENT_ENTRY_CANCEL = "eEntryCancel"
    EVENT_EXIT_CANCEL = "eExitCancel"


class Event:
    """Event object"""

    __slots__ = ["type", "data", "timestamp", "gateway_name"]

    def __init__(self, type: EventType, data: Any = None, gateway_name: str = ""):
        """
        Initialize event

        Args:
            type: Event type
            data: Event data
            gateway_name: Gateway name (optional)
        """
        self.type: EventType = type
        self.data: Any = data
        self.timestamp: datetime = datetime.now()
        self.gateway_name: str = gateway_name

    def __repr__(self):
        return f"Event({self.type.value}, {self.data}, {self.gateway_name})"


class EventEngine:
    """
    Event Engine

    Handles event distribution using a queue-based system.
    Supports event subscription and publishing.

    Thread Safety:
    - Uses bounded queue to prevent memory exhaustion
    - All handler access is protected by locks
    - Graceful shutdown with timeout handling
    """

    # Maximum queue size to prevent memory exhaustion
    MAX_QUEUE_SIZE = 10000

    def __init__(self):
        """Initialize event engine"""
        self._active: bool = False
        self._thread: Optional[Thread] = None
        self._queue: Queue = Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._handlers: Dict[EventType, List[Callable]] = {}
        self._general_handlers: List[Callable] = []
        self._timer_handlers: List[Callable] = []
        self._lock = Lock()
        self._handler_lock = Lock()  # Separate lock for handler access
        self._timer_interval: float = 1.0

    def start(self, timer_interval: float = 1.0):
        """
        Start event engine

        Args:
            timer_interval: Timer interval in seconds
        """
        if self._active:
            logger.warning("Event engine already started")
            return

        self._active = True
        self._timer_interval = timer_interval
        self._thread = Thread(target=self._run, daemon=True, name="EventEngine")
        self._thread.start()

        logger.info("Event engine started")

    def stop(self, timeout: float = 10.0):
        """
        Stop event engine

        Args:
            timeout: Maximum time to wait for thread termination (seconds)
        """
        if not self._active:
            return

        self._active = False

        if self._thread and self._thread.is_alive():
            # Put a None to wake up the thread
            try:
                self._queue.put_nowait(None)
            except Full:
                pass  # Queue might be full, thread will timeout anyway

            # Wait for thread to terminate
            self._thread.join(timeout=timeout)

            if self._thread.is_alive():
                logger.warning(
                    f"Event engine thread did not terminate within {timeout}s, "
                    "proceeding anyway (daemon thread will be killed on exit)"
                )
            else:
                logger.debug("Event engine thread terminated gracefully")

        self._thread = None

        # Clear the queue to free memory
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break

        logger.info("Event engine stopped")

    def _run(self):
        """Event processing main loop"""
        import time

        last_timer_time = time.time()

        while self._active:
            try:
                # Process events from queue
                event = self._queue.get(timeout=0.1)

                if event is None:  # Sentinel to wake up
                    continue

                self._process_event(event)

            except Empty:
                # Check if timer needs to trigger
                current_time = time.time()
                if current_time - last_timer_time >= self._timer_interval:
                    self._process_timer()
                    last_timer_time = current_time

            except Exception as e:
                logger.error(f"Event processing error: {e}", exc_info=True)

    def _process_event(self, event: Event):
        """Process a single event"""
        try:
            # Get snapshot of handlers under lock to avoid race conditions
            with self._handler_lock:
                general_handlers = list(self._general_handlers)
                type_handlers = list(self._handlers.get(event.type, []))

            # Call general handlers first (outside lock)
            for handler in general_handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"General handler error: {e}", exc_info=True)

            # Call specific event type handlers (outside lock)
            for handler in type_handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Handler error for {event.type}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Event processing error: {e}", exc_info=True)

    def _process_timer(self):
        """Process timer event"""
        try:
            timer_event = Event(EventType.EVENT_TIMER)
            self._process_event(timer_event)

            # Get snapshot of timer handlers under lock
            with self._handler_lock:
                timer_handlers = list(self._timer_handlers)

            # Call timer handlers (outside lock)
            for handler in timer_handlers:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"Timer handler error: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Timer processing error: {e}", exc_info=True)

    def put(self, event: Event):
        """
        Put event into queue

        Args:
            event: Event object
        """
        if self._active:
            self._queue.put(event)
        else:
            logger.warning(f"Event engine not active, dropping event: {event.type}")

    def publish(self, event_type: EventType, data: Any = None, gateway_name: str = ""):
        """
        Publish event (convenience method)

        Args:
            event_type: Event type
            data: Event data
            gateway_name: Gateway name
        """
        event = Event(event_type, data, gateway_name)
        self.put(event)

    def subscribe(self, event_type: EventType, handler: Callable):
        """
        Subscribe to specific event type

        Args:
            event_type: Event type to subscribe
            handler: Event handler function
        """
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []

            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)
                logger.debug(f"Subscribed to {event_type.value}: {handler}")

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """
        Unsubscribe from specific event type

        Args:
            event_type: Event type
            handler: Handler function to remove
        """
        with self._lock:
            if event_type in self._handlers and handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
                logger.debug(f"Unsubscribed from {event_type.value}: {handler}")

    def subscribe_general(self, handler: Callable):
        """
        Subscribe to all events

        Args:
            handler: Handler function
        """
        with self._lock:
            if handler not in self._general_handlers:
                self._general_handlers.append(handler)
                logger.debug(f"Subscribed to general events: {handler}")

    def unsubscribe_general(self, handler: Callable):
        """
        Unsubscribe from all events

        Args:
            handler: Handler function
        """
        with self._lock:
            if handler in self._general_handlers:
                self._general_handlers.remove(handler)
                logger.debug(f"Unsubscribed from general events: {handler}")

    def register_timer(self, handler: Callable):
        """
        Register timer handler

        Args:
            handler: Timer handler function
        """
        with self._lock:
            if handler not in self._timer_handlers:
                self._timer_handlers.append(handler)
                logger.debug(f"Registered timer handler: {handler}")

    def unregister_timer(self, handler: Callable):
        """
        Unregister timer handler

        Args:
            handler: Timer handler function
        """
        with self._lock:
            if handler in self._timer_handlers:
                self._timer_handlers.remove(handler)
                logger.debug(f"Unregistered timer handler: {handler}")

    def clear_handlers(self, event_type: Optional[EventType] = None):
        """
        Clear event handlers

        Args:
            event_type: Event type to clear, None for all
        """
        with self._lock:
            if event_type is None:
                self._handlers.clear()
                self._general_handlers.clear()
                self._timer_handlers.clear()
                logger.debug("Cleared all handlers")
            elif event_type in self._handlers:
                self._handlers[event_type].clear()
                logger.debug(f"Cleared handlers for {event_type.value}")

    @property
    def is_active(self) -> bool:
        """Check if event engine is active"""
        return self._active
