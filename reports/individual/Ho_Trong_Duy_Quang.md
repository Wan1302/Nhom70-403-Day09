# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Hồ Trọng Duy Quang - 2A202600081
<br>
**Vai trò trong nhóm:** Supervisor Owner / Synthesis / Retrieval Worker  
**Ngày nộp:** 14/04/2026
<br>
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào? (100–150 từ)

Tôi phụ trách chính thiết kế luồng đồ thị điều phối (Orchestrator) và tham gia xây dựng logic tổng hợp dữ liệu, cũng như truy xuất tài liệu vector.

**Module/file tôi chịu trách nhiệm:**
- File chính: `graph.py`, `workers/retrieval.py`, `workers/synthesis.py`.
- Functions tôi implement:
  - Viết logic định tuyến `supervisor_node` và các Conditional edges định hướng dữ liệu.
  - Implement luồng truy xuất chunks trong `retrieval.py`.
  - Trong hàm `_estimate_confidence` thuộc file `synthesis.py`: Tôi nhận nhiệm vụ cài đặt thuật toán tự tính điểm bằng công thức toán học (heuristic) dựa trên vector score và exceptions penalty. (Lưu ý: Logic LLM-as-judge nâng cao lúc sau của hàm này là do bạn **Nguyên** đảm nhận phát triển ghép vào). 

**Cách công việc của tôi kết nối với phần của thành viên khác:**
Luồng `graph.py` của tôi là xương sống định tuyến input vào module `policy_tool_worker` của thành viên khác. Sau đó, nó tổng hợp lại mọi kết quả đưa về module `synthesis.py` của tôi để ra answer sinh ra cho user.

**Bằng chứng:**
Code định tuyến có trong file `graph.py` chạy qua được `python graph.py` và có chứa logic `route_decision` xử lý điều hướng mượt mà cho supervisor.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? (150–200 từ)

**Quyết định:** Sử dụng công thức heuristic có trọng số (weighted rule-based) cho hàm `_estimate_confidence` ở `synthesis.py` như một cơ chế mặc định vững chắc trước khi gọi LLM.

**Lý do:**
Việc ước tính độ đáng tin cậy của câu trả lời không có nghĩa là lúc nào gọi LLM (Judge) cũng là tối ưu vì sẽ cộng dồn độ trễ hệ thống (latency) và tốn token API. Do đó, tôi dùng cách gộp top relevance score (chịu trách nhiệm cho đoạn trích dẫn đắt giá nhất) và average relevance score (thể hiện chất lượng tổng quan) để tính `evidence_score`. Hơn nữa, nó trừ phạt tự động nếu phát sinh `exceptions` từ Policy. Từ đó, bạn Nguyên sau này làm thêm LLM-as-judge vẫn có khung giá trị an toàn này để fallback lại về heuristic nếu LLM API của bạn bị lỗi hoặc không phản hồi số.

**Trade-off đã chấp nhận:**
Tính điểm qua vector score chỉ phản ánh độ giống nhau về từ vựng, không xác định 100% việc câu trả lời LLM có rơi vào Hallucination hay không (vậy nên sau đó mới cần bạn Nguyên cài bổ sung tính năng kiểm duyệt bằng LLM). Tuy nhiên, latency của quá trình đánh giá này gần bằng ~0 ms, đảm bảo luồng dự phòng vô cùng nhanh.

**Bằng chứng từ trace/code:**
```python
# Trích dẫn phần tự tính score trong synthesis.py
scores = [float(c.get("score", 0) or 0) for c in chunks]
avg_score = sum(scores) / len(scores) if scores else 0
top_score = max(scores) if scores else 0
evidence_score = (0.7 * top_score) + (0.3 * avg_score)

confidence = 0.2 if evidence_score <= 0 else 0.2 + (0.75 * evidence_score)
exception_penalty = 0.05 * len(policy_result.get("exceptions_found", []))
confidence = min(0.95, confidence - exception_penalty)
```

---

## 3. Tôi đã sửa một lỗi gì? (150–200 từ)

**Lỗi:** Crashed Pipeline ở khâu Synthesis và `ZeroDivisionError`.

**Symptom (pipeline làm gì sai?):**
Khi chạy các test query không liên quan tới bất kì keyword nào có sẵn trong dữ liệu (e.g. Hỏi lung tung), graph chuyển xuống vòng đánh giá score rồi đột ngột báo `SYNTHESIS_FAILED` khiến `final_answer` không được sinh ra hoặc trả ra rỗng đứt đoạn, confidence đưa về 0.0 do ngoại lệ.

**Root cause:**
Logic ban đầu khi đếm `avg_score` trong mảng `scores` không kiểm tra kịch bản danh sách `chunks` trả về từ `retrieval.py` trống rỗng. Lệnh `sum(scores) / len(scores)` gây ra chia cho 0 `Division by Zero Error`.

**Cách sửa:**
Trong `synthesis.py`, tôi đã wrap xử lý mảng thành inline condition. Thêm `... if scores else 0` và check early return ở đầu hàm bằng `if not chunks:` để xử lý ngoại lệ nhanh gọn. Nếu không có chunks mà policy cũng rỗng thì gán mặc định luôn confidence là 0.1 mà không cần đi qua phép toán.

**Bằng chứng trước/sau:**
Trước khi sửa (Lỗi code):
`avg_score = sum(scores) / len(scores)` -> Nếu len() là 0 -> Crash Worker.
Sau khi sửa:
`avg_score = sum(scores) / len(scores) if scores else 0` -> An toàn, fallback hoạt động trơn tru bất kể input vector rỗng.

---

## 4. Tôi tự đánh giá đóng góp của mình (100–150 từ)

**Tôi làm tốt nhất ở điểm nào?**
Tôi thiết lập được kiến trúc Graph chạy chuẩn xác, đi qua đủ các node của workflow, và hoàn thành hệ thống fallback score của vòng synthesis. Node logic của tôi ổn định.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**
Do phải tập trung nhiều vào logic liên kết nhiều file với nhau, cách tôi bóc tách dữ liệu từ file test trong vector store tại `retrieval.py` đôi lúc vẫn chưa thực sự mang lại độ chuẩn xác (relevance score) đỉnh nhất. Tôi vẫn phải dựa nhiều vào heuristic bù trừ.

**Nhóm phụ thuộc vào tôi ở đâu?**
`graph.py`. Chừng nào phần khung định tuyến (Orchestrator) của tôi không chạy trôi chảy thì các thành phần Policy hay MCP tools của các bạn làm không thể giao tiếp với nhau trong pipeline.

**Phần tôi phụ thuộc vào thành viên khác:**
Tôi cần phụ thuộc vào API response từ hệ thống LLM-as-judge của bạn Nguyên cũng như các input format chuẩn đầu ra Exception từ file policy của nhóm để tổng hợp câu trả lời đúng không bị sai lệch schema.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? (50–100 từ)

Tôi sẽ dành 2 giờ đó để sử dụng `mcp_server` để cải tiến chính logic định tuyến (router) của supervisor trong `graph.py`. Hiện tại việc phân luồng chỉ đơn thuần dựa vào phân loại qua Keyword thô ráp. Bằng chứng từ file trace thi thoảng bị route nhầm sang "human_review" nếu tự nhiên gõ "err-" vô ý. Việc áp dụng LLM route mạnh hơn có lưu vết gọi API tool sẽ biến luồng graph thành một agent đích thực thay vì dạng rule base cứng như bây giờ.
