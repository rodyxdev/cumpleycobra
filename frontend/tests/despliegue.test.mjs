// Despliegue: en producción el frontend nunca cae a localhost en silencio.

import assert from "node:assert/strict";
import { test } from "node:test";

import { LOCAL_API, resolveApiUrl } from "../src/lib/api-url.ts";

test("URL del backend según el entorno", () => {
  assert.equal(resolveApiUrl("https://api.up.railway.app/", "production"), "https://api.up.railway.app");
  assert.equal(resolveApiUrl(undefined, "production"), "");         // sin variable: error claro, no localhost
  assert.equal(resolveApiUrl("  ", "production"), "");
  assert.equal(resolveApiUrl(undefined, "development"), LOCAL_API);
  assert.equal(resolveApiUrl("http://localhost:8001", "production"), "http://localhost:8001");
});
