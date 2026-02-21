from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.router.router import get_profile


async def load_profile_node(state) -> dict:
    profile = get_profile(state["user_id"])
    return {"profile_slug": profile["slug"]}


async def call_llm_node(state) -> dict:
    profile = get_profile(state["user_id"])
    llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY)
    msgs = [
        SystemMessage(content=profile["persona"]),
        HumanMessage(content=state["incoming_text"]),
    ]
    resp = await llm.ainvoke(msgs)
    return {"response_text": resp.content}
