# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Hồ Đắc Toàn
**Vai trò trong nhóm:** MCP Owner · Policy Tool Worker Owner
**Ngày nộp:** 14/04/2026
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào?

**Hai file tôi trực tiếp implement:**

- `mcp_server.py` — Mock MCP Server với 4 tools và HTTP server (FastAPI)
- `workers/policy_tool.py` — Policy & Tool Worker, gọi MCP client

**Các function tôi viết:**

| File | Function | Mô tả |
|------|----------|-------|
| `mcp_server.py` | `dispatch_tool()` | MCP execution layer — nhận tên tool + input, gọi function tương ứng |
| `mcp_server.py` | `list_tools()` | MCP discovery — trả về danh sách tool schema |
| `mcp_server.py` | `tool_search_kb()` | Tìm kiếm ChromaDB qua retrieval worker |
| `mcp_server.py` | `tool_get_ticket_info()` | Tra cứu ticket từ mock database |
| `mcp_server.py` | `tool_check_access_permission()` | Kiểm tra quyền truy cập theo Access Control SOP |
| `mcp_server.py` | `tool_create_ticket()` | Tạo ticket mock |
| `mcp_server.py` | FastAPI routes | `/health`, `/tools` (GET), `/tools/call` (POST) |
| `workers/policy_tool.py` | `_call_mcp_tool()` | MCP client wrapper — gọi `dispatch_tool()` và đóng gói kết quả vào trace |
| `workers/policy_tool.py` | `analyze_policy()` | Phát hiện exception hoàn tiền bằng rule-based + LLM refinement |
| `workers/policy_tool.py` | `run()` | Worker entry point — đọc state, gọi MCP, ghi `policy_result` và `mcp_tools_used` |

**Cách công việc của tôi kết nối với phần còn lại:**

`policy_tool_worker` là trung gian giữa retrieval (thành viên khác) và synthesis. Tôi đọc `retrieved_chunks` từ state, gọi `dispatch_tool()` trong `mcp_server.py` nếu cần bổ sung context, rồi ghi `policy_result` để `synthesis_worker` dùng. Cụ thể: `tool_search_kb()` trong `mcp_server.py` import `workers.retrieval.retrieve_dense` — nên phần MCP phụ thuộc vào retrieval worker đã build đúng ChromaDB index.

**Bằng chứng:** `workers/policy_tool.py` import `dispatch_tool` từ `mcp_server.py`. File `artifacts/grading_run.jsonl` ghi `mcp_tools_used` cho các câu gq02, gq03, gq04, gq09, gq10; riêng gq09 dùng cả `search_kb` và `get_ticket_info`, xác nhận MCP được gọi qua code tôi viết.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì?

**Quyết định:** Dùng `TOOL_REGISTRY` dictionary + dynamic dispatch thay vì `if/elif` hardcode.

**Phiên bản ban đầu tôi viết:**

```python
def dispatch_tool(tool_name, tool_input):
    if tool_name == "search_kb":
        return tool_search_kb(**tool_input)
    elif tool_name == "get_ticket_info":
        return tool_get_ticket_info(**tool_input)
    elif tool_name == "check_access_permission":
        return tool_check_access_permission(**tool_input)
    # thêm tool mới → phải sửa hàm này
```

**Vấn đề:** Mỗi lần thêm tool mới phải sửa `dispatch_tool()`, và không có cơ chế discovery. FastAPI cũng không thể reuse logic này.

**Phiên bản sau (hiện tại):**

```python
TOOL_REGISTRY = {
    "search_kb":               tool_search_kb,
    "get_ticket_info":         tool_get_ticket_info,
    "check_access_permission": tool_check_access_permission,
    "create_ticket":           tool_create_ticket,
}

def dispatch_tool(tool_name: str, tool_input: dict) -> dict:
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Tool '{tool_name}' không tồn tại. Available: {list(TOOL_REGISTRY.keys())}"}
    try:
        return TOOL_REGISTRY[tool_name](**tool_input)
    except TypeError as e:
        return {"error": f"Invalid input: {e}", "schema": TOOL_SCHEMAS[tool_name]["inputSchema"]}
```

**Trade-off đã chấp nhận:** Cần đặt tên function nhất quán với key trong registry — nếu rename function mà không đổi key thì lỗi ngầm. Trong scope 4 tools của lab, rủi ro này thấp và có thể kiểm soát bằng code review.

**Lợi ích thực tế:** FastAPI route `/tools/call` dùng lại `dispatch_tool()` mà không cần viết thêm logic — Bonus +2 (HTTP server) chỉ tốn ~30 dòng code. Trace câu gq09 cho thấy `dispatch_tool("search_kb")` và `dispatch_tool("get_ticket_info")` chạy nối tiếp không lỗi, cả hai đi qua cùng một code path.

---

## 3. Tôi đã sửa một lỗi gì?

**Lỗi:** `tool_check_access_permission()` trong `mcp_server.py` trả về `emergency_override=True` cho tất cả level khi `is_emergency=True`, kể cả Level 3 vốn không có emergency bypass.

**Symptom:** Khi test câu *"Engineer cần Level 3 access khẩn cấp để sửa P1"*, pipeline gọi MCP `check_access_permission` với `{"access_level": 3, "is_emergency": True}`. Hàm trả về `emergency_override=True` → synthesis tổng hợp câu trả lời rằng Level 3 có thể bypass approval trong khẩn cấp — **sai hoàn toàn** so với SOP (Level 3 bắt buộc đủ 3 người phê duyệt dù khẩn cấp).

**Root cause** — phiên bản ban đầu của hàm:

```python
def tool_check_access_permission(access_level, requester_role, is_emergency=False):
    rule = ACCESS_RULES.get(access_level)
    notes = []
    if is_emergency:
        emergency_override = True   # BUG: áp dụng cho mọi level, không kiểm tra rule
        notes.append("Emergency mode — bypass approval")
    else:
        emergency_override = False
        notes.append(rule.get("note", ""))
    ...
```

Vấn đề: `is_emergency=True` luôn set `emergency_override=True` mà không kiểm tra xem level đó có cho phép bypass không. Level 2 có (`emergency_can_bypass=True`), Level 3 và 4 không có (`emergency_can_bypass=False`).

**Cách sửa** — tách thành 3 nhánh kiểm tra `rule.get("emergency_can_bypass")`:

```python
if is_emergency and rule.get("emergency_can_bypass"):
    notes.append(rule.get("emergency_bypass_note", ""))
    emergency_override = True
elif is_emergency and not rule.get("emergency_can_bypass"):
    notes.append(rule.get("note", f"Level {access_level} KHÔNG có emergency bypass."))
    emergency_override = False
else:
    emergency_override = False
    notes.append(rule.get("note", ""))
```

**Bằng chứng trước/sau:**

- Trước: `dispatch_tool("check_access_permission", {"access_level": 3, "is_emergency": True})` → `emergency_override=True`, notes không đề cập "KHÔNG có bypass" → synthesis hallucinate rằng Level 3 có thể cấp tạm thời.
- Sau: cùng input → `emergency_override=False`, `notes=["Level 3 — Elevated Access. KHÔNG có emergency bypass. Phải có đủ 3 approvers dù trong tình huống khẩn cấp."]`. Trace grading câu **gq03**: `confidence=0.90`, answer ghi đúng IT Security là người phê duyệt cuối cùng, không đề cập bypass. Câu **gq09**: Level 2 emergency được trả về `emergency_override=True` với đủ điều kiện cấp tạm thời; MCP `get_ticket_info` bổ sung SLA notification nên answer đủ cả Slack + email + PagerDuty dù judge vẫn cho `confidence=0.50`.

---

## 4. Tôi tự đánh giá đóng góp của mình

**Làm tốt nhất ở điểm nào?**

Thiết kế `mcp_server.py` có thể test độc lập và tái sử dụng. `dispatch_tool()` xử lý cả `TypeError` (sai tham số) lẫn runtime exception mà không crash pipeline — `policy_tool_worker` gọi MCP mà không cần thêm try-catch. `TOOL_SCHEMAS` cho phép `list_tools()` hoạt động đúng chuẩn MCP discovery.

**Còn yếu ở điểm nào?**

`analyze_policy()` hiện xử lý temporal scoping còn hơi mềm: trường hợp đơn trước 01/02/2026 mới được ghi vào `policy_version_note`, chưa thành field có cấu trúc để synthesis biết chắc rằng policy v3 bị thiếu trong docs. Ngoài ra rule-based exception detection còn phụ thuộc nhiều vào LLM để xử lý negation như "không phải Flash Sale", nên cần viết rule theo task-specific signal rõ hơn.

**Nhóm phụ thuộc vào tôi ở đâu?**

7/15 câu test đi qua `policy_tool_worker` — khoảng 46% pipeline phụ thuộc vào `mcp_server.py` hoạt động đúng. Nếu `dispatch_tool()` crash hoặc thiếu, các câu liên quan đến hoàn tiền, access control, và ticket đều trả về lỗi.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì?

Tôi sẽ sửa `analyze_policy()` để xử lý temporal scoping rõ hơn cho policy v3. Trace câu **gq02** cho thấy pipeline đã nhận ra đơn ngày 31/01/2026 không áp dụng refund policy v4, nhưng vì tài liệu nội bộ không có policy v3 nên answer chỉ đạt partial. Hiện tại `policy_version_note` mới là text note; tôi muốn biến nó thành output có cấu trúc để synthesis biết phải abstain có điều kiện thay vì trả lời lửng.

Fix cụ thể: khi phát hiện đơn trước 01/02/2026, set policy name và missing-context flag rõ ràng:

```python
if order_date < date(2026, 2, 1):
    policy_name = "refund_policy_v3_unknown"
    missing_required_policy = True
    policy_version_note = (
        "Đơn trước 01/02/2026 áp dụng policy v3, "
        "nhưng tài liệu hiện tại chỉ có policy v4."
    )
```

Thay đổi này giúp gq02 trả lời chắc hơn: xác định đúng policy version, nêu rõ thiếu tài liệu v3, và không suy diễn điều kiện hoàn tiền từ v4.
