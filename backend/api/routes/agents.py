"""Agent registry routes."""

from fastapi import APIRouter, Depends

from backend.auth import get_auth_context
from backend.platform import platform

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(get_auth_context)],
)


@router.get("")
async def list_agents():
    agents = []
    for info in platform.registry.list_agents():
        data = info.model_dump()
        data["runtime"] = platform.agent_runtimes.get(info.name, "native")
        agents.append(data)
    return {"agents": agents}


@router.get("/discover")
async def discover_agents(q: str, limit: int = 5):
    results = platform.registry.discover(q, limit=limit)
    return {
        "query": q,
        "agents": [
            {"agent": agent.model_dump(), "score": score}
            for agent, score in results
        ],
    }


@router.get("/capability/{capability}")
async def find_by_capability(capability: str):
    agents = platform.registry.find_by_capability(capability)
    return {"capability": capability, "agents": [a.model_dump() for a in agents]}


@router.get("/{name}")
async def get_agent(name: str):
    info = platform.registry.get(name)
    if not info:
        return {"error": f"Agent '{name}' not found"}
    memory = {}
    if name in platform.agents:
        memory = platform.agents[name].memory
    return {"agent": info.model_dump(), "memory": memory}
