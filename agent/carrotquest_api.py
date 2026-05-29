import requests

from .config import CQ_API_BASE


class CarrotQuestAPI:
    def __init__(self, auth_token: str, app_id: str):
        self.auth_token = auth_token
        self.app_id = app_id
        self._headers = {"Authorization": f"Token {auth_token}"}

    def get_user_events(self, user_id: str, limit: int = 50) -> list[dict]:
        resp = requests.get(
            f"{CQ_API_BASE}/users/{user_id}/events",
            headers=self._headers,
            params={"limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("events", [])

    def get_user(self, user_id: str) -> dict:
        resp = requests.get(
            f"{CQ_API_BASE}/users/{user_id}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def user_card_url(self, user_id: str) -> str:
        return f"https://app.carrotquest.io/apps/{self.app_id}/users/{user_id}"
