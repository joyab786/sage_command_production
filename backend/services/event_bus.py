import asyncio
import logging
import uuid
from typing import List, Callable, Awaitable, Dict, Any, Optional
from datetime import datetime, UTC, timedelta

from core.config import (
    SAGE_EVENT_BUS_ENABLED,
    SAGE_EVENT_BUS_QUEUE_SIZE,
    SAGE_EVENT_BUS_MAX_WORKERS,
    SAGE_EVENT_BUS_MAX_RETRIES
)
from data.schemas.event_contract import CanonicalEvent
from data.schemas.event_delivery_contract import (
    Subscription,
    EventDelivery,
    DeadLetter,
    DeliveryStatus,
    compute_delivery_id
)
from services.event_delivery_repository import EventDeliveryRepository

logger = logging.getLogger(__name__)

# Subscriber callback type: (EventDelivery, CanonicalEvent) -> Awaitable[bool (success)]
SubscriberCallback = Callable[[EventDelivery, CanonicalEvent], Awaitable[bool]]

class EventBus:
    """
    SageCommand V3 Internal Event Bus Foundation.
    Provides deterministic dispatch, bounded queues, at-least-once delivery semantics
    with idempotency tracking, retries, and dead-lettering.
    
    CRITICAL RESTRICTION: This bus MUST NOT import the execution gateway or execute physical actions.
    """
    def __init__(self, repository: EventDeliveryRepository):
        self.repository = repository
        self.enabled = SAGE_EVENT_BUS_ENABLED
        self.queue: asyncio.Queue[EventDelivery] = asyncio.Queue(maxsize=SAGE_EVENT_BUS_QUEUE_SIZE)
        self.workers: List[asyncio.Task] = []
        self._running = False
        self._callbacks: Dict[str, SubscriberCallback] = {} # subscription_id -> callback
        
        # Load active subscriptions into memory on init (tenant_id -> list[Subscription])
        self._subscriptions_cache: Dict[str, List[Subscription]] = {}

    def start(self):
        """Initializes the background dispatcher workers."""
        if not self.enabled or self._running:
            return
        
        self._running = True
        logger.info(f"Starting EventBus with {SAGE_EVENT_BUS_MAX_WORKERS} workers")
        for i in range(SAGE_EVENT_BUS_MAX_WORKERS):
            task = asyncio.create_task(self._worker_loop(i))
            self.workers.append(task)

    async def stop(self):
        """Gracefully shuts down dispatcher workers."""
        if not self._running:
            return
            
        self._running = False
        logger.info("Stopping EventBus workers...")
        
        # Unblock workers
        for _ in range(len(self.workers)):
            try:
                self.queue.put_nowait(None) # type: ignore
            except asyncio.QueueFull:
                pass
                
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("EventBus gracefully stopped.")

    def subscribe(self, subscription: Subscription, callback: SubscriberCallback) -> Subscription:
        """Registers a subscription and binds its callback in-memory."""
        saved_sub = self.repository.register_subscription(subscription)
        self._callbacks[saved_sub.subscription_id] = callback
        
        # Update cache
        tenant_cache = self._subscriptions_cache.setdefault(saved_sub.tenant_id, [])
        # Remove existing if overwriting
        tenant_cache = [s for s in tenant_cache if s.subscription_id != saved_sub.subscription_id]
        tenant_cache.append(saved_sub)
        self._subscriptions_cache[saved_sub.tenant_id] = tenant_cache
        
        return saved_sub

    def _match_subscriptions(self, event: CanonicalEvent) -> List[Subscription]:
        """Finds deterministic subscription matches for an event within the SAME TENANT ONLY."""
        if event.tenant_id not in self._subscriptions_cache:
            # Lazy load
            subs = self.repository.get_subscriptions_for_tenant(event.tenant_id)
            self._subscriptions_cache[event.tenant_id] = subs

        matches = []
        for sub in self._subscriptions_cache[event.tenant_id]:
            # Strict tenant isolation check (safety layer)
            if sub.tenant_id != event.tenant_id:
                continue
                
            # Workspace and plant boundaries
            if sub.workspace_id and sub.workspace_id != event.workspace_id:
                continue
            if sub.plant_id and sub.plant_id != event.plant_id:
                continue
                
            # Category and type matching
            if sub.category and sub.category != event.category.value:
                continue
            if sub.event_type and sub.event_type != event.event_type:
                continue
            
            # Provenance source matching
            if sub.source and sub.source != event.provenance.source:
                continue
                
            matches.append(sub)
            
        return matches

    async def publish(self, event: CanonicalEvent):
        """
        Publishes a canonical event to the bus.
        Matches subscriptions, generates idempotent delivery identities,
        persists delivery state, and enqueues.
        """
        if not self.enabled or not self._running:
            return

        subs = self._match_subscriptions(event)
        for sub in subs:
            delivery_id = compute_delivery_id(event.event_fingerprint, sub.subscription_id)
            
            # Check if this delivery already succeeded previously (Idempotency)
            existing_delivery = self.repository.get_delivery(delivery_id, event.tenant_id)
            if existing_delivery and existing_delivery.status == DeliveryStatus.SUCCESS:
                continue # Already successfully delivered
                
            delivery = existing_delivery or EventDelivery(
                delivery_id=delivery_id,
                event_id=event.event_id,
                event_fingerprint=event.event_fingerprint,
                subscription_id=sub.subscription_id,
                tenant_id=event.tenant_id,
                status=DeliveryStatus.PENDING,
                attempts=0,
                max_attempts=SAGE_EVENT_BUS_MAX_RETRIES
            )
            
            if delivery.status == DeliveryStatus.FAILED:
                # Reset status for retry if we are explicitly re-publishing
                delivery.status = DeliveryStatus.PENDING

            delivery = self.repository.record_delivery_attempt(delivery)
            
            try:
                # We do not block publication if queue is full; we drop the in-memory dispatch trigger.
                # Since the delivery is persisted as PENDING, a future sweeper/re-publisher could retry it.
                self.queue.put_nowait((delivery, event))
            except asyncio.QueueFull:
                logger.warning(f"EventBus queue is full. Delivery {delivery.delivery_id} deferred.")

    async def _worker_loop(self, worker_id: int):
        """Background bounded worker pulling from the dispatch queue."""
        while self._running:
            try:
                item = await self.queue.get()
                if item is None:
                    self.queue.task_done()
                    break # Shutdown signal
                    
                delivery, event = item
                await self._process_delivery(delivery, event)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBus Worker {worker_id} encountered unhandled error: {e}")
                
    async def _process_delivery(self, delivery: EventDelivery, event: CanonicalEvent):
        """Attempts to invoke the subscriber callback and records results."""
        callback = self._callbacks.get(delivery.subscription_id)
        if not callback:
            # Subscriber offline or unregistered
            delivery.last_error = "Subscriber callback not found in memory"
            delivery.status = DeliveryStatus.FAILED
            self.repository.record_delivery_attempt(delivery)
            return

        delivery.attempts += 1
        
        try:
            # Invoke isolated subscriber
            success = await callback(delivery, event)
            if success:
                delivery.status = DeliveryStatus.SUCCESS
                delivery.last_error = None
            else:
                delivery.status = DeliveryStatus.FAILED
                delivery.last_error = "Subscriber returned failure"
                
        except Exception as e:
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error = f"Subscriber raised exception: {str(e)}"
            
        # Handle Retry / DeadLetter
        if delivery.status == DeliveryStatus.FAILED:
            if delivery.attempts < delivery.max_attempts:
                # Calculate bounded exponential backoff
                backoff_seconds = min(2 ** delivery.attempts, 60)
                delivery.next_retry_at = (datetime.now(UTC) + timedelta(seconds=backoff_seconds)).isoformat().replace("+00:00", "Z")
                delivery.status = DeliveryStatus.PENDING # Ready to be swept/retried
            else:
                # Exhausted retries -> Dead Letter
                dl = DeadLetter(
                    dead_letter_id=f"dl_{uuid.uuid4().hex}",
                    delivery_id=delivery.delivery_id,
                    event_id=delivery.event_id,
                    subscription_id=delivery.subscription_id,
                    tenant_id=delivery.tenant_id,
                    failure_reason=delivery.last_error or "Max retries exhausted",
                    attempt_count=delivery.attempts
                )
                self.repository.record_dead_letter(dl)
                
        self.repository.record_delivery_attempt(delivery)

# Global instances for dependency injection
_event_delivery_repository = EventDeliveryRepository()
_event_bus = EventBus(_event_delivery_repository)

def get_event_bus() -> EventBus:
    return _event_bus
