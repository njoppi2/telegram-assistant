from langgraph.graph import END, StateGraph

from src.agent.arch_study_node import arch_study_node, check_study_session_node
from src.agent.nodes import (
    direct_response_node,
    handle_action_node,
    handle_query_node,
    load_profile_node,
)
from src.agent.state import AgentState


def route_after_check(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "direct_response":
        return "direct_response"
    if intent == "arch_study":
        return "arch_study"
    if intent == "action":
        return "handle_action"
    return "handle_query"


_g = StateGraph(AgentState)
_g.add_node("load_profile", load_profile_node)
_g.add_node("check_study_session", check_study_session_node)
_g.add_node("direct_response", direct_response_node)
_g.add_node("arch_study", arch_study_node)
_g.add_node("handle_query", handle_query_node)
_g.add_node("handle_action", handle_action_node)

_g.set_entry_point("load_profile")
_g.add_edge("load_profile", "check_study_session")
_g.add_conditional_edges(
    "check_study_session",
    route_after_check,
    {
        "direct_response": "direct_response",
        "arch_study": "arch_study",
        "handle_action": "handle_action",
        "handle_query": "handle_query",
    },
)
_g.add_edge("direct_response", END)
_g.add_edge("arch_study", END)
_g.add_edge("handle_query", END)
_g.add_edge("handle_action", END)

agent_graph = _g.compile()
