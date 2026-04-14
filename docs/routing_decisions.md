# Routing Decisions Log — Lab Day 09

**Nhóm:** Nhóm 70  
**Ngày:** 2026-04-14

> Ghi lại các quyết định routing thực tế từ trace của nhóm (artifacts/traces/).
> Mỗi entry lấy trực tiếp từ trace file — không giả định.

---

## Routing Decision #1

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `retrieval keywords matched: p1, sla, ticket | MCP not needed`  
**MCP tools được gọi:** Không có  
**Workers called sequence:** `retrieval_worker` → `synthesis_worker`

**Kết quả thực tế:**
- final_answer (ngắn): "SLA xử lý ticket P1 là 4 giờ kể từ khi ticket được tạo [sla_p1_2026.txt]."
- confidence: 0.61
- latency_ms: 8318
- Correct routing? Yes

**Nhận xét:** Routing đúng. Task chứa các từ khóa `p1`, `sla`, `ticket` rõ ràng nên supervisor route sang `retrieval_worker` — không cần policy check. Retrieval tìm đúng file `sla_p1_2026.txt`. Confidence 0.61 khá thấp vì retrieval còn kéo thêm `policy_refund_v4.txt` không liên quan (top-k=3 lấy cả chunk lạc đề). Latency cao hơn bình thường (8318ms) do lần đầu khởi tạo ChromaDB connection.

---

## Routing Decision #2

**Task đầu vào:**
> "Ai phải phê duyệt để cấp quyền Level 3?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `policy/access keywords matched: cấp quyền, quyền, level 3 | MCP enabled`  
**MCP tools được gọi:** `search_kb(query="Ai phải phê duyệt để cấp quyền Level 3?", top_k=3)`  
**Workers called sequence:** `policy_tool_worker` → `synthesis_worker`

**Kết quả thực tế:**
- final_answer (ngắn): "Để cấp quyền Level 3, cần có sự phê duyệt từ Line Manager, IT Admin, và IT Security [access_control_sop.txt]."
- confidence: 0.65
- latency_ms: 3684
- Correct routing? Yes

**Nhận xét:** Routing đúng. Từ khóa `cấp quyền`, `level 3` khớp với policy_keywords nên supervisor kích hoạt `policy_tool_worker` và set `needs_tool=True`. MCP tool `search_kb` được gọi thành công, trả về đúng chunk từ `access_control_sop.txt`. Policy worker xác định `policy_applies=True`, không có exception. Answer chính xác và có citation. Đây là ví dụ điển hình của routing sang policy path với MCP.

---

## Routing Decision #3

**Task đầu vào:**
> "Ticket P1 được tạo lúc 22:47. Ai sẽ nhận thông báo đầu tiên và qua kênh nào? Escalation xảy ra lúc mấy giờ?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `retrieval keywords matched: p1, ticket, escalation | MCP not needed`  
**MCP tools được gọi:** Không có  
**Workers called sequence:** `retrieval_worker` → `synthesis_worker`

**Kết quả thực tế:**
- final_answer (ngắn): "On-call engineer nhận qua PagerDuty, thông báo tới Slack #incident-p1 và email incident@company.internal. Escalation xảy ra lúc 22:57 (sau 10 phút không phản hồi) [sla_p1_2026.txt]."
- confidence: 0.68
- latency_ms: 2092
- Correct routing? Yes

**Nhận xét:** Đây là câu hỏi multi-hop — phải kết hợp thông tin từ nhiều chunk (SLA timeline + escalation rule + kênh liên lạc). Routing sang `retrieval_worker` đúng vì task chứa `p1`, `ticket`, `escalation`. Synthesis worker tính toán được thời gian escalation (22:47 + 10 phút = 22:57) từ context — đây là điểm mạnh của grounded generation. Score retrieval cao (0.6224–0.6471) vì câu hỏi rất khớp với nội dung tài liệu.

---

## Routing Decision #4 (bonus — multi-hop phức tạp nhất)

**Task đầu vào:**
> "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor để thực hiện emergency fix. Đồng thời cần notify stakeholders theo SLA. Nêu đủ cả hai quy trình."

**Worker được chọn:** `policy_tool_worker`  
**Route reason:** `policy/access keywords matched: access, level 2, contractor | risk_high keywords: emergency, 2am | MCP enabled`

**Nhận xét: Đây là trường hợp routing khó nhất trong lab. Tại sao?**

Task này span qua **hai domain** cùng lúc: (1) cấp quyền khẩn cấp cho contractor (→ access_control_sop.txt) và (2) notify stakeholder theo SLA P1 (→ sla_p1_2026.txt). Supervisor route sang `policy_tool_worker` vì phát hiện `access`, `level 2`, `contractor` trong policy_keywords — và đúng vì cấp quyền là phần cần policy check. Tuy nhiên SLA notification lại thuộc retrieval domain. Multi-hop câu hỏi như thế này lý tưởng phải gọi cả 2 worker, nhưng kiến trúc hiện tại chỉ route sang 1 worker. Kết quả confidence chỉ 0.69 dù MCP đã gọi `search_kb`. Đây là giới hạn của keyword-based routing khi task có nhiều intent.

---

## Tổng kết

### Routing Distribution

**Test questions (15 câu):**

| Worker | Số câu được route | % tổng |
|--------|------------------|--------|
| retrieval_worker | 8 | 53% |
| policy_tool_worker | 7 | 46% |
| human_review | 0 | 0% |

**Grading questions (10 câu):**

| Worker | Số câu | Câu ID |
|--------|--------|--------|
| retrieval_worker | 5 | gq01, gq05, gq06, gq07, gq08 |
| policy_tool_worker | 5 | gq02, gq03, gq04, gq09, gq10 |

### Routing Accuracy

- Test questions: ~13/15 route đúng
- Grading questions: routing hợp lý — gq07 (abstain test) route sang `retrieval_worker` đúng, gq09 (multi-hop) route sang `policy_tool_worker` đúng vì chứa "Level 2 access"
- Câu trigger HITL: 1/15 (6%)

### Lesson Learned về Routing

1. **Keyword matching đủ tốt cho câu đơn intent**: 85–90% các câu trong test set chỉ thuộc 1 domain rõ ràng, keyword matching đơn giản hoạt động tốt và nhanh hơn LLM classifier.
2. **Multi-hop task cần sequential workers**: Câu hỏi span nhiều domain (vừa cần SLA vừa cần access policy) không giải quyết được tốt với single-route architecture. Cần cân nhắc orchestration pattern cho phép gọi nhiều worker tuần tự.

### Route Reason Quality

Các `route_reason` trong trace đã đủ để debug vì format ghi rõ: (1) keywords nào matched, (2) MCP có được bật không, (3) risk flag có trigger không. Ví dụ: `"policy/access keywords matched: access, level 2, contractor | risk_high keywords: emergency, 2am | MCP enabled"` cho biết ngay cả 3 thông tin quan trọng trong một dòng. Cải tiến có thể làm: thêm `"no_match_keywords"` để ghi lại keywords nào bị bỏ qua, giúp debug false negative routing.
