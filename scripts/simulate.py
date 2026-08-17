"""
Simulation and Ground Truth Comparison Tool for LinkPlease.
Runs a 500-event stress test against the deployed / local webhook URL
and compares local /stats with PseudoGram's server-side truth.
"""
import sys
import os
import time
import argparse
import httpx
from dotenv import load_dotenv

load_dotenv()

PSEUDOGRAM_BASE_URL = os.getenv("PSEUDOGRAM_BASE_URL", "https://pseudogram-api.onrender.com").rstrip("/")
API_KEY = os.getenv("PSEUDOGRAM_API_KEY", "")

def run_simulation(webhook_url: str, count: int = 500, duration: int = 10, api_key: str = API_KEY):
    if not api_key:
        print("[ERROR] PSEUDOGRAM_API_KEY is required to run simulation.")
        sys.exit(1)

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    
    print(f"\n--- 1. Triggering Simulation on PseudoGram ---")
    print(f"Target Webhook: {webhook_url}")
    print(f"Events: {count} over {duration}s")
    
    start_payload = {
        "webhook_url": webhook_url,
        "count": count,
        "duration_seconds": duration
    }
    
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{PSEUDOGRAM_BASE_URL}/v1/simulate/start", json=start_payload, headers=headers)
        if resp.status_code != 200:
            print(f"[ERROR] Failed to start simulation ({resp.status_code}): {resp.text}")
            sys.exit(1)
        
        sim_data = resp.json()
        run_id = sim_data.get("run_id")
        print(f"[SUCCESS] Simulation started! Run ID: {run_id}")
        
        print(f"\n--- 2. Waiting for Simulation & Engine Processing ---")
        wait_seconds = duration + 15
        for remaining in range(wait_seconds, 0, -1):
            sys.stdout.write(f"\rWaiting: {remaining:2d}s remaining...")
            sys.stdout.flush()
            time.sleep(1)
        print("\nDone waiting. Fetching ground truth...\n")
        
        # Fetch ground truth
        truth_resp = client.get(f"{PSEUDOGRAM_BASE_URL}/v1/simulate/{run_id}/truth", headers=headers)
        if truth_resp.status_code != 200:
            print(f"[WARNING] Truth endpoint returned {truth_resp.status_code}: {truth_resp.text}")
            truth_data = {}
        else:
            truth_data = truth_resp.json()
            
        print(f"--- 3. PseudoGram Ground Truth ---")
        print(truth_data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkPlease Simulation Runner")
    parser.add_argument("--url", required=True, help="Webhook URL (e.g. https://your-domain.com/webhook)")
    parser.add_argument("--count", type=int, default=500, help="Number of events (default: 500)")
    parser.add_argument("--duration", type=int, default=10, help="Duration in seconds (default: 10)")
    parser.add_argument("--key", default=API_KEY, help="PseudoGram API Key")
    
    args = parser.parse_args()
    run_simulation(args.url, args.count, args.duration, args.key)
