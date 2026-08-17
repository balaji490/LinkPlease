import pytest
import asyncio
import random

@pytest.mark.asyncio
async def test_concurrent_500_events_ingestion(test_app):
    client = test_app["client"]
    db = test_app["db"]

    # 1. Create rules
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price: $50"})
    await client.post("/rules", json={"keyword": "INFO", "dm_message": "Info: link.com"})

    # 2. Prepare 500 comment events:
    # - 100 unique users with "PRICE"
    # - 50 unique users with "INFO"
    # - 50 duplicate events of already processed users
    # - 50 random comments not matching any keyword
    # - 250 redelivered duplicate event_ids
    events = []
    
    # 100 unique PRICE
    for i in range(100):
        events.append({
            "event_id": f"evt_price_{i}",
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_price_{i}",
                "text": "what is the PRICE?",
                "from": {"user_id": f"usr_price_{i}"}
            }
        })

    # 50 unique INFO
    for i in range(50):
        events.append({
            "event_id": f"evt_info_{i}",
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_info_{i}",
                "text": "send me INFO",
                "from": {"user_id": f"usr_info_{i}"}
            }
        })

    # 50 repeated comments from same users
    for i in range(50):
        events.append({
            "event_id": f"evt_dup_user_{i}",
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_dup_user_{i}",
                "text": "PRICE please again!",
                "from": {"user_id": f"usr_price_{i}"}  # Same user!
            }
        })

    # 50 no-match comments
    for i in range(50):
        events.append({
            "event_id": f"evt_nomatch_{i}",
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_nomatch_{i}",
                "text": "Great photo! 👍",
                "from": {"user_id": f"usr_other_{i}"}
            }
        })

    # 250 redelivered duplicates
    for i in range(250):
        # Pick from the first 100
        idx = i % 100
        events.append({
            "event_id": f"evt_price_{idx}",  # Same event_id!
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_price_{idx}",
                "text": "what is the PRICE?",
                "from": {"user_id": f"usr_price_{idx}"}
            }
        })

    # Shuffle events to simulate chaotic arrival
    random.shuffle(events)
    assert len(events) == 500

    # Ingest all 500 concurrently
    tasks = [client.post("/webhook", json=evt) for evt in events]
    responses = await asyncio.gather(*tasks)

    for resp in responses:
        assert resp.status_code == 200

    # Validate final stats
    stats = await db.get_stats()
    # Unique DMs queued: 100 (PRICE) + 50 (INFO) = 150
    assert stats["queued"] == 150
    # Duplicates blocked: 50 (duplicate user) + 250 (duplicate event_id on matching rule) = 300
    assert stats["duplicates_blocked"] == 300
    assert stats["failed"] == 0
    assert stats["sent"] == 0
