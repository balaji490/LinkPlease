"""
Helper script to apply and generate API key for PseudoGram mock API.
"""
import sys
import os
import argparse
import httpx

PSEUDOGRAM_BASE_URL = os.getenv("PSEUDOGRAM_BASE_URL", "https://pseudogram-api.onrender.com").rstrip("/")

def apply_and_keygen(name: str, email: str, phone: str, linkedin_url: str, whatsapp: str = None):
    whatsapp_val = whatsapp or phone
    apply_payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "whatsapp": whatsapp_val,
        "linkedin_url": linkedin_url
    }
    
    print(f"\n1. Submitting Application to {PSEUDOGRAM_BASE_URL}/v1/apply...")
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(f"{PSEUDOGRAM_BASE_URL}/v1/apply", json=apply_payload)
        print(f"Apply status: {resp.status_code} - {resp.text}")
        
        if resp.status_code not in (200, 201):
            print("[NOTICE] If already registered, continuing to keygen...")
            
        print(f"\n2. Requesting API Key from {PSEUDOGRAM_BASE_URL}/v1/keygen...")
        key_resp = client.post(f"{PSEUDOGRAM_BASE_URL}/v1/keygen", json={"email": email})
        print(f"Keygen status: {key_resp.status_code} - {key_resp.text}")
        
        if key_resp.status_code == 200:
            key_data = key_resp.json()
            api_key = key_data.get("api_key")
            print(f"\n[SUCCESS] Your PseudoGram API Key is: {api_key}")
            print(f"Set this in your .env file as PSEUDOGRAM_API_KEY={api_key}\n")
            return api_key
        else:
            print(f"[ERROR] Could not obtain API key: {key_resp.text}")
            return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PseudoGram Onboarding Helper")
    parser.add_argument("--name", required=True, help="Full Name")
    parser.add_argument("--email", required=True, help="Email address")
    parser.add_argument("--phone", required=True, help="Phone number with country code")
    parser.add_argument("--linkedin", required=True, help="LinkedIn profile URL")
    parser.add_argument("--whatsapp", default=None, help="WhatsApp number (optional)")
    
    args = parser.parse_args()
    apply_and_keygen(args.name, args.email, args.phone, args.linkedin, args.whatsapp)
