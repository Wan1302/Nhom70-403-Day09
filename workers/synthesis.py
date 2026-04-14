"""
workers/synthesis.py — Synthesis Worker
Sprint 2: Tổng hợp câu trả lời từ retrieved_chunks và policy_result.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: evidence từ retrieval_worker
    - policy_result: kết quả từ policy_tool_worker

Output (vào AgentState):
    - final_answer: câu trả lời cuối với citation
    - sources: danh sách nguồn tài liệu được cite
    - confidence: mức độ tin cậy (0.0 - 1.0)

Gọi độc lập để test:
    python workers/synthesis.py
"""

import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

WORKER_NAME = "synthesis_worker"

SYSTEM_PROMPT = """Bạn là trợ lý IT Helpdesk nội bộ.

Quy tắc nghiêm ngặt:
1. CHỈ trả lời dựa vào context được cung cấp. KHÔNG dùng kiến thức ngoài.
2. Nếu context không đủ để trả lời → nói rõ "Không đủ thông tin trong tài liệu nội bộ".
3. Trích dẫn nguồn cuối mỗi câu quan trọng: [tên_file].
4. Trả lời súc tích, có cấu trúc. Không dài dòng.
5. Nếu có exceptions/ngoại lệ → nêu rõ ràng trước khi kết luận.
"""


def _call_llm(messages: list) -> str:
    """
    Gọi LLM để tổng hợp câu trả lời.
    TODO Sprint 2: Implement với OpenAI hoặc Gemini.
    """
    # Option A: OpenAI
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key.startswith("sk-..."):
            return ""
        client = OpenAI(api_key=api_key, timeout=20)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=messages,
            temperature=0.1,  # Low temperature để grounded
            max_tokens=500,
        )
        return response.choices[0].message.content or ""
    except Exception:
        pass

    # Option B: Gemini
    # try:
    #     import google.generativeai as genai
    #     api_key = os.getenv("GOOGLE_API_KEY")
    #     if not api_key:
    #         return ""
    #     genai.configure(api_key=api_key)
    #     model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    #     combined = "\n".join([m["content"] for m in messages])
    #     response = model.generate_content(combined)
    #     return response.text or ""
    # except Exception:
    #     pass

    return ""

def _build_context(chunks: list, policy_result: dict, mcp_tools_used: list | None = None) -> str:
    """Xây dựng context string từ chunks và policy result."""
    parts = []

    if chunks:
        parts.append("=== TÀI LIỆU THAM KHẢO ===")
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("source", "unknown")
            text = chunk.get("text", "")
            score = chunk.get("score", 0)
            parts.append(f"[{i}] Nguồn: {source} (relevance: {score:.2f})\n{text}")

    if policy_result and policy_result.get("exceptions_found"):
        parts.append("\n=== POLICY EXCEPTIONS ===")
        for ex in policy_result["exceptions_found"]:
            parts.append(f"- {ex.get('rule', '')}")

    if policy_result and policy_result.get("policy_version_note"):
        parts.append("\n=== POLICY VERSION NOTE ===")
        parts.append(policy_result["policy_version_note"])

    if mcp_tools_used:
        parts.append("\n=== MCP TOOL OUTPUTS ===")
        for call in mcp_tools_used:
            parts.append(f"tool={call.get('tool')} output={call.get('output')} error={call.get('error')}")

    if not parts:
        return "(Không có context)"

    return "\n\n".join(parts)


def _source_list(chunks: list, policy_result: dict, mcp_tools_used: list | None = None) -> list:
    sources = []
    for chunk in chunks:
        source = chunk.get("source")
        if source and source not in sources:
            sources.append(source)

    policy_sources = policy_result.get("source", []) if policy_result else []
    if isinstance(policy_sources, str):
        policy_sources = [policy_sources]
    for source in policy_sources:
        if source and source not in sources:
            sources.append(source)

    for call in mcp_tools_used or []:
        output = call.get("output") or {}
        source = output.get("source")
        if source and source not in sources:
            sources.append(source)
        for source in output.get("sources", []) or []:
            if source and source not in sources:
                sources.append(source)

    return sources


def _extract_relevant_lines(text: str, query: str, limit: int = 4) -> list:
    query_terms = {
        token
        for token in re.findall(r"\w+", query.lower(), flags=re.UNICODE)
        if len(token) > 2
    }
    lines = [line.strip("- \t") for line in text.splitlines() if line.strip()]
    scored = []
    for line in lines:
        line_terms = set(re.findall(r"\w+", line.lower(), flags=re.UNICODE))
        score = len(query_terms & line_terms)
        if score:
            scored.append((score, line))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [line for _, line in scored[:limit]]
    return selected or lines[:limit]


def _summarize_mcp_tool(call: dict) -> list:
    tool = call.get("tool", "")
    output = call.get("output") or {}
    if call.get("error"):
        error = call["error"]
        return [f"MCP {tool} lỗi: {error.get('reason', error)}."]

    if tool == "get_ticket_info":
        bits = []
        if output.get("notifications_sent"):
            bits.append("Thông báo đã gửi qua " + ", ".join(output["notifications_sent"]))
        if output.get("escalated_to"):
            bits.append(f"đã escalate tới {output['escalated_to']}")
        if output.get("sla_deadline"):
            bits.append(f"SLA deadline: {output['sla_deadline']}")
        return [". ".join(bits) + "."] if bits else []

    if tool == "check_access_permission":
        bits = [
            f"Level {output.get('access_level')} cần approvers: {', '.join(output.get('required_approvers', []))}",
            f"emergency_override={output.get('emergency_override')}",
        ]
        bits.extend(output.get("notes", []) or [])
        return ["; ".join(str(bit) for bit in bits if bit) + "."]

    return []


def _fallback_answer(task: str, chunks: list, policy_result: dict, mcp_tools_used: list | None = None) -> str:
    sources = _source_list(chunks, policy_result, mcp_tools_used)
    primary_source = sources[0] if sources else "tài liệu nội bộ"

    if not chunks and not policy_result and not mcp_tools_used:
        return "Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này."

    lines = []
    policy_version_note = (policy_result or {}).get("policy_version_note")
    if policy_version_note:
        lines.append(f"{policy_version_note} [{primary_source}]")

    exceptions = (policy_result or {}).get("exceptions_found", [])
    for ex in exceptions:
        rule = ex.get("rule")
        source = ex.get("source") or primary_source
        if rule:
            lines.append(f"Ngoại lệ áp dụng: {rule} [{source}]")

    for call in mcp_tools_used or []:
        source = (call.get("output") or {}).get("source") or primary_source
        for item in _summarize_mcp_tool(call):
            lines.append(f"{item} [{source}]")

    for chunk in chunks[:2]:
        source = chunk.get("source", primary_source)
        for line in _extract_relevant_lines(chunk.get("text", ""), task, limit=3):
            entry = f"{line} [{source}]"
            if line and entry not in lines:
                lines.append(entry)
        if len(lines) >= 6:
            break

    if not lines:
        return "Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này."

    return "\n".join(f"- {line}" for line in lines[:6])


def _estimate_confidence(chunks: list, answer: str, policy_result: dict) -> float:
    """
    Ước tính confidence dựa vào:
    - Số lượng và quality của chunks
    - Có exceptions không
    - Answer có abstain không

    TODO Sprint 2: Có thể dùng LLM-as-Judge để tính confidence chính xác hơn.
    """
    if not chunks:
        if policy_result and (
            policy_result.get("exceptions_found")
            or policy_result.get("policy_applies") is not None
            or policy_result.get("policy_version_note")
        ):
            return 0.45
        return 0.1  # Không có evidence → low confidence

    if "Không đủ thông tin" in answer or "không có trong tài liệu" in answer.lower():
        return 0.3  # Abstain → moderate-low

    # Combine top relevance and average relevance so one good chunk can carry the answer.
    scores = [float(c.get("score", 0) or 0) for c in chunks]
    avg_score = sum(scores) / len(scores)
    top_score = max(scores)
    evidence_score = (0.7 * top_score) + (0.3 * avg_score)

    # If retrieval found chunks but the score is zero, keep it visibly low instead of hiding it.
    if evidence_score <= 0:
        confidence = 0.2
    else:
        confidence = 0.2 + (0.75 * evidence_score)

    # Penalty nếu có exceptions (phức tạp hơn)
    exception_penalty = 0.05 * len(policy_result.get("exceptions_found", []))

    confidence = min(0.95, confidence - exception_penalty)
    return round(max(0.1, confidence), 2)


def synthesize(task: str, chunks: list, policy_result: dict, mcp_tools_used: list | None = None) -> dict:
    """
    Tổng hợp câu trả lời từ chunks và policy context.

    Returns:
        {"answer": str, "sources": list, "confidence": float}
    """
    context = _build_context(chunks, policy_result, mcp_tools_used)

    # Build messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Câu hỏi: {task}

{context}

Hãy trả lời câu hỏi dựa vào tài liệu trên."""
        }
    ]

    answer = _call_llm(messages)
    if not answer:
        answer = _fallback_answer(task, chunks, policy_result, mcp_tools_used)
    sources = _source_list(chunks, policy_result, mcp_tools_used)
    confidence = _estimate_confidence(chunks, answer, policy_result)

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
    }


def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    policy_result = state.get("policy_result", {})
    mcp_tools_used = state.get("mcp_tools_used", [])

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "chunks_count": len(chunks),
            "has_policy": bool(policy_result),
            "mcp_calls": len(mcp_tools_used),
        },
        "output": None,
        "error": None,
    }

    try:
        result = synthesize(task, chunks, policy_result, mcp_tools_used)
        state["final_answer"] = result["answer"]
        state["sources"] = result["sources"]
        state["confidence"] = result["confidence"]

        worker_io["output"] = {
            "answer_length": len(result["answer"]),
            "sources": result["sources"],
            "confidence": result["confidence"],
        }
        state["history"].append(
            f"[{WORKER_NAME}] answer generated, confidence={result['confidence']}, "
            f"sources={result['sources']}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "SYNTHESIS_FAILED", "reason": str(e)}
        state["final_answer"] = f"SYNTHESIS_ERROR: {e}"
        state["confidence"] = 0.0
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


# ─────────────────────────────────────────────
# Test độc lập
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Synthesis Worker — Standalone Test")
    print("=" * 50)

    test_state = {
        "task": "SLA ticket P1 là bao lâu?",
        "retrieved_chunks": [
            {
                "text": "Ticket P1: Phản hồi ban đầu 15 phút kể từ khi ticket được tạo. Xử lý và khắc phục 4 giờ. Escalation: tự động escalate lên Senior Engineer nếu không có phản hồi trong 10 phút.",
                "source": "sla_p1_2026.txt",
                "score": 0.92,
            }
        ],
        "policy_result": {},
    }

    result = run(test_state.copy())
    print(f"\nAnswer:\n{result['final_answer']}")
    print(f"\nSources: {result['sources']}")
    print(f"Confidence: {result['confidence']}")

    print("\n--- Test 2: Exception case ---")
    test_state2 = {
        "task": "Khách hàng Flash Sale yêu cầu hoàn tiền vì lỗi nhà sản xuất.",
        "retrieved_chunks": [
            {
                "text": "Ngoại lệ: Đơn hàng Flash Sale không được hoàn tiền theo Điều 3 chính sách v4.",
                "source": "policy_refund_v4.txt",
                "score": 0.88,
            }
        ],
        "policy_result": {
            "policy_applies": False,
            "exceptions_found": [{"type": "flash_sale_exception", "rule": "Flash Sale không được hoàn tiền."}],
        },
    }
    result2 = run(test_state2.copy())
    print(f"\nAnswer:\n{result2['final_answer']}")
    print(f"Confidence: {result2['confidence']}")

    print("\n✅ synthesis_worker test done.")
