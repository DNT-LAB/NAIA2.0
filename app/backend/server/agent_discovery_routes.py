"""Read-only discovery over the app's actual registered routes and source catalog."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.agent_catalog import audit, describe, listing, overview, runtime_catalog, source_catalog


def register_agent_discovery_routes(app: FastAPI, context, *, run_in_thread):
    def catalog():
        return runtime_catalog(source_catalog(context.repo_root), app.openapi(), routes=app.routes)

    @app.get("/api/agent/assets")
    async def agent_assets(request: Request):
        """Offline asset availability and consent instructions; never starts a download."""
        from core.agent_setup import asset_catalog
        from app.backend.server.install_manager_routes import _is_local_request
        result = await run_in_thread(asset_catalog, getattr(context, "agent_source_paths", context.runtime_paths))
        if not _is_local_request(request):
            result.pop("user_data", None)
            for item in result["items"]:
                for key in ("target", "thumbnail_target", "available_at"):
                    item.pop(key, None)
        return result

    @app.get("/api/agent/models")
    async def agent_models():
        """Registered models, feature constraints and exact choice keys; no provider request."""
        from core.agent_setup import model_catalog
        return await run_in_thread(model_catalog, context.runtime_paths, context.get_api_mode())

    @app.get("/api/agent/catalog")
    async def agent_catalog(q: str = "", kind: str = "", offset: int = 0, limit: int = 30, id: str = "", view: str = "list"):
        """Discover or describe HTTP, WebSocket, module, registered service and source-only capabilities.

        id returns full usage/schema information. q searches names, source and
        descriptions. No feature is executed while building this inventory.
        """
        try:
            current = await run_in_thread(catalog)
            if id:
                return {"protocol_version": 1, "fingerprint": current["fingerprint"],
                        "capability": describe(current, id)}
            if view == "overview":
                return overview(current)
            return listing(current, query=q, kind=kind, offset=offset, limit=limit)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/agent/audit")
    async def agent_audit(details: bool = False):
        """Report missing transport/schema links, source/runtime drift and scanned-file coverage.

        details=true includes complete gap lists and the per-file inventory.
        Source-only methods may be internal helpers, not missing user features.
        """
        result = await run_in_thread(lambda: audit(catalog()))
        if not details:
            result = {key: value for key, value in result.items() if key not in {"files", "gaps"}}
        return result
