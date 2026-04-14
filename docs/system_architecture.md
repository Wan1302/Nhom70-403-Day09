# System Architecture — Lab Day 09

**Nhóm:** Nhóm 70  
**Ngày:** 2026-04-14  
**Version:** 1.0

---

## 1. Tổng quan kiến trúc

> Mô tả ngắn hệ thống của nhóm: chọn pattern gì, gồm những thành phần nào.

**Pattern đã chọn:** Supervisor-Worker (LangGraph StateGraph)  
**Lý do chọn pattern này (thay vì single agent):**

RAG pipeline Day 08 là monolith — retrieve và generate trong một hàm duy nhất. Khi pipeline trả lời sai, không thể xác định lỗi ở bước nào (retrieval quality? wrong policy? hallucination?). Supervisor-Worker pattern tách rõ trách nhiệm: supervisor chỉ quyết định routing, mỗi worker chỉ làm 1 việc, synthesis chỉ tổng hợp. Mỗi worker có thể test và debug độc lập mà không cần chạy toàn pipeline.

---

## 2. Sơ đồ Pipeline

> Vẽ sơ đồ pipeline dưới dạng text, Mermaid diagram, hoặc ASCII art.
> Yêu cầu tối thiểu: thể hiện rõ luồng từ input → supervisor → workers → output.

**Ví dụ (ASCII art):**
```
User Request
     │
     ▼
┌──────────────┐
│  Supervisor  │  ← route_reason, risk_high, needs_tool
└──────┬───────┘
       │
   [route_decision]
       │
  ┌────┴────────────────────┐
  │                         │
  ▼                         ▼
Retrieval Worker     Policy Tool Worker
  (evidence)           (policy check + MCP)
  │                         │
  └─────────┬───────────────┘
            │
            ▼
      Synthesis Worker
        (answer + cite)
            │
            ▼
         Output
```

**Sơ đồ thực tế của nhóm:**

```
User Request (task: str)
        │
        ▼
┌──────────────────────────────┐
│      supervisor_node()       │  graph.py
│  - keyword matching          │
│  - set route, risk_high,     │
│    needs_tool, route_reason  │
└──────────────┬───────────────┘
               │
          [route_decision()]
               │
    ┌──────────┴───────────────┐
    │                          │
    ▼                          ▼
retrieval_worker         policy_tool_worker
(workers/retrieval.py)   (workers/policy_tool.py)
- ChromaDB top-k=3       - gọi MCP search_kb
- all-MiniLM-L6-v2       - LLM policy check
- cosine similarity      - detect exceptions
    │                          │
    └──────────┬───────────────┘
               │
               ▼
        synthesis_worker
        (workers/synthesis.py)
        - GPT-4o, temp=0.1
        - grounded prompt
        - answer + [citation]
        - confidence 0.0–1.0
               │
               ▼
          Final Output
    (final_answer, sources,
     confidence, trace log)
```

**MCP Server** (`mcp_server.py`) là thành phần ngoài graph, được gọi từ `policy_tool_worker` khi `needs_tool=True`:
```
policy_tool_worker ──MCP call──► mcp_server.dispatch_tool()
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                   ▼
               search_kb      get_ticket_info    check_access_permission
              (ChromaDB)       (mock data)           (mock logic)
```

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích task, quyết định route sang worker nào, set risk_high và needs_tool |
| **Input** | `task: str` (câu hỏi đầu vào) |
| **Output** | `supervisor_route`, `route_reason`, `risk_high`, `needs_tool` |
| **Routing logic** | Keyword matching: policy_keywords → `policy_tool_worker`; retrieval_keywords → `retrieval_worker`; risk_keywords → set `risk_high=True` |
| **HITL condition** | `risk_high=True` và không có đủ context (triggered 1/15 lần trong test run) |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Query ChromaDB với task, trả về top-k chunks có relevance score cao nhất |
| **Embedding model** | `all-MiniLM-L6-v2` (SentenceTransformers, offline) |
| **Top-k** | 3 (mặc định, cấu hình qua `DEFAULT_TOP_K`) |
| **Distance metric** | Cosine similarity |
| **Stateless?** | Yes — không giữ state giữa các lần gọi |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Kiểm tra policy áp dụng, phát hiện exception case, gọi MCP tools khi `needs_tool=True` |
| **MCP tools gọi** | `search_kb` (chính), `check_access_permission` (khi liên quan access level) |
| **Exception cases xử lý** | Flash Sale (không hoàn tiền), Digital Product/license key (không hoàn tiền), Emergency access (cấp tạm thời 24h với Tech Lead approval) |
| **LLM** | GPT-4o-mini cho policy analysis (cost-efficient) |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | `gpt-4o` (configurable qua `OPENAI_MODEL` env var) |
| **Temperature** | 0.1 — thấp để đảm bảo grounded output |
| **Grounding strategy** | System prompt: "Answer only from the provided context. Do not add information not present." Citation bắt buộc `[source_file]` trong answer |
| **Abstain condition** | Hiện tại chưa implement threshold cứng — confidence thấp được ghi vào trace |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| `search_kb` | `query: str`, `top_k: int = 3` | `chunks: list`, `sources: list`, `total_found: int` |
| `get_ticket_info` | `ticket_id: str` | ticket priority, status, assignee, SLA deadline |
| `check_access_permission` | `access_level: int`, `requester_role: str`, `is_emergency: bool` | `can_grant: bool`, `approvers: list`, `process: str` |
| `create_ticket` | `priority: str`, `title: str`, `description: str` | `ticket_id`, `created_at`, `assigned_to` |

---

## 4. Shared State Schema

> Liệt kê các fields trong AgentState và ý nghĩa của từng field.

| Field | Type | Mô tả | Ai đọc/ghi |
|-------|------|-------|-----------|
| `task` | str | Câu hỏi đầu vào từ user | supervisor đọc |
| `supervisor_route` | str | Worker được chọn ("retrieval_worker" / "policy_tool_worker") | supervisor ghi, graph đọc để route |
| `route_reason` | str | Lý do route — keywords matched, MCP flag | supervisor ghi |
| `risk_high` | bool | True nếu task chứa risk keywords (emergency, 2am, ERR-) | supervisor ghi |
| `needs_tool` | bool | True nếu cần gọi MCP | supervisor ghi, policy_tool đọc |
| `hitl_triggered` | bool | True nếu pipeline pause cho human review | supervisor/policy_tool ghi |
| `retrieved_chunks` | list | Danh sách chunks từ ChromaDB (text, source, score, metadata) | retrieval ghi, synthesis đọc |
| `retrieved_sources` | list | Danh sách tên file nguồn | retrieval ghi |
| `policy_result` | dict | Kết quả policy check (policy_applies, exceptions_found, explanation) | policy_tool ghi, synthesis đọc |
| `mcp_tools_used` | list | Log các MCP tool calls đã thực hiện (tool, input, output, timestamp) | policy_tool ghi |
| `final_answer` | str | Câu trả lời tổng hợp có citation | synthesis ghi |
| `confidence` | float | Mức tin cậy 0.0–1.0 | synthesis ghi |
| `history` | list | Log text từng bước xử lý | tất cả workers append |
| `workers_called` | list | Sequence workers đã được gọi | mỗi worker append |
| `worker_io_logs` | list | Structured input/output log của từng worker | mỗi worker append |
| `latency_ms` | int | Tổng thời gian xử lý (ms) | graph ghi khi kết thúc |
| `run_id` | str | Unique ID của run (timestamp-based) | make_initial_state() ghi |

---

## 5. Lý do chọn Supervisor-Worker so với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi sai | Khó — không rõ lỗi ở đâu | Dễ hơn — test từng worker độc lập; trace ghi rõ từng bước |
| Thêm capability mới | Phải sửa toàn prompt | Thêm MCP tool (1 function) hoặc worker mới |
| Routing visibility | Không có | Có `route_reason` trong mỗi trace |
| Multi-hop | Một lần retrieve tất cả | MCP `search_kb` bổ sung thêm context theo domain |
| Cost | 1 LLM call/query | 2–3 LLM calls/query + MCP calls |
| Latency | ~2,886ms avg | ~3,531ms avg (+22%) |

**Quan sát từ thực tế lab:**

- ChromaDB `all-MiniLM-L6-v2` retrieval trả về top-k=3 nhưng thường chỉ 1–2 chunk thực sự liên quan. Một số chunk từ domain khác vẫn được kéo vào vì cosine similarity thấp nhưng vẫn vượt threshold.
- `route_reason` trong trace đủ để debug trong vòng 5 phút thay vì 30 phút phải đọc toàn bộ code.
- Policy worker gọi MCP chỉ khi `needs_tool=True` — 46% câu hỏi. 54% câu còn lại không tốn thêm latency cho MCP call.

---

## 6. Giới hạn và điểm cần cải tiến

1. **Single-route architecture**: Supervisor chỉ route sang 1 worker. Câu hỏi multi-intent (vừa cần SLA vừa cần access policy) không được xử lý đầy đủ — cần sequential chaining.
2. **Keyword matching brittle**: Nếu user dùng từ khác (VD: "quyền admin" thay vì "access level 4"), routing có thể sai. Cần LLM-based intent classifier hoặc fuzzy matching.
3. **Abstain chưa implement**: Cả hai pipeline không có khả năng trả về "không đủ thông tin". Synthesis luôn generate answer dù confidence thấp — tiềm ẩn hallucination risk.
