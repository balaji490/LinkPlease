import hmac
import hashlib
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def verify_signature(raw_body: bytes, signature_header: Optional[str], secret: str) -> bool:
    """
    Verify HMAC-SHA256 signature from X-PseudoGram-Signature header.
    Format: sha256=<hex_digest>
    """
    if not secret:
        # If no secret configured, allow (useful during local test/dev)
        return True
        
    if not signature_header:
        logger.warning("Missing X-PseudoGram-Signature header")
        return False

    prefix = "sha256="
    if signature_header.startswith(prefix):
        provided_sig = signature_header[len(prefix):]
    else:
        provided_sig = signature_header

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_sig.lower(), provided_sig.lower())
    if not is_valid:
        logger.warning("Signature mismatch. Expected %s, received %s", expected_sig, provided_sig)
    return is_valid
