"""
GLPI API Proxy — MCP bridge for Scraper-Server.
SPEC: SPEC.md §6 (infrastructure observability)
Endpoints confirmed against GLPI proxy v2.2:
  - GET  /Tickets?assigned_id=&status_id=   server-side filter
  - GET  /Assistance/Ticket/{id}            full ticket detail
  - GET  /Assistance/Ticket/{id}/Timeline   followup thread
  - POST /Assistance/Ticket/{id}/Timeline/Followup  post reply
  - PATCH /Assistance/Ticket/{id}           update status
"""
import json
import httpx
from mcp.server.fastmcp import FastMCP

PROXY_URL     = "http://100.112.16.115:8080/api/v2.2"
CLIENT_ID     = "5880211c5e72134f1ae47dda08377e4b503bd3d15f93d858dda5ab82a4a000e0"
CLIENT_SECRET = "b6d8fbdc08f6443abce916dae0d5184f56793a50782130e3c6fa6153692d165c"
USERNAME      = "AlgoTrade Server"
PASSWORD      = "45237348"
USER_ID       = 13  # AlgoTrade Server
GLPI_PROXY_ID = 14  # GLPI_PROXY user

mcp = FastMCP("glpi-scraper-proxy")


def _get_token() -> str:
    r = httpx.post(f"{PROXY_URL}/token", json={
        "grant_type": "password", "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET, "username": USERNAME,
        "password": PASSWORD, "scope": "api user",
    }, timeout=15)
    return r.json()["access_token"]

def _h() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


@mcp.tool()
def proxy_health() -> str:
    """Check GLPI proxy health."""
    try:
        r = httpx.get(f"{PROXY_URL}/Health", timeout=10)
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def create_server_ticket(title: str, description: str, assigned_id: int | None = None, urgency: int = 3) -> str:
    """
    Create a GLPI ticket as Scraper-Server (requester).
    title: short, meaningful summary of the request
    description: full context — what is needed, why, and specific details
    assigned_id: optional user ID to assign the ticket to (e.g. GLPI_PROXY=14)
    urgency: 1=very high … 5=very low
    Returns ticket id.
    """
    try:
        h = _h()
        r = httpx.post(f"{PROXY_URL}/Assistance/Ticket", headers=h, json={
            "name": title, "content": description,
            "type": 1, "urgency": urgency, "impact": 3, "priority": 3,
        }, timeout=15)
        ticket_id = r.json()["id"]
        httpx.post(f"{PROXY_URL}/Assistance/Ticket/{ticket_id}/TeamMember", headers=h, json={
            "type": "User", "id": USER_ID, "role": "requester",
        }, timeout=15)
        if assigned_id is not None:
            httpx.post(f"{PROXY_URL}/Assistance/Ticket/{ticket_id}/TeamMember", headers=h, json={
                "type": "User", "id": assigned_id, "role": "assigned",
            }, timeout=15)
        return json.dumps({"id": ticket_id}, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def list_server_tickets(
    requester_id: int | None = None,
    assigned_id: int | None = None,
    status_id: int | None = None,
) -> str:
    """
    List tickets with server-side filtering via GET /Tickets.
    requester_id: filter by requester (default: 15 = Scraper-Server)
    assigned_id: filter by assigned user ID
    status_id: 1=New 2=Processing(assigned) 3=Processing(planned) 4=Pending 5=Solved 6=Closed
    Returns id, name, status, requester, user_editor for each match.
    """
    try:
        params: dict = {}
        if assigned_id is not None:
            params["assigned_id"] = assigned_id
        if status_id is not None:
            params["status_id"] = status_id

        # Use server-side filter if any param given, else fetch all and filter client-side
        if params:
            r = httpx.get(f"{PROXY_URL}/Tickets", params=params, headers=_h(), timeout=15)
            tickets = r.json() if isinstance(r.json(), list) else []
        else:
            # paginate all
            tickets, offset = [], 0
            while True:
                r = httpx.get(f"{PROXY_URL}/Tickets?limit=100&start={offset}", headers=_h(), timeout=15)
                page = r.json() if isinstance(r.json(), list) else []
                if not page:
                    break
                tickets.extend(page)
                if len(page) < 100:
                    break
                offset += 100

        # Apply requester filter client-side only when no assigned_id filter is active
        def _row(t):
            return {
                "id": t["id"],
                "name": t.get("name"),
                "status": (t.get("status") or {}).get("name"),
                "status_id": (t.get("status") or {}).get("id"),
                "requester": (t.get("user_recipient") or {}).get("name"),
                "user_editor": (t.get("user_editor") or {}).get("name"),
                "is_deleted": t.get("is_deleted"),
            }
        if assigned_id is not None:
            result = [_row(t) for t in tickets]
        else:
            req_id = requester_id if requester_id is not None else USER_ID
            result = [_row(t) for t in tickets if (t.get("user_recipient") or {}).get("id") == req_id]
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_ticket(ticket_id: int) -> str:
    """
    Get full detail of a single ticket: id, name, content, status, user_editor, team.
    user_editor shows who last modified the ticket (e.g. GLPI_PROXY responding).
    is_deleted=true means the ticket was rejected/removed.
    """
    try:
        r = httpx.get(f"{PROXY_URL}/Assistance/Ticket/{ticket_id}", headers=_h(), timeout=15)
        t = r.json()
        return json.dumps({
            "id": t.get("id"),
            "name": t.get("name"),
            "content": t.get("content"),
            "status": (t.get("status") or {}).get("name"),
            "status_id": (t.get("status") or {}).get("id"),
            "is_deleted": t.get("is_deleted"),
            "user_editor": (t.get("user_editor") or {}).get("name"),
            "requester": (t.get("user_recipient") or {}).get("name"),
            "team": [(m["role"], m["name"]) for m in t.get("team", [])],
            "date_solve": t.get("date_solve"),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_ticket_timeline(ticket_id: int) -> str:
    """
    Get the followup thread for a ticket via GET /Assistance/Ticket/{id}/Timeline.
    Returns list of {type, content, user, date} entries.
    """
    try:
        r = httpx.get(f"{PROXY_URL}/Assistance/Ticket/{ticket_id}/Timeline",
                      headers=_h(), timeout=15)
        items = r.json() if isinstance(r.json(), list) else []
        return json.dumps([
            {
                "type": item.get("type"),
                "content": (item.get("item") or {}).get("content"),
                "user": ((item.get("item") or {}).get("user") or {}).get("name"),
                "date": (item.get("item") or {}).get("date"),
            }
            for item in items
        ], ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def reply_to_ticket(ticket_id: int, content: str, is_private: bool = False) -> str:
    """
    Post a followup reply to a ticket via POST /Assistance/Ticket/{id}/Timeline/Followup.
    """
    try:
        r = httpx.post(
            f"{PROXY_URL}/Assistance/Ticket/{ticket_id}/Timeline/Followup",
            headers=_h(), json={"content": content, "is_private": is_private}, timeout=15,
        )
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def complete_server_ticket(ticket_id: int, solution: str = "Tarea completada por agente.") -> str:
    """
    Post a followup reply with the solution text, then mark ticket as solved (status=5).
    solution: describe what was done — this appears in the ticket timeline.
    """
    try:
        h = _h()
        # 1. Post followup so solution is visible in timeline
        httpx.post(
            f"{PROXY_URL}/Assistance/Ticket/{ticket_id}/Timeline/Followup",
            headers=h, json={"content": solution}, timeout=15,
        )
        # 2. Close ticket
        r = httpx.patch(f"{PROXY_URL}/Assistance/Ticket/{ticket_id}", headers=h,
                        json={"status": 5}, timeout=15)
        try:
            return json.dumps(r.json(), ensure_ascii=False)
        except Exception:
            return json.dumps({"status": r.status_code, "body": r.text or "ok"})
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def close_ticket(ticket_id: int) -> str:
    """Mark a ticket as Closed (status=6)."""
    try:
        r = httpx.patch(f"{PROXY_URL}/Assistance/Ticket/{ticket_id}", headers=_h(),
                        json={"status": 6}, timeout=15)
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
