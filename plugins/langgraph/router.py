"""Router — LangGraph example plugin."""

from __future__ import annotations

from typing import TypedDict

from backend.core.bridged_agent import LangGraphBridge


class _State(TypedDict):
    input: str
    output: str


class RouterAgent(LangGraphBridge):
    name = "Router"
    role = "router"
    capabilities = ["routing", "classification"]
    description = "LangGraph 示例：任务分类路由"
    inputs = ["task_description"]
    outputs = ["route_decision"]
    accepts = ["assignment_start"]

    async def build_graph(self):
        from langgraph.graph import END, START, StateGraph

        def classify(state: _State) -> _State:
            text = state["input"].lower()
            if any(k in text for k in ("image", "ocr", "vision", "图片", "识别")):
                route = "vision"
            elif any(k in text for k in ("code", "api", "服务", "实现")):
                route = "coder"
            else:
                route = "research"
            return {"output": f"Route → {route}\nTask: {state['input'][:200]}"}

        graph = StateGraph(_State)
        graph.add_node("classify", classify)
        graph.add_edge(START, "classify")
        graph.add_edge("classify", END)
        return graph.compile()
