import pytest
import asyncio
import uuid
import os
from datetime import datetime, UTC
from typing import List

from data.schemas.event_contract import (
    CanonicalEvent, EventCategory, EventSeverity, EventLifecycle
)
from data.schemas.event_delivery_contract import (
    Subscription, EventDelivery, DeliveryStatus, DeadLetter
)
from services.event_delivery_repository import EventDeliveryRepository
from services.event_bus import EventBus
from core.config import SAGE_EVENT_DELIVERY_DB_PATH

def get_clean_repo():
    test_db = f"test_event_delivery_{uuid.uuid4().hex}.sqlite"
    repo = EventDeliveryRepository(db_path=test_db)
    return repo, test_db

def cleanup_db(db_path):
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass

def create_test_event(tenant_id="tenant-alpha", category=EventCategory.TELEMETRY) -> CanonicalEvent:
    event = CanonicalEvent(
        event_id=f"evt_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        category=category,
        event_type="test.event",
        severity=EventSeverity.INFO,
        lifecycle=EventLifecycle.RECORDED,
        occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        provenance="test_runner",
        payload={"value": 42}
    )
    event.apply_fingerprint()
    return event

class TestEventDrivenArchitecture:
    def test_01_subscription_creation_and_matching(self):
        async def run_test():
            repo, db_path = get_clean_repo()
            bus = EventBus(repo)
            bus.enabled = True
            bus.start()
            
            try:
                sub = Subscription(
                    subscription_id=f"sub_{uuid.uuid4().hex}",
                    subscriber_id="test_subscriber",
                    tenant_id="tenant-alpha",
                    category=EventCategory.TELEMETRY.value
                )
                
                delivered_events = []
                async def mock_callback(delivery: EventDelivery, event: CanonicalEvent) -> bool:
                    delivered_events.append(event)
                    return True
                    
                bus.subscribe(sub, mock_callback)
                
                matching_event = create_test_event(tenant_id="tenant-alpha", category=EventCategory.TELEMETRY)
                await bus.publish(matching_event)
                await asyncio.sleep(0.1)
                
                assert len(delivered_events) == 1
                assert delivered_events[0].event_id == matching_event.event_id
            finally:
                await bus.stop()
                cleanup_db(db_path)
        asyncio.run(run_test())

    def test_02_tenant_isolation(self):
        async def run_test():
            repo, db_path = get_clean_repo()
            bus = EventBus(repo)
            bus.enabled = True
            bus.start()
            
            try:
                sub_alpha = Subscription(
                    subscription_id=f"sub_{uuid.uuid4().hex}",
                    subscriber_id="test_subscriber",
                    tenant_id="tenant-alpha",
                )
                
                delivered_events = []
                async def mock_callback(delivery: EventDelivery, event: CanonicalEvent) -> bool:
                    delivered_events.append(event)
                    return True
                    
                bus.subscribe(sub_alpha, mock_callback)
                
                beta_event = create_test_event(tenant_id="tenant-beta")
                await bus.publish(beta_event)
                await asyncio.sleep(0.1)
                
                assert len(delivered_events) == 0
            finally:
                await bus.stop()
                cleanup_db(db_path)
        asyncio.run(run_test())

    def test_03_delivery_idempotency(self):
        async def run_test():
            repo, db_path = get_clean_repo()
            bus = EventBus(repo)
            bus.enabled = True
            bus.start()
            
            try:
                sub = Subscription(
                    subscription_id=f"sub_{uuid.uuid4().hex}",
                    subscriber_id="test_subscriber_idemp",
                    tenant_id="tenant-alpha"
                )
                
                delivery_count = 0
                async def mock_callback(delivery: EventDelivery, event: CanonicalEvent) -> bool:
                    nonlocal delivery_count
                    delivery_count += 1
                    return True
                    
                bus.subscribe(sub, mock_callback)
                event = create_test_event()
                
                await bus.publish(event)
                await asyncio.sleep(0.1)
                await bus.publish(event)
                await asyncio.sleep(0.1)
                
                assert delivery_count == 1
            finally:
                await bus.stop()
                cleanup_db(db_path)
        asyncio.run(run_test())

    def test_04_retry_and_dead_letter(self):
        async def run_test():
            repo, db_path = get_clean_repo()
            bus = EventBus(repo)
            bus.enabled = True
            bus.start()
            
            try:
                sub = Subscription(
                    subscription_id=f"sub_{uuid.uuid4().hex}",
                    subscriber_id="test_subscriber_fail",
                    tenant_id="tenant-alpha"
                )
                
                delivery_attempts = 0
                async def mock_callback(delivery: EventDelivery, event: CanonicalEvent) -> bool:
                    nonlocal delivery_attempts
                    delivery_attempts += 1
                    return False
                    
                bus.subscribe(sub, mock_callback)
                event = create_test_event()
                
                await bus.publish(event)
                await asyncio.sleep(0.1)
                
                assert delivery_attempts == 1
                deliveries = bus.repository.list_deliveries("tenant-alpha")
                assert len(deliveries) == 1
                assert deliveries[0].status == DeliveryStatus.PENDING
                
                deliveries[0].attempts = deliveries[0].max_attempts
                deliveries[0].status = DeliveryStatus.FAILED
                bus.repository.record_delivery_attempt(deliveries[0])
                
                await bus.publish(event)
                await asyncio.sleep(0.1)
                
                dls = bus.repository.list_dead_letters("tenant-alpha")
                assert len(dls) >= 1
                assert dls[0].event_id == event.event_id
            finally:
                await bus.stop()
                cleanup_db(db_path)
        asyncio.run(run_test())

    def test_05_execution_isolation(self):
        import sys
        import services.event_bus
        import inspect
        
        source = inspect.getsource(services.event_bus)
        assert "ExecutionGateway" not in source, "EventBus MUST NOT import ExecutionGateway"
        assert "ActionStatus" not in source, "EventBus MUST NOT import Action execution statuses"
