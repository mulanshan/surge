import http from "node:http";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const outDir = "/Users/mulanshan/surge/captures/youtube";
const port = 18765;
mkdirSync(outDir, { recursive: true });

function safeName(value) {
  return String(value || "unknown").replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 120);
}

const server = http.createServer((req, res) => {
  if (req.method !== "POST" || req.url !== "/capture") {
    res.writeHead(404);
    res.end("not found");
    return;
  }

  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    try {
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const now = new Date().toISOString().replace(/[:.]/g, "-");
      const endpoint = safeName(payload.endpoint);
      const id = `${now}_${endpoint}_${safeName(payload.status)}_${safeName(payload.size)}`;
      writeFileSync(join(outDir, `${id}.json`), JSON.stringify(payload, null, 2));
      if (payload.bodyBase64) {
        writeFileSync(join(outDir, `${id}.bin`), Buffer.from(payload.bodyBase64, "base64"));
      }
      console.log(`[capture] ${id} ${payload.url || ""}`);
      res.writeHead(204);
      res.end();
    } catch (error) {
      console.error("[capture-error]", error);
      res.writeHead(500);
      res.end(String(error));
    }
  });
});

server.listen(port, "0.0.0.0", () => {
  console.log(`YouTube capture server listening on http://0.0.0.0:${port}/capture`);
});
