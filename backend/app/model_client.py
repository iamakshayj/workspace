import json
import logging
import re

import httpx
import json_repair

from .config import Settings
from .schemas import FlowGraph


logger = logging.getLogger("flowforge.model")


class ModelUnavailableError(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    pass


SYSTEM_PROMPT = """You are a process analyst. Convert the user's source text into a grounded flowchart.

Rules:
- Include only steps supported by the source. Never invent policies or actors.
- Use short, stable kebab-case node IDs.
- Use start/end for explicit boundaries, decision for questions or branches, and process otherwise.
- Every decision must have labeled outgoing edges.
- Mark backward edges with is_loop=true.
- Put genuine ambiguities in questions instead of guessing.
- Return only one JSON object. Do not use markdown or commentary.

Required JSON shape:
{
  "title": "Short process title",
  "nodes": [
    {"id": "stable-kebab-id", "label": "Short label", "type": "start|end|process|decision|document|external_system|wait|subprocess", "owner": null, "description": null, "color": null}
  ],
  "edges": [
    {"source": "node-id", "target": "node-id", "label": "", "is_loop": false, "bidirectional": false}
  ],
  "questions": []
}
"""


class LocalModelClient:
    """Direct HTTP client for vLLM's local OpenAI-compatible transport.

    This module intentionally does not import or call the OpenAI SDK or service.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def completion_url(self) -> str:
        return f"{self.settings.model_base_url.rstrip('/')}/chat/completions"

    async def is_reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{self.settings.model_base_url.rstrip('/')}/models",
                    headers=self._headers(),
                )
                return response.is_success
        except httpx.HTTPError:
            return False

    async def generate_graph(self, source_text: str, requested_title: str | None) -> FlowGraph:
        schema = FlowGraph.model_json_schema()
        user_content = f"/no_think\n\nSource text:\n{source_text}"
        if requested_title:
            user_content = f"/no_think\n\nPreferred title: {requested_title}\n\nSource text:\n{source_text}"

        response_format = {"type": "json_object"}
        if self.settings.model_response_format == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "flow_graph", "strict": True, "schema": schema},
            }

        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 2_048,
            "response_format": response_format,
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.model_timeout_seconds) as client:
                response = await client.post(self.completion_url, json=payload, headers=self._headers())
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ModelUnavailableError(
                f"Local model server is unavailable at {self.settings.model_base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ModelUnavailableError("Local model generation timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ModelUnavailableError(f"Local model server returned {exc.response.status_code}: {detail}") from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            raw_graph = json_repair.loads(content) if isinstance(content, str) else content
            return FlowGraph.model_validate(raw_graph)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Local model returned an invalid graph payload",
                extra={"event": "model.output.invalid"},
            )
            raise ModelOutputError("The local model returned an invalid flowchart payload") from exc

    async def chat(self, messages: list[dict[str, str]], system_prompt: str) -> str:
        """Return a plain-text assistant response from the locally hosted model."""
        conversation = [{"role": "system", "content": system_prompt}]
        conversation.extend(messages[:-1])
        conversation.append({
            "role": messages[-1]["role"],
            "content": f"/no_think\n\n{messages[-1]['content']}",
        })
        payload = {
            "model": self.settings.model_name,
            "messages": conversation,
            "temperature": 0.35,
            "max_tokens": 1_024,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.model_timeout_seconds) as client:
                response = await client.post(self.completion_url, json=payload, headers=self._headers())
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ModelUnavailableError(
                f"Local model server is unavailable at {self.settings.model_base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ModelUnavailableError("Local model response timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ModelUnavailableError(f"Local model server returned {exc.response.status_code}: {detail}") from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty completion")
            return re.sub(r"<think>[\s\S]*?</think>", "", content, flags=re.IGNORECASE).strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Local model returned an invalid assistant response", extra={"event": "model.chat.invalid"})
            raise ModelOutputError("The local model returned an invalid assistant response") from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.model_api_token}"}
