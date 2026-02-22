from langgraph.graph import END, StateGraph

from src.agent.nodes import (
    detect_intent_node,
    handle_action_node,
    handle_query_node,
    load_profile_node,
)
from src.agent.state import AgentState


def route_by_intent(state: AgentState) -> str:
    if state.get("intent") == "query":
        return "handle_query"
    return "handle_action"


_g = StateGraph(AgentState)
_g.add_node("load_profile", load_profile_node)
_g.add_node("detect_intent", detect_intent_node)
_g.add_node("handle_query", handle_query_node)
_g.add_node("handle_action", handle_action_node)

_g.set_entry_point("load_profile")
_g.add_edge("load_profile", "detect_intent")
_g.add_conditional_edges(
    "detect_intent",
    route_by_intent,
    {"handle_query": "handle_query", "handle_action": "handle_action"},
)
_g.add_edge("handle_query", END)
_g.add_edge("handle_action", END)

agent_graph = _g.compile()
