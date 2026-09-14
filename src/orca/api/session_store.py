from collections import OrderedDict

from orca.knowledge.models import SessionState


class SessionStore:
    def __init__(self, max_sessions: int = 256) -> None:
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._cache: dict[tuple[str, tuple[float, float]], dict] = {}
        self._max_sessions = max_sessions

    def get(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id)
            self._sessions[session_id] = state
        self._sessions.move_to_end(session_id)
        return state

    def save(self, state: SessionState) -> None:
        self._sessions[state.session_id] = state
        self._sessions.move_to_end(state.session_id)
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)

    def cached(self, key: tuple[str, tuple[float, float]]) -> dict | None:
        return self._cache.get(key)

    def cache(self, key: tuple[str, tuple[float, float]], response: dict) -> None:
        self._cache[key] = response
