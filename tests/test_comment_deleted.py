import pytest

@pytest.mark.asyncio
async def test_comment_deleted_before_dispatch(test_app):
    client = test_app["client"]
    db = test_app["db"]

    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price: $50"})

    # 1. Incoming comment.created
    comment_event = {
        "event_id": "evt_del_001",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_to_delete_001",
            "text": "PRICE please",
            "from": {"user_id": "usr_del_001"}
        }
    }
    await client.post("/webhook", json=comment_event)

    stats1 = await db.get_stats()
    assert stats1["queued"] == 1

    # 2. comment.deleted arrives before DM is dispatched
    delete_event = {
        "event_id": "evt_del_002",
        "event_type": "comment.deleted",
        "data": {
            "comment_id": "cmt_to_delete_001"
        }
    }
    await client.post("/webhook", json=delete_event)

    # The pending DM job should now be cancelled!
    stats2 = await db.get_stats()
    assert stats2["queued"] == 0

@pytest.mark.asyncio
async def test_comment_deleted_arrives_before_created(test_app):
    client = test_app["client"]
    db = test_app["db"]

    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price: $50"})

    # 1. Out-of-order: comment.deleted arrives FIRST
    delete_event = {
        "event_id": "evt_ooo_del",
        "event_type": "comment.deleted",
        "data": {
            "comment_id": "cmt_out_of_order"
        }
    }
    await client.post("/webhook", json=delete_event)

    # 2. Delayed comment.created arrives SECOND
    create_event = {
        "event_id": "evt_ooo_create",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_out_of_order",
            "text": "what is the PRICE?",
            "from": {"user_id": "usr_ooo_001"}
        }
    }
    await client.post("/webhook", json=create_event)

    # DM should not be queued because comment is tombstoned
    stats = await db.get_stats()
    assert stats["queued"] == 0
