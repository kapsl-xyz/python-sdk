"""Kapsl HTTP client — deploy agents, create runs, stream events."""

import json
import logging
from typing import Any, Callable

import requests

from ._tool import _build_tool_defs, generate_tool_code

logger = logging.getLogger("kapsl")


class KapslError(Exception):
    """Error from the Kapsl API."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


def _default_on_event(event: dict) -> None:
    """Print step progress to stderr.

    Event shape: {"event": "<kind>", "data": {"id": ..., "run_id": ..., "step": N, "kind": "...", "data": {...}}}
    """
    kind = event.get("event", "")
    payload = event.get("data", {})
    step = payload.get("step", "")
    inner = payload.get("data", {})

    if kind == "step_started":
        logger.info("step %s", step)
    elif kind == "tool_call":
        logger.info("  tool: %s", inner.get("name", "?"))
    elif kind == "tool_result":
        name = inner.get("name", "?")
        ok = inner.get("ok", False)
        if ok:
            logger.info("  result: %s (ok)", name)
        else:
            logger.warning("  result: %s (error)", name)
    elif kind == "run_completed":
        logger.info("done")
    elif kind == "run_failed":
        logger.error("failed: %s", inner.get("error", "unknown error"))


class Run:
    """Handle to a running or completed run."""

    def __init__(self, data: dict, base_url: str):
        self.id: str = data["id"]
        self.status: str = data["status"]
        self.output: Any = data.get("output")
        self._data = data
        self._base_url = base_url

    def events(self):
        """Stream SSE events from the run. Yields dicts with 'event' and 'data' keys."""
        url = f"{self._base_url}/v1/runs/{self.id}/events"
        # read timeout only — no connect timeout so initial connection can take time,
        # but if no data arrives for 60s the stream is considered dead.
        resp = requests.get(url, stream=True, headers={"Accept": "text/event-stream"}, timeout=(10, 60))
        resp.raise_for_status()

        event_type = None
        data_buf = []

        for raw_line in resp.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue

            line = raw_line

            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
                continue

            if line.startswith("data:"):
                data_buf.append(line[len("data:"):].strip())
                continue

            if line.startswith(":"):
                # SSE comment / keepalive
                continue

            if line == "":
                # Empty line = event boundary
                if event_type and data_buf:
                    raw_data = "\n".join(data_buf)
                    try:
                        parsed = json.loads(raw_data)
                    except json.JSONDecodeError:
                        parsed = raw_data

                    event = {"event": event_type, "data": parsed}
                    yield event

                    if event_type in ("run_completed", "run_failed", "run_suspended"):
                        return

                event_type = None
                data_buf = []

    def refresh(self) -> "Run":
        """Re-fetch run state from the server."""
        resp = requests.get(f"{self._base_url}/v1/runs/{self.id}")
        if resp.status_code != 200:
            raise KapslError(resp.status_code, resp.text)
        data = resp.json()
        self.status = data["status"]
        self.output = data.get("output")
        self._data = data
        return self

    def wait(self, on_event: Callable[[dict], None] | None = _default_on_event) -> Any:
        """Block until the run reaches a terminal state. Returns the output.

        Args:
            on_event: Callback for each event. Pass None to suppress output.
                      Defaults to printing step progress to stderr.
        """
        for event in self.events():
            if on_event:
                on_event(event)
        self.refresh()
        return self.output


class Client:
    """Kapsl API client."""

    def __init__(self, base_url: str = "http://127.0.0.1:50051"):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error", resp.text)
            except Exception:
                msg = resp.text
            raise KapslError(resp.status_code, msg)
        return resp

    def deploy(self, agent) -> dict:
        """Deploy an agent to the runtime.

        Args:
            agent: An Agent instance with name, model, system, and tools.

        Returns:
            The created/updated agent dict from the API.
        """
        payload: dict[str, Any] = {
            "name": agent.name,
            "model": agent.model,
        }
        if agent.system:
            payload["system"] = agent.system
        if agent.tools:
            payload["tools"] = _build_tool_defs(agent.tools)
            payload["tool_code"] = generate_tool_code(agent.tools)
        if agent.requirements:
            payload["requirements"] = agent.requirements

        resp = self._request("POST", "/v1/agents", json=payload)
        return resp.json()

    def run(self, agent_name: str, input: Any, **overrides) -> Run:
        """Create a new run for a deployed agent.

        Args:
            agent_name: Name of the deployed agent.
            input: The input to send (string or JSON-serializable value).
            **overrides: Optional per-run overrides (model, system, tools, tool_code).

        Returns:
            A Run handle for streaming events and getting output.
        """
        payload: dict[str, Any] = {"agent": agent_name, "input": input}
        for key in ("model", "system", "tools", "tool_code"):
            if key in overrides:
                payload[key] = overrides[key]

        resp = self._request("POST", "/v1/runs", json=payload)
        return Run(resp.json(), self.base_url)

    def get_run(self, run_id: str) -> dict:
        """Fetch a run by ID."""
        return self._request("GET", f"/v1/runs/{run_id}").json()

    def list_runs(self) -> list[dict]:
        """List all runs."""
        return self._request("GET", "/v1/runs").json()

    def list_agents(self) -> list[dict]:
        """List all registered agents."""
        return self._request("GET", "/v1/agents").json()

    def dry_run(self, tool_code: str, name: str, input: dict) -> dict:
        """Execute a single tool call without creating a run.

        Args:
            tool_code: The complete Python tool script.
            name: Tool function name to call.
            input: Input dict for the tool.
        """
        payload = {"tool_code": tool_code, "name": name, "input": input}
        return self._request("POST", "/v1/tools/dry-run", json=payload).json()
