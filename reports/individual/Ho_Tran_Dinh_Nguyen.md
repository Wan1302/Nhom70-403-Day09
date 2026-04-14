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

**Quyết định:** Thay hàm `_estimate_confidence()` từ heuristic cosine score sang LLM-as-Judge dùng GPT-4o.

Khi chạy lần đầu với heuristic, tôi nhận thấy avg_confidence = 0.572 nhưng các câu có confidence rất tập trung trong khoảng 0.60–0.72 — pipeline không phân biệt được câu trả lời tốt với câu yếu. Nhìn vào trace của q04 ("store credit = bao nhiêu %?") thấy confidence = 0.61 dù answer chỉ mơ hồ, trong khi q11 ("Ticket P1 lúc 22:47") cũng chỉ 0.68 dù answer rất chính xác.

Tôi quyết định dùng LLM-as-Judge: gọi GPT-4o với system prompt tiếng Việt mô tả thang điểm 0.00–1.00, pass answer và top-3 evidence chunks, nhận về 1 số duy nhất (`max_tokens=5`). Có 2 shortcut không gọi LLM: không có evidence → `0.10` ngay, answer chứa "Không đủ thông tin" → `0.25` ngay. Nếu API lỗi → fallback về heuristic cũ.

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

**Lỗi:** `eval_trace.py` và `graph.py` crash `UnicodeEncodeError` khi chạy trên Windows terminal.

**Symptom:** Chạy `python eval_trace.py` trên PowerShell cho ra lỗi:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u25b6'
in position 33: character maps to <undefined>
```

Pipeline không chạy được, không sinh ra trace files.

**Root cause:** Windows terminal mặc định dùng encoding `cp1252`, không hỗ trợ ký tự Unicode ngoài ASCII như `▶`, `✓`, `📊`. Các `print()` statement trong `__main__` block dùng emoji và ký tự đặc biệt bị crash ngay khi in ra terminal.

**Cách sửa:** Đặt biến môi trường `PYTHONIOENCODING=utf-8` trước khi chạy để Python dùng UTF-8 cho stdout:

```powershell
$env:PYTHONIOENCODING="utf-8"; venv\Scripts\python.exe eval_trace.py --grading
```

**Bằng chứng trước/sau:**

```
# TRƯỚC (crash):
PS> python eval_trace.py --grading
UnicodeEncodeError: 'charmap' codec can't encode character '\u2714'...

# SAU (chạy thành công):
PS> $env:PYTHONIOENCODING="utf-8"; venv\Scripts\python.exe eval_trace.py --grading
[01/10] gq01: Ticket P1 duoc tao luc 22:47...
  ✓ route=retrieval_worker, conf=0.50
...
✅ Grading log saved → artifacts/grading_run.jsonl
```

File `artifacts/grading_run.jsonl` sinh ra đủ 10 dòng, đúng format yêu cầu của SCORING.md.

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
