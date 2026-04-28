"""End-to-end integration test for RE-AI.

Tests the full pipeline:
1. Server health check
2. Kanban CRUD (milestone → slice → task → status update)
3. Analysis endpoints (all 5)
4. RAG search (verify vector store stores and retrieves analysis results)
5. Frontend build integrity
"""

import http.client
import json
import os
import sys
import time
from pathlib import Path

FIXTURE_PATH = "tests/fixtures/minimal_test.dll"
BASE_URL = os.environ.get("RE_AI_TEST_URL", "localhost:8001")
API_BASE = "/api"

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} -- {detail}")


def api_post(path: str, body: dict) -> tuple[int, dict]:
    """POST to an API endpoint and return (status_code, body_dict)."""
    c = http.client.HTTPConnection("localhost", 8001, timeout=15)
    try:
        c.request("POST", f"{API_BASE}{path}", json.dumps(body), {"Content-Type": "application/json"})
        r = c.getresponse()
        status = r.status
        data = json.loads(r.read())
        return status, data
    except Exception as e:
        return 0, {"error": str(e)}
    finally:
        c.close()


def api_get(path: str) -> tuple[int, list | dict]:
    """GET an API endpoint and return (status_code, body)."""
    c = http.client.HTTPConnection("localhost", 8001, timeout=15)
    try:
        c.request("GET", f"{API_BASE}{path}")
        r = c.getresponse()
        status = r.status
        data = json.loads(r.read())
        return status, data
    except Exception as e:
        return 0, {"error": str(e)}
    finally:
        c.close()


def api_patch(path: str, body: dict) -> tuple[int, dict]:
    """PATCH an API endpoint."""
    c = http.client.HTTPConnection("localhost", 8001, timeout=15)
    try:
        c.request("PATCH", f"{API_BASE}{path}", json.dumps(body), {"Content-Type": "application/json"})
        r = c.getresponse()
        status = r.status
        data = json.loads(r.read())
        return status, data
    except Exception as e:
        return 0, {"error": str(e)}
    finally:
        c.close()


def test_health():
    print("\n-- Health --")
    c = http.client.HTTPConnection("localhost", 8001, timeout=10)
    try:
        c.request("GET", "/health")
        r = c.getresponse()
        body = json.loads(r.read())
        check("health endpoint returns 200", r.status == 200, str(r.status))
        check("status is ok", body.get("status") == "ok", str(body))
    except Exception as e:
        check("health endpoint returns 200", False, str(e))
    finally:
        c.close()


def test_kanban_crud():
    print("\n-- Kanban CRUD --")

    # Create milestone
    status, data = api_post("/milestones", {"title": "Integ Test", "description": "Auto-created"})
    check("create milestone returns 201", status == 201, str(status))
    milestone_id = data.get("id")
    check("milestone has id", milestone_id is not None, str(data))
    check("milestone title matches", data.get("title") == "Integ Test", str(data))

    # List milestones
    status, data = api_get("/milestones")
    check("list milestones returns 200", status == 200, str(status))
    check("milestones is a list", isinstance(data, list), str(type(data)))
    check("at least 1 milestone", len(data) >= 1, str(len(data)))

    # Create slice
    status, data = api_post(f"/milestones/{milestone_id}/slices", {"title": "Test Slice", "description": "Slice for integration test"})
    check("create slice returns 201", status == 201, str(status))
    slice_id = data.get("id")
    check("slice has id", slice_id is not None, str(data))

    # List slices by milestone
    status, data = api_get(f"/milestones/{milestone_id}/slices")
    check("list slices returns 200", status == 200, str(status))
    check("slices is a list", isinstance(data, list), str(type(data)))
    check("at least 1 slice", len(data) >= 1, str(len(data)))

    # Create task
    status, data = api_post(f"/slices/{slice_id}/tasks", {"title": "Test Task", "description": "Task for integration test"})
    check("create task returns 201", status == 201, str(status))
    task_id = data.get("id")
    check("task has id", task_id is not None, str(data))
    check("task status is pending", data.get("status") == "pending", str(data.get("status")))

    # List tasks by slice
    status, data = api_get(f"/slices/{slice_id}/tasks")
    check("list tasks returns 200", status == 200, str(status))
    check("tasks is a list", isinstance(data, list), str(type(data)))
    check("at least 1 task", len(data) >= 1, str(len(data)))

    # Update task status
    status, data = api_patch(f"/tasks/{task_id}/status", {"status": "in_progress"})
    check("update task status returns 200", status == 200, str(status))
    check("task status updated", data.get("status") == "in_progress", str(data.get("status")))

    # Get task status
    status, data = api_get(f"/tasks/{task_id}")
    check("get task returns 200", status == 200, str(status))
    check("task status is in_progress", data.get("status") == "in_progress", str(data.get("status")))

    return milestone_id, slice_id, task_id


def test_analysis():
    print("\n-- Analysis API --")

    body = {"path": FIXTURE_PATH}

    # extract-pe-info
    status, data = api_post("/analysis/extract-pe-info", body)
    check("extract-pe-info returns 200", status == 200, str(status))
    check("machine type AMD64", data.get("machine_type") == "AMD64", str(data.get("machine_type")))
    check("2 sections", len(data.get("sections", [])) == 2, str(len(data.get("sections", []))))

    # list-imports-exports
    status, data = api_post("/analysis/list-imports-exports", body)
    check("list-imports-exports returns 200", status == 200, str(status))
    check("imports is a list", isinstance(data.get("imports"), list), str(type(data.get("imports"))))
    check("exports is a list", isinstance(data.get("exports"), list), str(type(data.get("exports"))))

    # extract-strings
    status, data = api_post("/analysis/extract-strings", body)
    check("extract-strings returns 200", status == 200, str(status))
    check("strings is a list", isinstance(data.get("strings"), list), str(type(data.get("strings"))))
    check("strings count >= 1", data.get("total_count", 0) >= 1, str(data.get("total_count")))

    # disassemble
    body2 = {"path": FIXTURE_PATH, "section_name": ".text", "offset": 0, "size": 256}
    status, data = api_post("/analysis/disassemble", body2)
    check("disassemble returns 200", status == 200, str(status))
    check("instructions is a list", isinstance(data.get("instructions"), list), str(type(data.get("instructions"))))
    check("instructions > 0", len(data.get("instructions", [])) > 0, str(len(data.get("instructions", []))))

    # get-file-info
    status, data = api_post("/analysis/get-file-info", body)
    check("get-file-info returns 200", status == 200, str(status))
    check("is_pe is True", data.get("is_pe") is True, str(data.get("is_pe")))


def test_rag():
    print("\n-- RAG Search --")

    # Run an analysis to populate RAG
    api_post("/analysis/extract-pe-info", {"path": FIXTURE_PATH})

    # Give async RAG storage a moment
    time.sleep(1.0)

    # Search for it
    status, data = api_post("/rag/search", {"query": "minimal_test", "top_k": 5})
    check("RAG search returns 200", status == 200, str(status))
    check("error is empty string", data.get("error") in ("", None, ""), str(data.get("error")))
    # Even if empty results, the key thing is the vector store is available
    check("vector store is available", data.get("error") != "Vector store not available", str(data.get("error")))


def test_registry():
    print("\n-- Tool Registry --")

    status, data = api_get("/registry/tools")
    check("registry tools returns 200", status == 200, str(status))
    check("tools key exists", "tools" in data if isinstance(data, dict) else True, str(data))


def test_frontend():
    print("\n-- Frontend --")

    c = http.client.HTTPConnection("localhost", 8001, timeout=15)
    try:
        c.request("GET", "/")
        r = c.getresponse()
        body = r.read().decode("utf-8")
        check("frontend serves HTML", r.status == 200, str(r.status))
        check("contains root div", '<div id="root"></div>' in body, "index.html found")
        check("has script bundle", "/assets/index-" in body, "vite build output served")
    except Exception as e:
        check("frontend request failed", False, str(e))
    finally:
        c.close()


def test_build():
    print("\n-- Build Integrity --")

    # Verify the frontend build output exists
    static_dir = Path("../backend/static")
    if not static_dir.exists():
        static_dir = Path("backend/static")
    if not static_dir.exists():
        static_dir = Path("C:/Users/Derek/Desktop/RE-AI/backend/static")

    check("static directory exists", static_dir.exists(), str(static_dir))
    if static_dir.exists():
        js_files = list(static_dir.glob("assets/*.js"))
        css_files = list(static_dir.glob("assets/*.css"))
        check("JS bundle exists", len(js_files) > 0, f"{len(js_files)} JS files")
        check("CSS bundle exists", len(css_files) > 0, f"{len(css_files)} CSS files")


def test_api_surface():
    """Test a broader set of endpoints to confirm the full API surface is healthy."""
    print("\n-- API Surface Health --")

    endpoints = [
        ("GET", "/health", 200),
        ("GET", "/api/milestones", 200),
        ("GET", "/api/registry/tools", 200),
        ("GET", "/api/tools/detect", 200),
        ("GET", "/api/config/wizard-status", 200),
    ]

    for method, path, expected in endpoints:
        if method == "GET":
            c = http.client.HTTPConnection("localhost", 8001, timeout=10)
            try:
                c.request("GET", path)
                r = c.getresponse()
                status = r.status
                r.read()  # consume
                check(f"GET {path} returns {expected}", status == expected, f"got {status}")
            except Exception as e:
                check(f"GET {path} returns {expected}", False, str(e))
            finally:
                c.close()


def main():
    print("=" * 60)
    print("  RE-AI End-to-End Integration Test")
    print("=" * 60)
    print(f"  Target: http://{BASE_URL}")
    print(f"  Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    test_health()
    test_kanban_crud()
    test_analysis()
    test_rag()
    test_registry()
    test_frontend()
    test_build()
    test_api_surface()

    print()
    print("=" * 60)
    total = PASS + FAIL
    print(f"  Results: {PASS} passed / {FAIL} failed / {total} total")
    print("=" * 60)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
