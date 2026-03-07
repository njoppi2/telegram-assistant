import operator
from typing import Annotated, TypedDict, Union


class AgentState(TypedDict):
    user_id: str
    username: str
    profile_slug: str
    profile_persona: str
    profile_capabilities: list[str]
    messages: Annotated[list[dict[str, str]], operator.add]
    incoming_text: str
    response_text: str
    intent: str
    study_session: dict | None
