"""Generate the contract of implemented routes, not the future design surface."""

import json
import os
from pathlib import Path
from fairy.app import create_app

database_url = os.getenv("FAIRY_TEST_POSTGRES_URL")
if not database_url:
    raise SystemExit("FAIRY_TEST_POSTGRES_URL is required for contract generation")
app = create_app(database_url, token="schema-generation-only")
api = next(route.app for route in app.routes if getattr(route, "path", None) == "/v2")
schema = api.openapi()
schema["info"] = {"title": "Fairy implemented v2 API", "version": "0.3.0"}
schema["servers"] = [{"url": "/v2"}]
schema.setdefault("components", {}).setdefault("securitySchemes", {})["Bearer"] = {
    "type": "http",
    "scheme": "bearer",
}
schema["security"] = [{"Bearer": []}]
Path("contracts").mkdir(exist_ok=True)
Path("contracts/openapi.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
)
