import pytest
import hmac
import hashlib
import json
from app.config import settings

@pytest.mark.asyncio
async def test_webhook_ingestion_and_signature(test_app):
    client = test_app["client"]
    db = test_app["db"]

    # Create a rule first
    await client.post("/rules", json={
        "keyword": "PRICE",
        "dm_message": "Price list here!"
    })

    webhook_payload = {
        "event_id": "evt_test_001",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22.481Z",
        "data": {
            "comment_id": "cmt_test_001",
            "post_id": "post_100",
            "text": "Hey what is the PRICE?",
            "created_at": "2026-08-10T09:14:21.900Z",
            "from": {
                "user_id": "usr_test_101",
                "username": "tester1"
            }
        }
    }

    raw_body = json.dumps(webhook_payload).encode("utf-8")
    secret = settings.PSEUDOGRAM_API_KEY or "test_secret_key"
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Call webhook with signature
    resp = await client.post(
        "/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-PseudoGram-Signature": f"sha256={sig}"
        }
    )
    assert resp.status_code == 200

    # Verify stats shows 1 queued
    stats = await db.get_stats()
    assert stats["queued"] == 1
    assert stats["duplicates_blocked"] == 0

@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejection(test_app):
    client = test_app["client"]
    
    webhook_payload = {
        "event_id": "evt_test_002",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_test_002",
            "from": {"user_id": "usr_fake"}
        }
    }
    raw_body = json.dumps(webhook_payload).encode("utf-8")

    # Send with bogus signature
    resp = await client.post(
        "/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-PseudoGram-Signature": "sha256=invalid_hex_signature"
        }
    )
    assert resp.status_code == 401
