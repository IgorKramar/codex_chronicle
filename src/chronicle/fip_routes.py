"""Public routing metadata shared by HTTP and remote clients."""

ROUTES = {
    "get_capabilities": ("GET", "/v1/capabilities"),
    "list_projects": ("GET", "/v1/memory/projects"),
    "get_project_state": ("GET", "/v1/memory/projects/{project_id}/state"),
    "get_project_history": ("GET", "/v1/memory/projects/{project_id}/history"),
    "list_sessions": ("GET", "/v1/memory/sessions"),
    "get_session_details": ("GET", "/v1/memory/projects/{project_id}/sessions/{session_id:path}"),
    "search_knowledge": ("GET", "/v1/memory/search"),
    "get_decisions": ("GET", "/v1/memory/projects/{project_id}/decisions"),
    "get_failures": ("GET", "/v1/memory/projects/{project_id}/failures"),
    "get_artifacts": ("GET", "/v1/memory/projects/{project_id}/artifacts"),
    "get_test_results": ("GET", "/v1/memory/projects/{project_id}/test-results"),
    "append_event": ("POST", "/v1/memory/events"),
    "register_decision": ("POST", "/v1/memory/decisions"),
    "register_artifact": ("POST", "/v1/memory/artifacts"),
}
