# Single Agent vs Multi-Agent Comparison — Lab Day 09

**Nhóm:** Nhóm 70  
**Ngày:** 2026-04-14

> So sánh Day 08 (single-agent RAG) với Day 09 (supervisor-worker).
> Số liệu Day 08 từ baseline do nhóm cung cấp. Số liệu Day 09 từ `artifacts/eval_report.json`.

---

## 1. Metrics Comparison

| Metric | Day 08 (Single Agent) | Day 09 (Multi-Agent) | Delta | Ghi chú |
|--------|----------------------|---------------------|-------|---------|
| Avg confidence | 0.661 | 0.573 | −0.088 | Day 09 dùng LLM-as-Judge (GPT-4o) → chấm chính xác hơn, không inflate |
| Avg latency (ms) | 2,886 | 4,749 | +1,863 ms | Thêm supervisor node + MCP call + LLM judge call |
| Multi-hop accuracy | 0.0% (0/3) | gq09 full (ước tính 16/16) | Cải thiện rõ | Day 09 dùng routing + MCP để xử lý câu cross-doc khó nhất |
| Routing visibility | ✗ Không có | ✓ Có `route_reason` | N/A | Mỗi câu đều có route_reason trong trace |
| MCP tool usage | N/A | 46% (7/15 câu) | N/A | Tự động gọi external tool khi cần policy check |
| HITL rate | 0% | 6% (1/15 câu) | +6% | Day 09 có khả năng pause cho human review |
| Câu conf ≤ 0.25 (yếu) | Không đo | 4/10 grading câu | N/A | gq02(0.25), gq04(0.10), gq07(0.25), gq08(0.25) — judge phát hiện đúng |
| Câu conf ≥ 0.90 (tốt) | Không đo | 4/10 grading câu | N/A | gq03, gq05, gq06, gq10 — pipeline trả lời tốt |

> **Ghi chú về confidence:** Day 09 thấp hơn Day 08 (0.573 vs 0.661) không có nghĩa là kém hơn — Day 08 dùng heuristic cosine score nên luôn cho ~0.6 bất kể chất lượng. Day 09 dùng LLM-as-Judge phân biệt rõ câu tốt (0.90–0.95) với câu yếu (0.10–0.25), giúp phát hiện answer cần review.

---

## 2. Phân tích theo loại câu hỏi

### 2.1 Câu hỏi đơn giản (single-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Confidence trung bình | 0.661 | 0.573 (LLM-as-Judge) |
| Latency | ~2,886 ms | avg 4,749ms |
| Observation | Một pipeline xử lý tất cả | Supervisor route → 1 worker → synthesis → LLM judge |

**Kết luận:** Multi-agent không cải thiện accuracy cho câu đơn giản — single-agent cũng trả lời được. Lợi ích chính là **traceability** và **honest confidence**: LLM judge phân biệt được câu trả lời tốt (conf=0.90–0.95) với câu yếu (conf=0.10–0.25), thay vì heuristic luôn trả về ~0.6.

### 2.2 Câu hỏi multi-hop (cross-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | 0/3 (0%) | gq09 full theo self-review grading |
| Routing visible? | ✗ | ✓ |
| Observation | Pipeline không phân biệt loại câu hỏi | Supervisor nhận diện từ khóa và route phù hợp; MCP giúp lấy thêm context |

**Kết luận:** Day 08 thất bại hoàn toàn trên multi-hop (0%). Day 09 xử lý được gq09 — câu khó nhất — vì `policy_tool_worker` gọi MCP `search_kb` và `get_ticket_info`, giúp answer bao phủ cả SLA P1 notification lẫn Level 2 emergency access. Tuy vậy, single-route vẫn là giới hạn kiến trúc: nếu MCP không kéo đủ context phụ, task span 2 domain sẽ ổn định hơn khi supervisor cho phép gọi tuần tự cả `retrieval_worker` và `policy_tool_worker`.

### 2.3 Câu hỏi cần abstain

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Abstain rate | 0.0% | 0.0% |
| Hallucination cases | Không đo được | Có thể kiểm tra qua confidence thấp + grading |
| Observation | Không có cơ chế abstain | Synthesis worker có thể flag low confidence; HITL triggered 1 lần |

**Kết luận:** Cả hai pipeline chưa implement abstain thực sự (trả về "không đủ thông tin"). Day 09 có HITL (1 lần trigger) nhưng vẫn generate answer. Cần thêm threshold abstain khi `confidence < 0.4` ở synthesis worker.

---

## 3. Debuggability Analysis

### Day 08 — Debug workflow
```
Khi answer sai → phải đọc toàn bộ RAG pipeline code → không biết lỗi ở retrieval hay generation
Không có trace → không biết bắt đầu từ đâu → đọc code từ đầu
Thời gian ước tính: ~30 phút
```

### Day 09 — Debug workflow
```
Khi answer sai → đọc artifacts/traces/run_XXXXX.json → xem supervisor_route + route_reason
  → Nếu route sai → sửa keyword list trong supervisor_node()
  → Nếu retrieval sai → test: python workers/retrieval.py
  → Nếu synthesis sai → xem retrieved_sources → kiểm tra chunk quality
  → Nếu MCP sai → xem mcp_tools_used + output trong trace
Thời gian ước tính: ~10 phút
```

**Câu cụ thể nhóm đã debug:** Câu gq09/q15 (Ticket P1 lúc 2am, contractor Level 2 + SLA notify) là case multi-intent khó nhất. Đọc trace thấy `supervisor_route=policy_tool_worker` và MCP gọi cả `search_kb` lẫn `get_ticket_info`; nhờ đó answer cuối cùng nêu đủ Slack + email + PagerDuty cho SLA P1 và điều kiện Level 2 emergency access. Thời gian debug/verify: ~5 phút nhờ trace có `route_reason`, `workers_called`, và `mcp_tools_used`.

---

## 4. Extensibility Analysis

| Scenario | Day 08 | Day 09 |
|---------|--------|--------|
| Thêm 1 tool/API mới | Phải sửa toàn bộ RAG prompt và pipeline | Thêm function vào `mcp_server.py` + 1 keyword rule trong supervisor |
| Thêm 1 domain mới (VD: HR policy) | Phải re-prompt toàn bộ system prompt | Thêm 1 worker mới + route rule |
| Thay đổi retrieval strategy | Sửa trực tiếp trong pipeline, ảnh hưởng mọi câu | Sửa `workers/retrieval.py` độc lập |
| A/B test một phần | Phải clone toàn pipeline | Swap worker trong graph — không ảnh hưởng phần còn lại |

**Nhận xét:** Day 09 đúng hướng về extensibility. Thực tế trong lab, khi cần thêm `tool_create_ticket` vào MCP server, chỉ cần thêm 1 function và đăng ký vào `TOOL_REGISTRY` — không cần đụng vào supervisor hay synthesis.

---

## 5. Cost & Latency Trade-off

| Scenario | Day 08 calls | Day 09 calls |
|---------|-------------|-------------|
| Simple query (retrieval path) | 1 LLM call | 2 LLM calls (policy check + synthesis) |
| Complex query (policy path + MCP) | 1 LLM call | 2–3 LLM calls + 1 MCP call |
| MCP tool call | N/A | 1 tool call (ChromaDB, không tốn LLM) |

**Nhận xét về cost-benefit:** Day 09 tốn khoảng 2× LLM calls so với Day 08 cho cùng 1 câu hỏi. Tuy nhiên đổi lại được: routing visibility, khả năng debug, và có thể thêm/thay worker mà không break toàn hệ. Với bài toán production có nhiều loại câu hỏi khác nhau, trade-off này xứng đáng — nhất là khi routing sai chỉ ảnh hưởng 1 worker thay vì toàn pipeline.

---

## 6. Kết luận

> **Multi-agent tốt hơn single agent ở điểm nào?**

1. **Debuggability**: Trace rõ ràng từng bước (supervisor → worker → synthesis), có thể test worker độc lập. Day 08 không có bất kỳ visibility nào về lỗi nằm ở đâu.
2. **Extensibility**: Thêm MCP tool mới hoặc worker mới không ảnh hưởng phần còn lại. Day 08 phải sửa toàn pipeline khi thêm capability.

> **Multi-agent kém hơn hoặc không khác biệt ở điểm nào?**

1. **Latency & cost**: Thêm ~1,863ms trung bình và ~2× LLM calls. Với câu hỏi đơn giản, overhead này không mang lại lợi ích accuracy.

> **Khi nào KHÔNG nên dùng multi-agent?**

Khi tất cả câu hỏi đều thuộc cùng 1 domain, không cần phân biệt retrieval vs policy, và không có external tool cần gọi. Ví dụ: chatbot FAQ đơn giản chỉ trả lời từ 1 document — single-agent RAG nhanh hơn, rẻ hơn, dễ maintain hơn.

> **Nếu tiếp tục phát triển hệ thống này, nhóm sẽ thêm gì?**

1. Cho phép supervisor gọi nhiều worker tuần tự cho multi-intent tasks (sequential chaining thay vì single-route) để gq09 và các câu tương tự không phụ thuộc hoàn toàn vào MCP context phụ.
2. Thêm abstain threshold tại synthesis: khi `confidence < 0.4` trả về "Không đủ thông tin" thay vì generate câu trả lời không chắc chắn.
3. Thay keyword matching bằng LLM intent classifier để xử lý câu hỏi mơ hồ tốt hơn.
