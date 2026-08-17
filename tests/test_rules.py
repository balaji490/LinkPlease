import pytest

@pytest.mark.asyncio
async def test_create_rule_and_matching(test_app):
    client = test_app["client"]
    rule_engine = test_app["rule_engine"]

    # 1. Create rule via API
    resp = await client.post("/rules", json={
        "keyword": "PRICE",
        "dm_message": "Here is our price list: $99/mo"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "rule_id" in data
    assert data["keyword"] == "PRICE"
    assert data["dm_message"] == "Here is our price list: $99/mo"

    # 2. Test case-insensitive substring matching
    matches_upper = await rule_engine.match_rules("Hey, what is the PRICE?")
    assert len(matches_upper) == 1
    assert matches_upper[0]["rule_id"] == data["rule_id"]

    matches_lower = await rule_engine.match_rules("can i get price details?")
    assert len(matches_lower) == 1

    matches_mixed = await rule_engine.match_rules("tell me the PriCe please!")
    assert len(matches_mixed) == 1

    matches_none = await rule_engine.match_rules("awesome photo!")
    assert len(matches_none) == 0

@pytest.mark.asyncio
async def test_create_multiple_rules(test_app):
    client = test_app["client"]
    rule_engine = test_app["rule_engine"]

    await client.post("/rules", json={"keyword": "DISCOUNT", "dm_message": "Use code SAVE10"})
    await client.post("/rules", json={"keyword": "LINK", "dm_message": "Here is the link: example.com"})

    # Matching multiple rules in one comment
    matches = await rule_engine.match_rules("send DISCOUNT and LINK please")
    assert len(matches) == 2
    keywords = {m["keyword"] for m in matches}
    assert keywords == {"DISCOUNT", "LINK"}
