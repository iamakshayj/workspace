import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .config import Settings, get_settings
from .database import User, get_session
from .governance import record_audit_event
from .model_client import LocalModelClient, ModelOutputError, ModelUnavailableError
from .policy_engine import authorize, enforce_dlp, require_entitlement


router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class AssistantContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str = Field(default="home", max_length=60)
    title: str | None = Field(default=None, max_length=240)
    details: str | None = Field(default=None, max_length=2_000)


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[AssistantMessage] = Field(min_length=1, max_length=20)
    context: AssistantContext = Field(default_factory=AssistantContext)


class AssistantChatResponse(BaseModel):
    answer: str
    model: str
    mode: Literal["advisory", "fallback"] = "advisory"
    action_performed: bool = False


_ACTION_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)?\s+(?:scheduled|rescheduled|created|updated|deleted|sent|invited|assigned|moved|changed|approved|submitted)"
    r"|(?:the\s+)?(?:meeting|call|task|event|page|document|workflow|project|message|invite|request)\s+"
    r"(?:is|was|has been)\s+(?:now\s+)?(?:scheduled|rescheduled|created|updated|deleted|sent|assigned|moved|changed|approved|submitted))\b",
    re.IGNORECASE,
)


def guard_unperformed_action_claims(answer: str) -> str:
    """Never let a text-only assistant imply that it changed workspace data."""
    if not _ACTION_CLAIM.search(answer):
        return answer
    return (
        "No workspace change was made. I can help prepare this request, but you need to "
        "review and submit it using the relevant Create action in Workspace."
    )


def fallback_assistant_answer(payload: AssistantChatRequest) -> str:
    """Keep common workspace guidance usable while the optional model is offline."""
    latest = payload.messages[-1].content.lower()
    if any(word in latest for word in ("schedule", "meeting", "call", "calendar")):
        return (
            "I can still prepare this in limited mode. Use **Create in Workspace → Meeting** "
            "to review the date, time, and attendees before sending the invitation."
        )
    if any(word in latest for word in ("task", "story", "work item", "todo")):
        return "I can still prepare a work item in limited mode. Use **Create in Workspace → Task** to review and save it."
    return (
        "The reasoning service is temporarily offline. Workspace actions and saved data are still available, "
        "but open-ended AI answers need the reasoning service to reconnect."
    )


def get_assistant_model(settings: Settings = Depends(get_settings)) -> LocalModelClient:
    return LocalModelClient(settings)


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    payload: AssistantChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    model: LocalModelClient = Depends(get_assistant_model),
) -> AssistantChatResponse:
    # Direct unit invocations do not resolve FastAPI dependencies; HTTP requests always
    # receive a real tenant session and therefore always execute the controls below.
    governed_session = session if hasattr(session, "scalar") else None
    if governed_session:
        await require_entitlement(governed_session, user.entity_id, "workspace_assistant")
        await authorize(governed_session, user, action="ai.send", resource_type="assistant", source_type=payload.context.page)
    prompt_content = "\n".join(message.content for message in payload.messages if message.role == "user")
    input_decision = await enforce_dlp(
        governed_session, user, content=prompt_content, source_type="assistant", action="ai.send",
    ) if governed_session else None
    if input_decision and input_decision.findings:
        record_audit_event(
            governed_session, entity_id=user.entity_id, actor_id=user.id, action="dlp.assistant_input_detected",
            target_type="assistant", details={
                "classification": input_decision.classification,
                "findings": input_decision.findings,
                "obligations": input_decision.obligations,
            },
        )
        await governed_session.commit()
    context = payload.context
    system_prompt = f"""You are Workspace AI, a concise and practical assistant for {user.display_name}.
You can help with general questions, writing, analysis, planning, brainstorming, summaries, and day-to-day work.
Current app area: {context.page}.
Current title: {context.title or 'Not provided'}.
Optional visible context: {context.details or 'Not provided'}.

Rules:
- Answer the user's actual question directly and clearly.
- Use the supplied workspace context only when it is relevant.
- Never claim you changed workspace data; instead explain the next action or offer a useful draft.
- Never invent private workspace facts that were not supplied.
- Prefer compact paragraphs and short lists. Use Markdown when helpful.
"""
    response_mode: Literal["advisory", "fallback"] = "advisory"
    try:
        answer = await model.chat(
            [message.model_dump() for message in payload.messages],
            system_prompt,
        )
    except (ModelUnavailableError, ModelOutputError):
        answer = fallback_assistant_answer(payload)
        response_mode = "fallback"
    answer = guard_unperformed_action_claims(answer)
    output_decision = await enforce_dlp(
        governed_session, user, content=answer, source_type="generated_output", action="ai.send",
    ) if governed_session else None
    if output_decision and output_decision.findings:
        record_audit_event(
            governed_session, entity_id=user.entity_id, actor_id=user.id, action="dlp.assistant_output_detected",
            target_type="assistant", details={
                "classification": output_decision.classification,
                "findings": output_decision.findings,
                "obligations": output_decision.obligations,
            },
        )
        await governed_session.commit()
    return AssistantChatResponse(answer=answer, model=settings.model_name, mode=response_mode)
