"""
mcp_server.py — Mock MCP Server + FastAPI HTTP Server (Bonus +2)
Sprint 3: Implement ít nhất 2 MCP tools.

Mô phỏng MCP (Model Context Protocol) interface trong Python.
Agent (MCP client) gọi dispatch_tool() thay vì hard-code từng API.

Tools available:
    1. search_kb(query, top_k)                           → tìm kiếm Knowledge Base
    2. get_ticket_info(ticket_id)                        → tra cứu thông tin ticket (mock data)
    3. check_access_permission(level, requester_role)    → kiểm tra quyền truy cập
    4. create_ticket(priority, title, description)       → tạo ticket mới (mock)

Sử dụng (Standard — mock class):
    from mcp_server import dispatch_tool, list_tools
    result = dispatch_tool("search_kb", {"query": "SLA P1", "top_k": 3})

Sử dụng (Advanced — HTTP server, Bonus +2):
    python mcp_server.py --serve        # Khởi động HTTP server tại port 8080
    python mcp_server.py                # Chạy test demo

HTTP Endpoints:
    GET  /tools              → list all available tools
    POST /tools/call         → call a tool by name
    GET  /health             → health check
"""

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────
# Tool Definitions (Schema Discovery)
# ─────────────────────────────────────────────

TOOL_SCHEMAS = {
    "search_kb": {
        "name": "search_kb",
        "description": "Tìm kiếm Knowledge Base nội bộ bằng semantic search. Trả về top-k chunks liên quan nhất.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Câu hỏi hoặc keyword cần tìm"},
                "top_k": {"type": "integer", "description": "Số chunks cần trả về", "default": 3},
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "chunks": {"type": "array"},
                "sources": {"type": "array"},
                "total_found": {"type": "integer"},
            },
        },
    },
    "get_ticket_info": {
        "name": "get_ticket_info",
        "description": "Tra cứu thông tin ticket từ hệ thống Jira nội bộ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "ID ticket (VD: IT-1234, P1-LATEST)"},
            },
            "required": ["ticket_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "priority": {"type": "string"},
                "status": {"type": "string"},
                "assignee": {"type": "string"},
                "created_at": {"type": "string"},
                "sla_deadline": {"type": "string"},
            },
        },
    },
    "check_access_permission": {
        "name": "check_access_permission",
        "description": "Kiểm tra điều kiện cấp quyền truy cập theo Access Control SOP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_level": {"type": "integer", "description": "Level cần cấp (1, 2, hoặc 3)"},
                "requester_role": {"type": "string", "description": "Vai trò của người yêu cầu"},
                "is_emergency": {"type": "boolean", "description": "Có phải khẩn cấp không", "default": False},
            },
            "required": ["access_level", "requester_role"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "can_grant": {"type": "boolean"},
                "required_approvers": {"type": "array"},
                "emergency_override": {"type": "boolean"},
                "source": {"type": "string"},
            },
        },
    },
    "create_ticket": {
        "name": "create_ticket",
        "description": "Tạo ticket mới trong hệ thống Jira (MOCK — không tạo thật trong lab).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["priority", "title"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "url": {"type": "string"},
                "created_at": {"type": "string"},
            },
        },
    },
}


# ─────────────────────────────────────────────
# Tool Implementations
# ─────────────────────────────────────────────

def tool_search_kb(query: str, top_k: int = 3) -> dict:
    """
    Tìm kiếm Knowledge Base bằng semantic search qua ChromaDB.
    """
    try:
        import sys
        import os
        # Đảm bảo có thể import từ root
        _root = os.path.dirname(os.path.abspath(__file__))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from workers.retrieval import retrieve_dense
        chunks = retrieve_dense(query, top_k=top_k)
        sources = list({c["source"] for c in chunks})
        return {
            "chunks": chunks,
            "sources": sources,
            "total_found": len(chunks),
        }
    except Exception as e:
        # Fallback: trả về mock data nếu ChromaDB chưa setup
        return {
            "chunks": [
                {
                    "text": f"[MOCK] ChromaDB query failed: {e}. Returning mock result.",
                    "source": "mock_data",
                    "score": 0.5,
                }
            ],
            "sources": ["mock_data"],
            "total_found": 1,
        }


# Mock ticket database
MOCK_TICKETS = {
    "P1-LATEST": {
        "ticket_id": "IT-9847",
        "priority": "P1",
        "title": "API Gateway down — toàn bộ người dùng không đăng nhập được",
        "status": "in_progress",
        "assignee": "nguyen.van.a@company.internal",
        "created_at": "2026-04-14T22:47:00",
        "sla_deadline": "2026-04-15T02:47:00",
        "escalated": True,
        "escalated_to": "senior_engineer_team",
        "notifications_sent": ["slack:#incident-p1", "email:incident@company.internal", "pagerduty:oncall"],
    },
    "IT-1234": {
        "ticket_id": "IT-1234",
        "priority": "P2",
        "title": "Feature login chậm cho một số user",
        "status": "open",
        "assignee": None,
        "created_at": "2026-04-14T09:15:00",
        "sla_deadline": "2026-04-15T09:15:00",
        "escalated": False,
    },
}


def tool_get_ticket_info(ticket_id: str) -> dict:
    """Tra cứu thông tin ticket (mock data)."""
    ticket = MOCK_TICKETS.get(ticket_id.upper())
    if ticket:
        return ticket
    return {
        "error": f"Ticket '{ticket_id}' không tìm thấy trong hệ thống.",
        "available_mock_ids": list(MOCK_TICKETS.keys()),
    }


# Mock access control rules (dựa trên access_control_sop.txt)
ACCESS_RULES = {
    1: {
        "required_approvers": ["Line Manager"],
        "emergency_can_bypass": False,
        "note": "Level 1 — Read Only. Thời gian xử lý: 1 ngày làm việc.",
    },
    2: {
        "required_approvers": ["Line Manager", "IT Admin"],
        "emergency_can_bypass": True,
        "emergency_bypass_note": (
            "Level 2 CÓ emergency bypass: On-call IT Admin có thể cấp tạm thời (max 24h) "
            "sau khi được Tech Lead phê duyệt bằng lời. "
            "Phải ghi log vào Security Audit System."
        ),
        "note": "Level 2 — Standard Access. Thời gian xử lý: 2 ngày làm việc.",
    },
    3: {
        "required_approvers": ["Line Manager", "IT Admin", "IT Security"],
        "emergency_can_bypass": False,
        "note": (
            "Level 3 — Elevated Access. KHÔNG có emergency bypass. "
            "Phải có đủ 3 approvers dù trong tình huống khẩn cấp. "
            "Thời gian xử lý: 3 ngày làm việc."
        ),
    },
    4: {
        "required_approvers": ["IT Manager", "CISO"],
        "emergency_can_bypass": False,
        "note": (
            "Level 4 — Admin Access. KHÔNG có emergency bypass. "
            "Yêu cầu training bắt buộc về security policy. "
            "Thời gian xử lý: 5 ngày làm việc."
        ),
    },
}


def tool_check_access_permission(access_level: int, requester_role: str, is_emergency: bool = False) -> dict:
    """Kiểm tra điều kiện cấp quyền theo Access Control SOP."""
    rule = ACCESS_RULES.get(access_level)
    if not rule:
        return {"error": f"Access level {access_level} không hợp lệ. Levels: 1, 2, 3, 4."}

    notes = []
    if is_emergency and rule.get("emergency_can_bypass"):
        notes.append(rule.get("emergency_bypass_note", ""))
        emergency_override = True
    elif is_emergency and not rule.get("emergency_can_bypass"):
        notes.append(rule.get("note", f"Level {access_level} KHÔNG có emergency bypass."))
        emergency_override = False
    else:
        emergency_override = False
        notes.append(rule.get("note", ""))

    return {
        "access_level": access_level,
        "can_grant": True,
        "required_approvers": rule["required_approvers"],
        "approver_count": len(rule["required_approvers"]),
        "emergency_override": emergency_override,
        "notes": notes,
        "source": "access_control_sop.txt",
    }


def tool_create_ticket(priority: str, title: str, description: str = "") -> dict:
    """Tạo ticket mới (MOCK — in log, không tạo thật)."""
    mock_id = f"IT-{9900 + abs(hash(title)) % 99}"
    ticket = {
        "ticket_id": mock_id,
        "priority": priority,
        "title": title,
        "description": description[:200],
        "status": "open",
        "created_at": datetime.now().isoformat(),
        "url": f"https://jira.company.internal/browse/{mock_id}",
        "note": "MOCK ticket — không tồn tại trong hệ thống thật",
    }
    print(f"  [MCP create_ticket] MOCK: {mock_id} | {priority} | {title[:50]}")
    return ticket


# ─────────────────────────────────────────────
# Dispatch Layer — MCP server interface
# ─────────────────────────────────────────────

TOOL_REGISTRY = {
    "search_kb":              tool_search_kb,
    "get_ticket_info":        tool_get_ticket_info,
    "check_access_permission": tool_check_access_permission,
    "create_ticket":          tool_create_ticket,
}


def list_tools() -> list:
    """
    MCP discovery: trả về danh sách tools có sẵn.
    Tương đương với tools/list trong MCP protocol.
    """
    return list(TOOL_SCHEMAS.values())


def dispatch_tool(tool_name: str, tool_input: dict) -> dict:
    """
    MCP execution: nhận tool_name và input, gọi tool tương ứng.
    Tương đương với tools/call trong MCP protocol.

    Args:
        tool_name: tên tool (phải có trong TOOL_REGISTRY)
        tool_input: input dict

    Returns:
        Tool output dict, hoặc error dict nếu thất bại
    """
    if tool_name not in TOOL_REGISTRY:
        return {
            "error": f"Tool '{tool_name}' không tồn tại. Available: {list(TOOL_REGISTRY.keys())}"
        }

    tool_fn = TOOL_REGISTRY[tool_name]
    try:
        result = tool_fn(**tool_input)
        return result
    except TypeError as e:
        return {
            "error": f"Invalid input for tool '{tool_name}': {e}",
            "schema": TOOL_SCHEMAS[tool_name]["inputSchema"],
        }
    except Exception as e:
        return {
            "error": f"Tool '{tool_name}' execution failed: {e}",
        }


# ─────────────────────────────────────────────
# FastAPI HTTP Server (Bonus +2)
# ─────────────────────────────────────────────

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    import uvicorn

    app = FastAPI(
        title="Lab Day 09 — Mock MCP HTTP Server",
        description=(
            "HTTP-based MCP server expose tools cho workers. "
            "Implements tools/list và tools/call endpoints theo MCP protocol."
        ),
        version="1.0.0",
    )

    class ToolCallRequest(BaseModel):
        tool: str
        input: dict = {}

    @app.get("/health")
    def health_check():
        """Health check endpoint."""
        return {"status": "ok", "tools_count": len(TOOL_REGISTRY)}

    @app.get("/tools")
    def http_list_tools():
        """MCP tools/list: trả về danh sách tools có sẵn."""
        return {"tools": list_tools()}

    @app.post("/tools/call")
    def http_call_tool(body: ToolCallRequest):
        """
        MCP tools/call: gọi tool theo tên và input.

        Request body:
            {"tool": "search_kb", "input": {"query": "SLA P1", "top_k": 3}}

        Response:
            {"result": {...}, "tool": "search_kb", "timestamp": "..."}
        """
        result = dispatch_tool(body.tool, body.input)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return {
            "result": result,
            "tool": body.tool,
            "timestamp": datetime.now().isoformat(),
        }

    HAS_FASTAPI = True

except ImportError:
    HAS_FASTAPI = False
    app = None


def start_http_server(host: str = "0.0.0.0", port: int = 8080):
    """Khởi động FastAPI HTTP MCP server."""
    if not HAS_FASTAPI:
        print("❌ FastAPI/uvicorn không được cài đặt. Chạy: pip install fastapi uvicorn")
        return
    import uvicorn
    print(f"🚀 Starting MCP HTTP Server at http://{host}:{port}")
    print(f"   Docs: http://{host}:{port}/docs")
    print(f"   Tools: http://{host}:{port}/tools")
    uvicorn.run(app, host=host, port=port)


# ─────────────────────────────────────────────
# Test & Demo / CLI Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if "--serve" in sys.argv:
        # Khởi động HTTP server (Bonus mode)
        start_http_server()
    else:
        # Chạy test demo
        print("=" * 60)
        print("MCP Server — Tool Discovery & Test")
        print("=" * 60)

        # 1. Discover tools
        print("\n📋 Available Tools:")
        for tool in list_tools():
            print(f"  • {tool['name']}: {tool['description'][:65]}...")

        # 2. Test search_kb
        print("\n🔍 Test: search_kb")
        result = dispatch_tool("search_kb", {"query": "SLA P1 resolution time", "top_k": 2})
        if result.get("chunks"):
            for c in result["chunks"]:
                print(f"  [{c.get('score', '?')}] {c.get('source')}: {str(c.get('text', ''))[:70]}...")
        else:
            print(f"  Result: {result}")

        # 3. Test get_ticket_info
        print("\n🎫 Test: get_ticket_info")
        ticket = dispatch_tool("get_ticket_info", {"ticket_id": "P1-LATEST"})
        print(f"  Ticket: {ticket.get('ticket_id')} | {ticket.get('priority')} | {ticket.get('status')}")
        if ticket.get("notifications_sent"):
            print(f"  Notifications: {ticket['notifications_sent']}")

        # 4. Test check_access_permission — Level 3 emergency
        print("\n🔐 Test: check_access_permission (Level 3, emergency)")
        perm3 = dispatch_tool("check_access_permission", {
            "access_level": 3, "requester_role": "contractor", "is_emergency": True,
        })
        print(f"  Level 3 can_grant: {perm3.get('can_grant')}")
        print(f"  required_approvers: {perm3.get('required_approvers')}")
        print(f"  emergency_override: {perm3.get('emergency_override')}")
        print(f"  notes: {perm3.get('notes')}")

        # 5. Test check_access_permission — Level 2 emergency
        print("\n🔐 Test: check_access_permission (Level 2, emergency)")
        perm2 = dispatch_tool("check_access_permission", {
            "access_level": 2, "requester_role": "contractor", "is_emergency": True,
        })
        print(f"  Level 2 can_grant: {perm2.get('can_grant')}")
        print(f"  emergency_override: {perm2.get('emergency_override')}")
        print(f"  notes: {perm2.get('notes')}")

        # 6. Test invalid tool
        print("\n❌ Test: invalid tool")
        err = dispatch_tool("nonexistent_tool", {})
        print(f"  Error: {err.get('error')}")

        print("\n✅ MCP server test done.")
        if HAS_FASTAPI:
            print("\n🚀 HTTP Server available! Run: python mcp_server.py --serve")
        else:
            print("\n⚠️  FastAPI not installed. Standard mock mode only.")
