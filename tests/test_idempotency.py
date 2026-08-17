import pytest

@pytest.mark.asyncio
async def test_duplicate_event_id_handling(test_app):
    client = test_app["client"]
    db = test_app["db"]

    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price: $50"})

    event = {
        "event_id": "evt_repeat_001",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_repeat_001",
            "text": "PRICE please",
            "from": {"user_id": "usr_repeat_1"}
        }
    }

    # First delivery
    resp1 = await client.post("/webhook", json=event)
    assert resp1.status_code == 200

    stats1 = await db.get_stats()
    assert stats1["queued"] == 1
    assert stats1["duplicates_blocked"] == 0

    # Second delivery of same event_id (8% mock API redelivery case)
    resp2 = await client.post("/webhook", json=event)
    assert resp2.status_code == 200

    stats2 = await db.get_stats()
    assert stats2["queued"] == 1
    assert stats2["duplicates_blocked"] == 1

@pytest.mark.asyncio
async def test_user_never_dmed_twice_for_same_rule(test_app):
    client = test_app["client"]
    db = test_app["db"]

    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price: $50"})

    # User 1 comments 5 times with different comment_ids and event_ids
    for i in range(5):
        event = {
            "event_id": f"evt_multi_comment_{i}",
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_multi_{i}",
                "text": f"Hey what is the PRICE? {i}",
                "from": {"user_id": "usr_same_person"}
            }
        }
        resp = await client.post("/webhook", json=event)
        assert resp.status_code == 200

    # Only 1 DM should be queued, and 4 should be recorded as duplicates_blocked
    stats = await db.get_stats()
    assert stats["queued"] == 1
    assert stats["duplicates_blocked"] == 4

@pytest.mark.asyncio
async def test_different_users_get_dms(test_app):
    client = test_app["client"]
    db = test_app["db"]

    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price: $50"})

    # 10 different users comment
    for i in range(10):
        event = {
            "event_id": f"evt_user_{i}",
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_user_{i}",
                "text": "PRICE please",
                "from": {"user_id": f"usr_{i}"}
            }
        }
        await client.post("/webhook", json=event)

    stats = await db.get_stats()
    assert stats["queued"] == 10
    assert stats["duplicates_blocked"] == 0
