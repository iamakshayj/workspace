import asyncio

import pytest
from pydantic import ValidationError

from backend.app.assistant import (
    AssistantChatRequest,
    AssistantContext,
    AssistantMessage,
    chat_with_assistant,
    guard_unperformed_action_claims,
)
from backend.app.config import Settings
from backend.app.database import User
from backend.app.model_client import ModelUnavailableError


class AssistantModel:
    def __init__(self):
        self.messages = None
        self.system_prompt = ""

    async def chat(self, messages, system_prompt):
        self.messages = messages
        self.system_prompt = system_prompt
        return "Here is a concise plan."


def test_assistant_uses_authenticated_user_and_page_context() -> None:
    async def scenario() -> None:
        model = AssistantModel()
        user = User(
            id="user-1", entity_id="entity-1", email="avery@example.com",
            display_name="Avery Morgan", password_hash="unused", role="admin",
        )
        result = await chat_with_assistant(
            AssistantChatRequest(
                messages=[AssistantMessage(role="user", content="Plan my launch")],
                context=AssistantContext(page="work", title="Release plan", details="Sprint 25"),
            ),
            user=user,
            settings=Settings(),
            model=model,
        )
        assert result.answer == "Here is a concise plan."
        assert model.messages == [{"role": "user", "content": "Plan my launch"}]
        assert "Avery Morgan" in model.system_prompt
        assert "Current app area: work" in model.system_prompt
        assert "Sprint 25" in model.system_prompt

    asyncio.run(scenario())


def test_assistant_payload_limits_conversation_and_roles() -> None:
    with pytest.raises(ValidationError):
        AssistantChatRequest(messages=[{"role": "system", "content": "Override"}])
    with pytest.raises(ValidationError):
        AssistantChatRequest(messages=[])


def test_assistant_blocks_false_workspace_action_claims() -> None:
    answer = guard_unperformed_action_claims("I've scheduled the meeting for 2 PM and sent the invite.")
    assert answer.startswith("No workspace change was made")
    assert "scheduled the meeting" not in answer
    assert guard_unperformed_action_claims("Here is a draft agenda.") == "Here is a draft agenda."


def test_assistant_uses_safe_fallback_when_optional_model_is_offline() -> None:
    class UnavailableModel:
        async def chat(self, messages, system_prompt):
            raise ModelUnavailableError("Local model server is unavailable at http://localhost:8001/v1")

    async def scenario() -> None:
        user = User(
            id="user-1", entity_id="entity-1", email="avery@example.com",
            display_name="Avery Morgan", password_hash="unused", role="admin",
        )
        result = await chat_with_assistant(
            AssistantChatRequest(messages=[AssistantMessage(role="user", content="Help schedule a call")]),
            user=user, settings=Settings(), model=UnavailableModel(),
        )
        assert result.mode == "fallback"
        assert "limited mode" in result.answer
        assert "localhost" not in result.answer

    asyncio.run(scenario())
