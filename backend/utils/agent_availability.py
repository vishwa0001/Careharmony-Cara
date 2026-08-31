import os
import requests

AGENT_AVAILABILITY_API_URL = os.environ.get("AGENT_AVAILABILITY_API_URL", "http://mock-api/agent/availability")


def check_agent_availability(context: dict = {}) -> bool:
    """
    Returns True if a PES agent is available, False otherwise.
    Fail-safe: returns False on any error so caller falls back to Normal Cara Flow.
    """
    try:
        response = requests.get(AGENT_AVAILABILITY_API_URL, params=context, timeout=5)
        response.raise_for_status()
        return response.json().get("available", False)
    except Exception:
        return False
