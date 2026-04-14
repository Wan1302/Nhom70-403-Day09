# Báo Cáo Nhóm — Lab Day 09: Multi-Agent Orchestration

**Tên nhóm:** Nhóm 70  
**Thành viên:**
| Tên | Vai trò | Email |
|-----|---------|-------|
| Hồ Trọng Duy Quang | Supervisor Owner + Worker Owner (retrieval, synthesis) | [email] |
| Hồ Đắc Toàn | Worker Owner (policy_tool) + MCP Owner | [email] |
| Hồ Trần Đình Nguyên | Trace & Docs Owner | [email] |

**Ngày nộp:** 2026-04-14  
**Repo:** Nhom70-403-Day09  
**Độ dài khuyến nghị:** 600–1000 từ

---

## 1. Kiến trúc nhóm đã xây dựng

**Hệ thống tổng quan:**

Nhóm xây dựng hệ thống Supervisor-Worker gồm 4 thành phần chính chạy trên LangGraph `StateGraph`: (1) `supervisor_node` — phân tích câu hỏi và quyết định route, (2) `retrieval_worker` — tìm kiếm evidence từ ChromaDB bằng embedding `all-MiniLM-L6-v2`, (3) `policy_tool_worker` — kiểm tra policy và gọi MCP tools khi cần, (4) `synthesis_worker` — tổng hợp câu trả lời có citation bằng GPT-4o với confidence được đánh giá bởi LLM-as-Judge. Toàn bộ state chia sẻ qua `AgentState` (TypedDict) gồm 17 fields, mỗi worker chỉ đọc/ghi các fields trong contract của mình (`contracts/worker_contracts.yaml`).

**Routing logic cốt lõi:**

Supervisor dùng keyword matching hai chiều. Nếu task chứa các từ thuộc `policy_keywords` (hoàn tiền, refund, flash sale, cấp quyền, access level, contractor...) → route sang `policy_tool_worker` và set `needs_tool=True`. Nếu task chứa `retrieval_keywords` (P1, SLA, ticket, escalation, remote, VPN...) → route sang `retrieval_worker`. Nếu phát hiện `risk_keywords` (emergency, 2am, ERR-) → set `risk_high=True`. Kết quả thực tế trên 15 test questions: 8/15 (53%) route sang `retrieval_worker`, 7/15 (46%) sang `policy_tool_worker`, 0 câu vào `human_review`.

**MCP tools đã tích hợp:**

- `search_kb`: Semantic search ChromaDB, trả về top-k chunks — gọi khi `needs_tool=True` và `retrieved_chunks` trống. Được gọi 7/15 lần trong test run.
- `get_ticket_info`: Tra cứu thông tin ticket P1 (mock data) — trả về escalation status, SLA deadline, notifications sent.
- `check_access_permission`: Kiểm tra điều kiện cấp quyền Level 1–4, bao gồm emergency override — được gọi cho câu hỏi access control.
- `create_ticket`: Tạo ticket Jira mới (mock) — tool thứ 4 trong registry.

Ví dụ trace có MCP call (run_20260414_165717): task "Ai phải phê duyệt để cấp quyền Level 3?" → `policy_tool_worker` gọi `search_kb(query, top_k=3)` → trả về 3 chunks từ `access_control_sop.txt`, confidence 0.95.

---

## 2. Quyết định kỹ thuật quan trọng nhất

**Quyết định:** Dùng LLM-as-Judge (GPT-4o) thay cho heuristic cosine score để tính confidence.

**Bối cảnh vấn đề:**

Ban đầu `synthesis_worker` tính confidence bằng công thức heuristic: `0.2 + 0.75 × (0.7 × top_score + 0.3 × avg_score)`. Kết quả là mọi câu trả lời đều cho confidence trong khoảng 0.55–0.72 bất kể chất lượng thực tế — pipeline không phân biệt được câu tốt với câu yếu. Day 08 baseline cho avg_confidence = 0.661 với cùng heuristic.

**Các phương án đã cân nhắc:**

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|-----------|
| Heuristic cosine score | Nhanh, không tốn API call | Không phân biệt chất lượng ngữ nghĩa, luôn cho ~0.6 |
| Rule-based (keyword presence) | Dễ implement, transparent | Brittle, không xử lý được paraphrase |
| LLM-as-Judge (GPT-4o) | Đánh giá ngữ nghĩa chính xác, phân biệt câu tốt/yếu | Thêm latency ~200–400ms, thêm 1 API call |

**Phương án đã chọn và lý do:**

Nhóm chọn LLM-as-Judge vì mục tiêu chính của confidence score là phát hiện câu trả lời cần HITL hoặc retry — heuristic không làm được điều này. Với `max_tokens=5` và `temperature=0`, overhead chỉ ~200–400ms và chi phí API rất thấp. Có shortcut: không có evidence → trả ngay `0.10`, abstain answer → trả ngay `0.25` mà không gọi LLM.

**Bằng chứng từ trace/code:**

```
# Grading run — so sánh confidence theo câu:
gq03 (Level 3 access, answer có đủ 3 approvers): conf = 0.90  ← judge nhận ra tốt
gq05 (P1 escalation rule):                        conf = 0.90  ← đúng và grounded
gq04 (store credit %):                             conf = 0.10  ← judge phát hiện answer yếu
gq07 (mức phạt tài chính — abstain):              conf = 0.25  ← judge nhận ra đúng là abstain
gq09 (multi-hop P1 + Level 2):                    conf = 0.50  ← judge biết answer chỉ partial

# Heuristic cũ sẽ cho tất cả: ~0.58–0.68 (không phân biệt được)
```

Kết quả: avg_confidence Day 09 = 0.573 thấp hơn Day 08 = 0.661, nhưng đây là tín hiệu trung thực hơn, không phải pipeline kém đi.

---

## 3. Kết quả grading questions

**Tổng điểm raw ước tính:** Chờ giảng viên chấm chính thức.

**Câu pipeline xử lý tốt nhất:**

- **gq03** (conf=0.90) — "Engineer cần Level 3 access, bao nhiêu người phê duyệt?" → `policy_tool_worker` gọi MCP `search_kb`, tìm đúng chunk từ `access_control_sop.txt` nêu đủ 3 approvers: Line Manager, IT Admin, IT Security.
- **gq05** (conf=0.90) — "P1 không phản hồi 10 phút, hệ thống làm gì?" → `retrieval_worker` tìm đúng SLA rule, answer nêu đúng "tự động escalate lên Senior Engineer".
- **gq10** (conf=0.90) — "Flash Sale + lỗi nhà sản xuất" → `policy_tool_worker` phát hiện đúng Flash Sale exception, kết luận không được hoàn tiền dù có lỗi nhà sản xuất.

**Câu pipeline fail hoặc partial:**

- **gq04** (conf=0.10) — "Store credit = bao nhiêu %?" → retrieval kéo được chunk nhưng answer yếu, judge cho 0.10. Root cause: câu hỏi rất cụ thể (1 con số) nhưng chunk được retrieve chứa nhiều thông tin lẫn lộn.
- **gq08** (conf=0.25) — "Đổi mật khẩu bao nhiêu ngày?" → route sang `retrieval_worker` đúng nhưng confidence thấp. Root cause: `it_helpdesk_faq.txt` không được retrieve với score cao vì query embedding không đủ sát.

**Câu gq07 (abstain):** Pipeline route sang `retrieval_worker` vì từ khóa "SLA P1". Synthesis worker gọi LLM với context từ `sla_p1_2026.txt` — file này không có thông tin mức phạt tài chính. Judge cho confidence 0.25, phản ánh đúng đây là câu cần abstain. Answer kỳ vọng: "Thông tin này không có trong tài liệu SLA nội bộ."

**Câu gq09 (multi-hop khó nhất):** Route sang `policy_tool_worker` (conf=0.50) vì chứa "Level 2 access". MCP `search_kb` được gọi để lấy thêm context. Tuy nhiên pipeline chỉ gọi 1 worker — không cross-reference đầy đủ cả SLA P1 notification lẫn access control emergency procedure trong cùng 1 run. Trace ghi `workers_called: ["policy_tool_worker", "synthesis_worker"]` — chỉ 1 worker thay vì 2. Đây là giới hạn của single-route architecture.

---

## 4. So sánh Day 08 vs Day 09 — Điều nhóm quan sát được

**Metric thay đổi rõ nhất (có số liệu):**

| Metric | Day 08 | Day 09 | Delta |
|--------|--------|--------|-------|
| avg_confidence | 0.661 | 0.573 | −0.088 |
| avg_latency | 2,886ms | 4,749ms | +1,863ms |
| Multi-hop accuracy | 0% (0/3) | TBD | — |
| Routing visibility | Không có | Có `route_reason` | — |

**Điều nhóm bất ngờ nhất:** LLM-as-Judge cho thấy Day 08 đã "inflate" confidence bằng heuristic — confidence 0.661 của Day 08 thực ra không phản ánh chất lượng thật. Khi dùng judge, nhiều câu chỉ đạt 0.10–0.25, cho thấy pipeline Day 08 có thể đã trả lời sai nhiều câu mà không biết. `multi_hop_accuracy = 0.0` ở Day 08 là bằng chứng.

**Trường hợp multi-agent không giúp ích:** Với câu hỏi đơn giản single-document (VD: gq05 "P1 escalation"), cả hai pipeline đều trả lời được. Multi-agent chỉ thêm ~1,863ms latency và 1–2 LLM calls mà không cải thiện accuracy. Với use case FAQ đơn giản thuần một domain, single-agent vẫn là lựa chọn tốt hơn.

---

## 5. Phân công và đánh giá nhóm

**Phân công thực tế:**

| Thành viên | Phần đã làm | Sprint |
|------------|-------------|--------|
| Hồ Trọng Duy Quang | `graph.py` (supervisor, routing logic, AgentState), `workers/retrieval.py`, `workers/synthesis.py` | Sprint 1, 2 |
| Hồ Đắc Toàn | `workers/policy_tool.py` (policy check, exception detection), `mcp_server.py` (4 MCP tools) | Sprint 2, 3 |
| Hồ Trần Đình Nguyên | `eval_trace.py`, `artifacts/traces/`, `artifacts/grading_run.jsonl`, `docs/`, `reports/` | Sprint 4 |

**Điều nhóm làm tốt:**

Phân chia module rõ ràng theo contract (`worker_contracts.yaml`) giúp 3 người làm song song mà không conflict. Worker contract được viết trước khi implement nên ít xảy ra mismatch input/output. MCP server tách biệt khỏi graph logic nên dễ test độc lập.

**Điều nhóm làm chưa tốt:**

Unicode encoding trên Windows terminal gây crash `graph.py` và `eval_trace.py` khi chạy trực tiếp (emoji trong `print()`). Vấn đề này không ảnh hưởng logic nhưng ảnh hưởng điểm Sprint 1 và Sprint 4. Ngoài ra, single-route architecture của supervisor không xử lý được multi-hop task cần 2 domain cùng lúc (gq09).

**Nếu làm lại:** Thống nhất `PYTHONIOENCODING=utf-8` từ đầu và dùng `logging` thay `print()` cho output có emoji. Implement sequential routing cho multi-hop task từ Sprint 1 thay vì để đến khi phát hiện vấn đề ở Sprint 4.

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì?

**1. Sequential routing cho multi-hop task:** Trace gq09 (conf=0.50) cho thấy câu hỏi span 2 domain (SLA + Access Control) chỉ được xử lý bởi 1 worker. Cần thêm route `"both_workers"` trong supervisor: gọi `retrieval_worker` trước để lấy SLA chunks, sau đó `policy_tool_worker` để lấy access policy, rồi merge trước khi synthesis.

**2. Abstain threshold cứng:** 4/10 grading câu có confidence ≤ 0.25. Nếu thêm rule `confidence < 0.3 → answer = "Không đủ thông tin..."` vào synthesis worker, pipeline sẽ abstain đúng cho gq07 và tránh penalty hallucination. Hiện tại judge biết câu yếu nhưng pipeline vẫn generate answer.

---

*File lưu tại: `reports/group_report.md`*  
*Commit sau 18:00 được phép theo SCORING.md*
