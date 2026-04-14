# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Hồ Trần Đình Nguyên  
**Vai trò trong nhóm:** Trace & Docs Owner  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào?

**Module/file tôi chịu trách nhiệm:**
- File chính: `eval_trace.py`, `artifacts/traces/` (15 trace files), `artifacts/grading_run.jsonl`, `artifacts/eval_report.json`
- Docs: `docs/system_architecture.md`, `docs/routing_decisions.md`, `docs/single_vs_multi_comparison.md`
- Functions tôi implement: `analyze_traces()`, `compare_single_vs_multi()`, `run_grading_questions()`

Cụ thể, tôi implement `eval_trace.py` để chạy toàn bộ 15 test questions qua pipeline, ghi trace ra từng file JSON trong `artifacts/traces/`, tính metrics tổng hợp (avg_confidence, avg_latency, routing distribution, MCP usage rate, HITL rate) và so sánh với Day 08 baseline. Sau 17:00, tôi chạy thêm `--grading` để sinh `artifacts/grading_run.jsonl` với 10 câu grading questions.

**Cách công việc của tôi kết nối với phần của thành viên khác:**

`eval_trace.py` gọi `run_graph()` từ `graph.py` (Quang viết) và đọc output state từ tất cả workers. Nếu bất kỳ worker nào thay đổi field trong `AgentState`, trace tôi ghi sẽ phản ánh ngay — giúp tôi phát hiện lỗi của worker mà không cần đọc code của từng người.

**Bằng chứng:** File `artifacts/traces/run_20260414_170729_243568.json` ghi đầy đủ `worker_io_logs` của cả 3 workers, `mcp_tools_used` từ Toàn, và `supervisor_route` từ Quang trong cùng 1 trace.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì?

**Quyết định:** Đề xuất và implement LLM-as-Judge thay cho heuristic cosine score trong `workers/synthesis.py` (file do Quang phụ trách) sau khi phát hiện vấn đề qua kết quả eval.

Sau khi chạy `analyze_traces()` lần đầu, tôi thấy avg_confidence = 0.572 nhưng toàn bộ 15 câu có confidence tập trung trong khoảng 0.55–0.72 — không có câu nào dưới 0.5 hay trên 0.75. Tôi nhận ra đây là dấu hiệu heuristic không có giá trị phân biệt: trace của q04 ("store credit = bao nhiêu %?") cho confidence = 0.61 dù answer mơ hồ, trace của q11 ("Ticket P1 lúc 22:47") cũng chỉ 0.68 dù answer chính xác — confidence không phản ánh chất lượng thật.

Tôi báo với nhóm, đề xuất dùng LLM-as-Judge và trực tiếp implement vào `_estimate_confidence()`: gọi GPT-4o với system prompt tiếng Việt, pass answer + top-3 evidence chunks, nhận về 1 số float (`max_tokens=5`). Hai shortcut tránh gọi LLM: không có evidence → `0.10`, answer chứa "Không đủ thông tin" → `0.25`. Fallback về heuristic nếu API lỗi.

**Trade-off đã chấp nhận:** Thêm ~200–400ms latency và 1 API call mỗi câu. Đổi lại, judge phân biệt rõ câu tốt (conf ≥ 0.90) với câu yếu (conf ≤ 0.25) — heuristic không thể làm được.

**Bằng chứng từ trace/code:**

```python
# workers/synthesis.py — _estimate_confidence()
resp = client.chat.completions.create(
    model=os.getenv("OPENAI_JUDGE_MODEL", "gpt-4o"),
    messages=[
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": user_msg},
    ],
    temperature=0.0,
    max_tokens=5,
)

# Kết quả grading run — phân biệt rõ hơn heuristic:
# gq03 (answer đúng, có citation):  conf = 0.90
# gq05 (SLA escalation đúng):       conf = 0.90
# gq04 (answer mơ hồ):              conf = 0.10
# gq07 (không có info, cần abstain): conf = 0.25
```

---

## 3. Tôi đã sửa một lỗi gì?

**Lỗi:** `contracts/worker_contracts.yaml` bị stale — mô tả `synthesis_worker` vẫn ghi confidence là heuristic dù code đã được đổi sang LLM-as-Judge.

**Symptom:** Sau khi nhóm implement LLM-as-Judge trong `workers/synthesis.py`, tôi đọc lại `contracts/worker_contracts.yaml` để điền docs và phát hiện `actual_implementation.notes` của `synthesis_worker` vẫn ghi:

```yaml
- "Confidence is heuristic: abstain/no evidence is low; otherwise combines
   top retrieval score, average retrieval score, policy-only evidence,
   and exception penalties."
```

Contract khai báo sai so với implementation thực tế — ai đọc contract sẽ hiểu sai cách confidence được tính, ảnh hưởng trực tiếp đến điểm **Code Contribution Evidence** (tiêu chí "không có mâu thuẫn giữa claim trong report và thực tế trong code").

**Root cause:** Khi `synthesis_worker` được cập nhật để dùng LLM-as-Judge, chỉ có `workers/synthesis.py` được sửa. File `contracts/worker_contracts.yaml` không được cập nhật đồng bộ — đây là lỗi documentation drift thường gặp khi implementation thay đổi sau khi contract đã viết.

**Cách sửa:** Tôi cập nhật `actual_implementation.notes` trong contract để phản ánh đúng implementation:

```yaml
# TRƯỚC:
- "Confidence is heuristic: abstain/no evidence is low; otherwise combines
   top retrieval score, average retrieval score, policy-only evidence,
   and exception penalties."

# SAU:
- "Confidence uses LLM-as-Judge (GPT-4o, OPENAI_JUDGE_MODEL env): given
   the answer and evidence chunks, GPT-4o returns a float 0.00-1.00.
   Shortcuts: no evidence → 0.10, abstain answer → 0.25.
   Falls back to heuristic (cosine score weighted average) if LLM unavailable."
```

**Bằng chứng:** Commit `b1937e3` (author: hotrandinhnguyen, 2026-04-14 17:20) — git diff thực tế:

```diff
# contracts/worker_contracts.yaml — commit b1937e3
-  - "Confidence is heuristic: abstain/no evidence is low; otherwise combines
-     top retrieval score, average retrieval score, policy-only evidence,
-     and exception penalties."
+  - "Confidence uses LLM-as-Judge (GPT-4o, OPENAI_JUDGE_MODEL env): given
+     the answer and evidence chunks, GPT-4o returns a float 0.00-1.00.
+     Shortcuts: no evidence → 0.10, abstain answer → 0.25.
+     Falls back to heuristic (cosine score weighted average) if LLM unavailable."
```

Sau khi sửa, contract khớp với `_estimate_confidence()` trong `workers/synthesis.py`. Grading run xác nhận judge hoạt động đúng: gq07 (không có info phạt tài chính → cần abstain) nhận conf=0.25, gq03 (đủ evidence 3 approvers) nhận conf=0.90.

---

## 4. Tôi tự đánh giá đóng góp của mình

**Tôi làm tốt nhất ở điểm nào?**

Điền đầy đủ số liệu thực tế vào cả 3 docs (`routing_decisions.md`, `single_vs_multi_comparison.md`, `system_architecture.md`) từ trace thật thay vì để placeholder. Đặc biệt, tôi phát hiện được vấn đề confidence heuristic không có giá trị phân biệt và đề xuất LLM-as-Judge — quyết định này ảnh hưởng trực tiếp đến khả năng nhóm phát hiện câu yếu (4/10 grading câu có conf ≤ 0.25).

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Không phát hiện sớm vấn đề Unicode — lẽ ra nên test `eval_trace.py` trên Windows ngay từ Sprint 4 thay vì phát hiện khi chạy grading. Ngoài ra chưa implement abstain threshold cứng trong synthesis: judge biết câu yếu (conf=0.25) nhưng pipeline vẫn generate answer thay vì trả về "Không đủ thông tin".

**Nhóm phụ thuộc vào tôi ở đâu?**

`artifacts/grading_run.jsonl` là output bắt buộc để nộp bài (30/60 điểm nhóm). Nếu tôi không chạy `eval_trace.py --grading` trước 18:00, nhóm mất toàn bộ điểm grading. Ngoài ra 3 docs trong `docs/` cũng do tôi điền — nếu để trống mất 10 điểm.

**Phần tôi phụ thuộc vào thành viên khác:**

Tôi cần `graph.py` (Quang) chạy được để `eval_trace.py` gọi `run_graph()`. Cần `workers/policy_tool.py` (Toàn) trả về đúng `policy_result` format để trace ghi đúng `mcp_tools_used`.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì?

Tôi sẽ thêm **abstain threshold cứng** vào `synthesis_worker`: nếu LLM judge trả về confidence < 0.30, thay vì return answer như hiện tại, worker sẽ override `final_answer = "Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này."`. Lý do: trace gq07 (conf=0.25) cho thấy judge đã biết đây là câu cần abstain nhưng pipeline vẫn generate answer có thể sai. Theo SCORING.md, abstain đúng cho gq07 được 10/10 điểm, còn generate answer sai bị −5 điểm penalty — chênh lệch 15 điểm chỉ cần 1 if statement.

---

*Lưu file: `reports/individual/Ho_Tran_Dinh_Nguyen.md`*
