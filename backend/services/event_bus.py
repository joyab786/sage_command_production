import asyncio
import logging
import uuid
from typing import List, Callable, Awaitable, Dict, Any, Optional
from datetime import datetime, UTC, timedelta

from core.config import (
    SAGE_EVENT_BUS_ENABLED,
    SAGE_EVENT_BUS_QUEUE_SIZE,
    SAGE_EVENT_BUS_MAX_WORKERS,
    SAGE_EVENT_BUS_MAX_RETRIES,
    SAGE_EVENT_BUS_SWEEPER_INTERVAL_SECONDS,
    SAGE_EVENT_DELIVERY_LEASE_SECONDS
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
    with atomic database claims, leases, idempotency tracking, retries, and dead-lettering.
    
    CRITICAL RESTRICTION: This bus MUST NOT import the execution gateway or execute physical actions.
    """
    def __init__(self, repository: EventDeliveryRepository, event_repository: Optional[Any] = None):
        self.repository = repository
        self.event_repository = event_repository
        self.enabled = SAGE_EVENT_BUS_ENABLED
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=SAGE_EVENT_BUS_QUEUE_SIZE)
        self.workers: List[asyncio.Task] = []
        self._sweeper_task: Optional[asyncio.Task] = None
        self._running = False
        self._callbacks: Dict[str, SubscriberCallback] = {} # subscription_id -> callback
        
        # Load active subscriptions into memory on init (tenant_id -> list[Subscription])
        self._subscriptions_cache: Dict[str, List[Subscription]] = {}

    def start(self):
        """Initializes the background dispatcher workers and recovery sweeper."""
        if not self.enabled or self._running:
            return
        
        self._running = True
        logger.info(f"Starting EventBus with {SAGE_EVENT_BUS_MAX_WORKERS} workers")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            for i in range(SAGE_EVENT_BUS_MAX_WORKERS):
                task = asyncio.create_task(self._worker_loop(i))
                self.workers.append(task)
            if self._sweeper_task is None:
                self._sweeper_task = asyncio.create_task(self._sweeper_loop())

    async def stop(self):
        """Gracefully shuts down dispatcher workers and recovery sweeper."""
        if not self._running:
            return
            
        self._running = False
        logger.info("Stopping EventBus workers and sweeper...")
        
        if self._sweeper_task:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
            self._sweeper_task = None

        # Unblock workers
        for _ in range(len(self.workers)):
            try:
                self.queue.put_nowait(None) # type: ignore
            except asyncio.QueueFull:
                pass
                
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("EventBus gracefully stopped.")

    async def _sweeper_loop(self):
        """Background sweeper periodically recovering pending deliveries and expired leases."""
        while self._running:
            try:
                await asyncio.sleep(SAGE_EVENT_BUS_SWEEPER_INTERVAL_SECONDS)
                if self._running:
                    await self.recover_pending_deliveries(respect_backoff=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBus sweeper encountered unhandled error: {e}")

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

    def register_callback(self, subscription_id: str, callback: SubscriberCallback):
        """Binds or updates an in-memory subscriber callback for an existing subscription."""
        self._callbacks[subscription_id] = callback

    def unregister_callback(self, subscription_id: str):
        """Removes an in-memory subscriber callback (simulating subscriber going offline)."""
        self._callbacks.pop(subscription_id, None)

    def redrive_dead_letter(self, dead_letter_id: str, tenant_id: str) -> Optional[EventDelivery]:
        """Administratively re-arms a dead letter for delivery recovery within tenant boundary."""
        return self.repository.redrive_dead_letter(dead_letter_id, tenant_id)

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
            if sub.source:
                prov_source = getattr(event.provenance, "source", None) or (event.provenance if isinstance(event.provenance, str) else str(event.provenance))
                if sub.source != prov_source:
                    continue
                
            matches.append(sub)
            
        return matches

    def has_unfulfilled_deliveries(self, event: CanonicalEvent) -> bool:
        """
        Determines if an event has unfulfilled subscriptions requiring publication/retry.
        Returns True if there are matching subscriptions that have not yet succeeded and
        have not been terminally exhausted.
        Returns False if there are no matching subscriptions, all matched deliveries succeeded,
        or all unfulfilled deliveries have terminally exhausted retries.
        """
        subs = self._match_subscriptions(event)
        if not subs:
            return False
            
        for sub in subs:
            delivery_id = compute_delivery_id(event.event_fingerprint, sub.subscription_id)
            existing_delivery = self.repository.get_delivery(delivery_id, event.tenant_id)
            if not existing_delivery:
                return True
            if existing_delivery.status == DeliveryStatus.SUCCESS:
                continue
            if self.repository.get_dead_letter_by_delivery_id(delivery_id, event.tenant_id):
                continue
            if existing_delivery.status in (DeliveryStatus.PENDING, DeliveryStatus.PROCESSING):
                return True
            if existing_delivery.status == DeliveryStatus.FAILED and existing_delivery.attempts < existing_delivery.max_attempts:
                return True
        return False

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
                
            # If terminally exhausted (dead-lettered), do not retry indefinitely
            if existing_delivery and self.repository.get_dead_letter_by_delivery_id(delivery_id, event.tenant_id):
                continue

            # If actively PROCESSING with a valid lease, do not re-enqueue or interrupt active worker
            if existing_delivery and existing_delivery.status == DeliveryStatus.PROCESSING:
                now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                if existing_delivery.lease_expires_at and existing_delivery.lease_expires_at > now_iso:
                    continue

            delivery = existing_delivery or EventDelivery(
                delivery_id=delivery_id,
                event_id=event.event_id,
                event_fingerprint=event.event_fingerprint,
                subscription_id=sub.subscription_id,
                tenant_id=event.tenant_id,
                status=DeliveryStatus.PENDING,
                attempts=0,
                max_attempts=SAGE_EVENT_BUS_MAX_RETRIES,
                idempotency_key=delivery_id
            )
            
            if delivery.status == DeliveryStatus.FAILED:
                # Reset status for retry if we are explicitly re-publishing
                delivery.status = DeliveryStatus.PENDING
                delivery.next_retry_at = None

            delivery = self.repository.record_delivery_attempt(delivery)
            
            try:
                # We do not block publication if queue is full; we drop the in-memory dispatch trigger.
                # Since the delivery is persisted as PENDING, a future sweeper/re-publisher will recover it.
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
                await self._process_delivery(delivery, event, respect_backoff=True)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBus Worker {worker_id} encountered unhandled error: {e}")
                
    async def _process_delivery(
        self,
        delivery: EventDelivery,
        event: CanonicalEvent,
        respect_backoff: bool = False,
        lease_seconds: int = SAGE_EVENT_DELIVERY_LEASE_SECONDS
    ) -> bool:
        """
        Attempts to claim the delivery atomically, invoke the subscriber callback outside DB tx,
        and finalize the attempt with the acquired claim token.
        Preserves at-least-once delivery semantics for crash recovery.
        Returns True if processing succeeded or was already terminal success; False otherwise.
        """
        # Strict tenant boundary check
        if delivery.tenant_id != event.tenant_id:
            logger.error(f"Tenant boundary violation in _process_delivery: delivery tenant {delivery.tenant_id} != event tenant {event.tenant_id}")
            return False

        if delivery.status == DeliveryStatus.SUCCESS:
            return True

        # Acquire atomic database-backed lease claim
        claimed = self.repository.claim_delivery(
            delivery_id=delivery.delivery_id,
            tenant_id=delivery.tenant_id,
            lease_seconds=lease_seconds,
            respect_backoff=respect_backoff
        )
        if not claimed:
            # Cannot claim: actively leased, backoff window unexpired, already terminal success, or dead-lettered
            logger.debug(f"Delivery {delivery.delivery_id} could not be claimed (active lease, backoff, or finalized).")
            return False

        claim_token = claimed.claim_token
        # Ensure stable idempotency_key is present on the delivery passed to subscriber
        if not claimed.idempotency_key:
            claimed.idempotency_key = claimed.delivery_id

        callback = self._callbacks.get(claimed.subscription_id)
        if not callback:
            # Subscriber offline or unregistered - transient failure eligible for bounded retry
            logger.warning(f"Subscriber callback missing for subscription {claimed.subscription_id} on delivery {claimed.delivery_id}")
            self.repository.finalize_delivery(
                delivery_id=claimed.delivery_id,
                tenant_id=claimed.tenant_id,
                claim_token=claim_token,
                success=False,
                error_msg="Subscriber callback not found in memory"
            )
            return False

        # Invoke isolated subscriber callback outside of any database transaction
        try:
            success = await callback(claimed, event)
            if success:
                fin = self.repository.finalize_delivery(
                    delivery_id=claimed.delivery_id,
                    tenant_id=claimed.tenant_id,
                    claim_token=claim_token,
                    success=True
                )
                if not fin:
                    logger.warning(
                        f"Delivery {claimed.delivery_id} callback succeeded but claim token {claim_token[:8] if claim_token else ''} was superseded/expired."
                    )
                return bool(fin)
            else:
                self.repository.finalize_delivery(
                    delivery_id=claimed.delivery_id,
                    tenant_id=claimed.tenant_id,
                    claim_token=claim_token,
                    success=False,
                    error_msg="Subscriber returned failure"
                )
                return False
        except Exception as e:
            self.repository.finalize_delivery(
                delivery_id=claimed.delivery_id,
                tenant_id=claimed.tenant_id,
                claim_token=claim_token,
                success=False,
                error_msg=f"Subscriber raised exception: {str(e)}"
            )
            return False

    async def recover_pending_deliveries(
        self,
        tenant_id: Optional[str] = None,
        event_repo: Optional[Any] = None,
        limit: int = 50,
        respect_backoff: bool = False
    ) -> int:
        """
        Recovers and processes pending event deliveries stored in the repository.
        Fetches pending deliveries and expired leases, resolves canonical events,
        and dispatches them to subscriber callbacks under atomic claims.
        Returns the number of recovered deliveries processed.
        """
        if not self.enabled:
            return 0
            
        repo = event_repo or self.event_repository
        if not repo:
            try:
                from services.event_repository import EventRepository
                repo = EventRepository()
                self.event_repository = repo
            except Exception as e:
                logger.warning(f"Cannot recover pending deliveries: failed to load EventRepository: {e}")
                return 0
                
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        pending_deliveries = self.repository.get_pending_deliveries(
            tenant_id=tenant_id,
            limit=limit,
            now_iso=now_iso if respect_backoff else None,
            include_stale_leases=True
        )
        processed_count = 0
        
        for delivery in pending_deliveries:
            if tenant_id and delivery.tenant_id != tenant_id:
                logger.error(f"Tenant boundary violation during recovery: delivery {delivery.delivery_id} tenant {delivery.tenant_id} != target {tenant_id}")
                continue

            event = repo.get_event(delivery.tenant_id, delivery.event_id)
            if not event:
                logger.warning(f"Pending delivery {delivery.delivery_id} references missing event {delivery.event_id}.")
                continue

            if event.tenant_id != delivery.tenant_id:
                logger.error(f"Cross-tenant event resolution blocked during recovery: delivery tenant {delivery.tenant_id} != event tenant {event.tenant_id}")
                continue
                
            # Process delivery either via running workers queue or direct invocation
            if self._running and self.workers:
                try:
                    self.queue.put_nowait((delivery, event))
                    processed_count += 1
                except asyncio.QueueFull:
                    logger.warning(f"Queue full during recovery for delivery {delivery.delivery_id}")
            else:
                res = await self._process_delivery(delivery, event, respect_backoff=respect_backoff)
                if res:
                    processed_count += 1
                
        return processed_count

# Global instances for dependency injection
_event_delivery_repository = EventDeliveryRepository()
_event_bus = EventBus(_event_delivery_repository)

def get_event_bus() -> EventBus:
    return _event_bus
