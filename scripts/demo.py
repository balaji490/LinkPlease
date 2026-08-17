import httpx
import time
import json

BASE_URL = "http://127.0.0.1:8000"

def run_demo():
    print("=" * 60)
    print(" LinkPlease Mini-Engine Live Demo Flow")
    print("=" * 60)

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Health check
        health = client.get("/health").json()
        print(f"\n[1] Health Check: {health}")

        # 2. Create a rule
        rule_req = {
            "keyword": "PRICE",
            "dm_message": "Hey! Here is our price list: $99/mo. Sign up at link.com"
        }
        rule_resp = client.post("/rules", json=rule_req)
        print(f"\n[2] Create Rule (POST /rules):")
        print(f"    Status: {rule_resp.status_code}")
        print(f"    Body:   {rule_resp.json()}")
        rule_id = rule_resp.json().get("rule_id")

        # 3. Ingest comment matching keyword
        comment_1 = {
            "event_id": "evt_demo_001",
            "event_type": "comment.created",
            "sent_at": "2026-08-17T00:00:00.000Z",
            "data": {
                "comment_id": "cmt_demo_001",
                "post_id": "post_123",
                "text": "Hey what is the PRICE for this?",
                "created_at": "2026-08-17T00:00:00.000Z",
                "from": {
                    "user_id": "usr_alex_01",
                    "username": "alex.shoots"
                }
            }
        }
        w1 = client.post("/webhook", json=comment_1)
        print(f"\n[3] Incoming Comment Matching Rule (POST /webhook):")
        print(f"    Status: {w1.status_code}")
        print(f"    Body:   {w1.json()}")

        # 4. Duplicate Comment from same user (Idempotency Protection)
        comment_2 = {
            "event_id": "evt_demo_002",
            "event_type": "comment.created",
            "sent_at": "2026-08-17T00:00:05.000Z",
            "data": {
                "comment_id": "cmt_demo_002",
                "post_id": "post_123",
                "text": "tell me PRICE again please!",
                "from": {
                    "user_id": "usr_alex_01",  # Same user!
                    "username": "alex.shoots"
                }
            }
        }
        w2 = client.post("/webhook", json=comment_2)
        print(f"\n[4] Duplicate Comment from Same User (POST /webhook):")
        print(f"    Status: {w2.status_code}")
        print(f"    Body:   {w2.json()} (Blocked duplicate)")

        # 5. Redelivered event_id (8% mock API case)
        w3 = client.post("/webhook", json=comment_1)
        print(f"\n[5] Redelivered event_id 'evt_demo_001' (POST /webhook):")
        print(f"    Status: {w3.status_code}")
        print(f"    Body:   {w3.json()} (Blocked duplicate event)")

        # 6. Comment with no keyword match
        comment_3 = {
            "event_id": "evt_demo_003",
            "event_type": "comment.created",
            "data": {
                "comment_id": "cmt_demo_003",
                "text": "Love the vibes! 🔥",
                "from": {"user_id": "usr_maria_02"}
            }
        }
        w4 = client.post("/webhook", json=comment_3)
        print(f"\n[6] Unmatched Comment (POST /webhook):")
        print(f"    Status: {w4.status_code}")
        print(f"    Body:   {w4.json()}")

        # 7. Check Live Stats
        stats = client.get("/stats").json()
        print(f"\n[7] Live Stats (GET /stats):")
        print(f"    {json.dumps(stats, indent=4)}")
        print("=" * 60)

if __name__ == "__main__":
    run_demo()
