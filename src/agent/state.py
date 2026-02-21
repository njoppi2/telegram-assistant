import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    user_id: str
    username: str
    profile_slug: str
    messages: Annotated[list[BaseMessage], operator.add]
    incoming_text: str
    response_text: str
