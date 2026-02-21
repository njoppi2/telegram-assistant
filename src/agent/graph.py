from langgraph.graph import END, StateGraph

from src.agent.nodes import call_llm_node, load_profile_node
from src.agent.state import AgentState


_g = StateGraph(AgentState)
_g.add_node("load_profile", load_profile_node)
_g.add_node("call_llm", call_llm_node)
_g.set_entry_point("load_profile")
_g.add_edge("load_profile", "call_llm")
_g.add_edge("call_llm", END)
agent_graph = _g.compile()
