"""
graph.py — Supervisor Orchestrator
Sprint 1: Implement AgentState, supervisor_node, route_decision và kết nối graph.

Kiến trúc:
    Input → Supervisor → [retrieval_worker | policy_tool_worker | human_review] → synthesis → Output

Chạy thử:
    python graph.py
"""

import json
import os
import time
from datetime import datetime
from typing import TypedDict, Literal, Optional

from langgraph.graph import StateGraph, END

# ─────────────────────────────────────────────
# 1. Shared State — dữ liệu đi xuyên toàn graph
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    # Input
    task: str                           # Câu hỏi đầu vào từ user

    # Supervisor decisions
    route_reason: str                   # Lý do route sang worker nào
    risk_high: bool                     # True → cần HITL hoặc human_review
    needs_tool: bool                    # True → cần gọi external tool qua MCP
    hitl_triggered: bool                # True → đã pause cho human review

    # Worker outputs
    retrieved_chunks: list              # Output từ retrieval_worker
    retrieved_sources: list             # Danh sách nguồn tài liệu
    policy_result: dict                 # Output từ policy_tool_worker
    mcp_tools_used: list                # Danh sách MCP tools đã gọi

    # Final output
    final_answer: str                   # Câu trả lời tổng hợp
    sources: list                       # Sources được cite
    confidence: float                   # Mức độ tin cậy (0.0 - 1.0)

    # Trace & history
    history: list                       # Lịch sử các bước đã qua
    workers_called: list                # Danh sách workers đã được gọi
    worker_io_logs: list                # Log input/output của từng worker
    supervisor_route: str               # Worker được chọn bởi supervisor
    latency_ms: Optional[int]           # Thời gian xử lý (ms)
    run_id: str                         # ID của run này
    start_time: Optional[float]          # Timestamp bắt đầu run


def make_initial_state(task: str) -> AgentState:
    """Khởi tạo state cho một run mới."""
    return {
        "task": task,
        "route_reason": "",
        "risk_high": False,
        "needs_tool": False,
        "hitl_triggered": False,
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "policy_result": {},
        "mcp_tools_used": [],
        "final_answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": [],
        "workers_called": [],
        "worker_io_logs": [],
        "supervisor_route": "",
        "latency_ms": None,
        "run_id": f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
        "start_time": None,
    }


# ─────────────────────────────────────────────
# 2. Supervisor Node — quyết định route
# ─────────────────────────────────────────────

def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor phân tích task và quyết định:
    1. Route sang worker nào
    2. Có cần MCP tool không
    3. Có risk cao cần HITL không

    TODO Sprint 1: Implement routing logic dựa vào task keywords.
    """
    task = state["task"].lower()
    state["history"].append(f"[supervisor] received task: {state['task'][:80]}")

    # --- TODO: Implement routing logic ---
    # Gợi ý:
    # - "hoàn tiền", "refund", "flash sale", "license" → policy_tool_worker
    # - "cấp quyền", "access level", "level 3", "emergency" → policy_tool_worker
    # - "P1", "escalation", "sla", "ticket" → retrieval_worker
    # - mã lỗi không rõ (ERR-XXX), không đủ context → human_review
    # - còn lại → retrieval_worker

    route = "retrieval_worker"         # TODO: thay bằng logic thực
    route_reason = "default route"    # TODO: thay bằng lý do thực
    needs_tool = False
    risk_high = False

    # Ví dụ routing cơ bản — nhóm phát triển thêm:
    policy_keywords = [
        "hoàn tiền", "refund", "flash sale", "license", "subscription",
        "cấp quyền", "quyền", "access", "level 2", "level 3", "level 4",
        "admin access", "contractor",
    ]
    retrieval_keywords = ["p1", "sla", "ticket", "escalation", "remote", "vpn", "mật khẩu", "password"]
    risk_keywords = ["emergency", "khẩn cấp", "2am", "không rõ", "err-"]

    policy_hits = [kw for kw in policy_keywords if kw in task]
    retrieval_hits = [kw for kw in retrieval_keywords if kw in task]
    risk_hits = [kw for kw in risk_keywords if kw in task]

    if policy_hits:
        route = "policy_tool_worker"
        route_reason = f"policy/access keywords matched: {', '.join(policy_hits[:3])}"
        needs_tool = True
    elif retrieval_hits:
        route = "retrieval_worker"
        route_reason = f"retrieval keywords matched: {', '.join(retrieval_hits[:3])}"
    else:
        route = "retrieval_worker"
        route_reason = "no policy/access keyword; default to retrieval_worker"

    if risk_hits:
        risk_high = True
        route_reason += f" | risk_high keywords: {', '.join(risk_hits[:3])}"

    # Human review override
    if risk_high and "err-" in task:
        route = "human_review"
        route_reason = "unknown error code + risk_high → human review"

    state["supervisor_route"] = route
    state["needs_tool"] = needs_tool
    state["risk_high"] = risk_high
    route_reason += " | MCP enabled" if needs_tool else " | MCP not needed"
    state["route_reason"] = route_reason
    state["history"].append(f"[supervisor] route={route} reason={route_reason}")

    return state


# ─────────────────────────────────────────────
# 3. Route Decision — conditional edge
# ─────────────────────────────────────────────

def route_decision(state: AgentState) -> Literal["retrieval_worker", "policy_tool_worker", "human_review"]:
    """
    Trả về tên worker tiếp theo dựa vào supervisor_route trong state.
    Đây là conditional edge của graph.
    """
    route = state.get("supervisor_route", "retrieval_worker")
    return route  # type: ignore


def route_after_policy(state: AgentState) -> Literal["retrieval_worker", "synthesis_worker"]:
    """
    Policy worker có thể cần retrieval evidence trước khi phân tích lần cuối.
    Nếu chưa có retrieved_chunks thì đi lấy retrieval, còn đã có context thì synthesize.
    """
    if not state.get("retrieved_chunks"):
        return "retrieval_worker"
    return "synthesis_worker"


def route_after_retrieval(state: AgentState) -> Literal["policy_tool_worker", "synthesis_worker"]:
    """
    Nếu supervisor ban đầu chọn policy và retrieval vừa bổ sung context,
    quay lại policy một lần để policy_result dùng evidence mới.
    """
    policy_calls = state.get("workers_called", []).count("policy_tool_worker")
    if (
        state.get("supervisor_route") == "policy_tool_worker"
        and state.get("retrieved_chunks")
        and policy_calls == 1
    ):
        return "policy_tool_worker"
    return "synthesis_worker"


# ─────────────────────────────────────────────
# 4. Human Review Node — HITL placeholder
# ─────────────────────────────────────────────

def human_review_node(state: AgentState) -> AgentState:
    """
    HITL node: pause và chờ human approval.
    Trong lab này, implement dưới dạng placeholder (in ra warning).

    TODO Sprint 3 (optional): Implement actual HITL với interrupt_before hoặc
    breakpoint nếu dùng LangGraph.
    """
    state["hitl_triggered"] = True
    state["history"].append("[human_review] HITL triggered — awaiting human input")
    state["workers_called"].append("human_review")

    # Placeholder: tự động approve để pipeline tiếp tục
    print(f"\n⚠️  HITL TRIGGERED")
    print(f"   Task: {state['task']}")
    print(f"   Reason: {state['route_reason']}")
    print(f"   Action: Auto-approving in lab mode (set hitl_triggered=True)\n")

    # Sau khi human approve, route về retrieval để lấy evidence
    state["supervisor_route"] = "retrieval_worker"
    state["route_reason"] += " | human approved → retrieval"

    return state


# ─────────────────────────────────────────────
# 5. Import Workers
# ─────────────────────────────────────────────

# TODO Sprint 2: Uncomment sau khi implement workers
from workers.retrieval import run as retrieval_run
from workers.policy_tool import run as policy_tool_run
from workers.synthesis import run as synthesis_run


def retrieval_worker_node(state: AgentState) -> AgentState:
    """Wrapper gọi retrieval worker."""
    # TODO Sprint 2: Thay bằng retrieval_run(state)
    return retrieval_run(state)


def policy_tool_worker_node(state: AgentState) -> AgentState:
    """Wrapper gọi policy/tool worker."""
    # TODO Sprint 2: Thay bằng policy_tool_run(state)
    return policy_tool_run(state)


def synthesis_worker_node(state: AgentState) -> AgentState:
    """Wrapper gọi synthesis worker."""
    # TODO Sprint 2: Thay bằng synthesis_run(state)
    return synthesis_run(state)


def start_timer_node(state: AgentState) -> AgentState:
    """Ghi thời điểm bắt đầu để finish node tính latency cho LangGraph."""
    state["start_time"] = time.time()
    return state


def finish_node(state: AgentState) -> AgentState:
    """Ghi latency và history cuối run."""
    start = state.get("start_time")
    if start is not None:
        state["latency_ms"] = int((time.time() - start) * 1000)
    else:
        state["latency_ms"] = 0
    state["history"].append(f"[graph] completed in {state['latency_ms']}ms")
    return state


# ─────────────────────────────────────────────
# 6. Build Graph
# ─────────────────────────────────────────────

def build_graph():
    """
    Xây dựng graph với supervisor-worker pattern.

    LangGraph StateGraph:
    start_timer → supervisor → [retrieval_worker | policy_tool_worker | human_review]
    retrieval_worker → [policy_tool_worker | synthesis_worker]
    policy_tool_worker → [retrieval_worker | synthesis_worker]
    human_review → retrieval_worker
    synthesis_worker → finish → END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("start_timer", start_timer_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("retrieval_worker", retrieval_worker_node)
    workflow.add_node("policy_tool_worker", policy_tool_worker_node)
    workflow.add_node("synthesis_worker", synthesis_worker_node)
    workflow.add_node("finish", finish_node)

    workflow.set_entry_point("start_timer")
    workflow.add_edge("start_timer", "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        route_decision,
        {
            "retrieval_worker": "retrieval_worker",
            "policy_tool_worker": "policy_tool_worker",
            "human_review": "human_review",
        },
    )
    workflow.add_edge("human_review", "retrieval_worker")
    workflow.add_conditional_edges(
        "retrieval_worker",
        route_after_retrieval,
        {
            "policy_tool_worker": "policy_tool_worker",
            "synthesis_worker": "synthesis_worker",
        },
    )
    workflow.add_conditional_edges(
        "policy_tool_worker",
        route_after_policy,
        {
            "retrieval_worker": "retrieval_worker",
            "synthesis_worker": "synthesis_worker",
        },
    )
    workflow.add_edge("synthesis_worker", "finish")
    workflow.add_edge("finish", END)

    return workflow.compile()


# ─────────────────────────────────────────────
# 7. Public API
# ─────────────────────────────────────────────

_graph = build_graph()


def run_graph(task: str) -> AgentState:
    """
    Entry point: nhận câu hỏi, trả về AgentState với full trace.

    Args:
        task: Câu hỏi từ user

    Returns:
        AgentState với final_answer, trace, routing info, v.v.
    """
    state = make_initial_state(task)
    result = _graph.invoke(state)
    return result


def save_trace(state: AgentState, output_dir: str = "./artifacts/traces") -> str:
    """Lưu trace ra file JSON."""
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{state['run_id']}.json")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return filename
    except PermissionError as e:
        print(f"WARNING: Could not save trace to {filename}: {e}")
        return ""


# ─────────────────────────────────────────────
# 8. Manual Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Day 09 Lab — Supervisor-Worker Graph")
    print("=" * 60)

    test_queries = [
        "SLA xử lý ticket P1 là bao lâu?",
        "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
        "Cần cấp quyền Level 3 để khắc phục P1 khẩn cấp. Quy trình là gì?",
    ]

    for query in test_queries:
        print(f"\n▶ Query: {query}")
        result = run_graph(query)
        print(f"  Route   : {result['supervisor_route']}")
        print(f"  Reason  : {result['route_reason']}")
        print(f"  Workers : {result['workers_called']}")
        print(f"  Answer  : {result['final_answer'][:100]}...")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Latency : {result['latency_ms']}ms")

        # Lưu trace
        trace_file = save_trace(result)
        if trace_file:
            print(f"  Trace saved → {trace_file}")
        else:
            print("  Trace not saved")

    print("\n✅ graph.py test complete. Implement TODO sections in Sprint 1 & 2.")
