function toBase64(bytes) {
  if (!bytes) return "";
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.slice(i, i + chunkSize));
  }
  return btoa(binary);
}

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return match ? match[1] : "unknown";
}

const rawBody = $response.bodyBytes || $response.body;
const bodyBytes =
  rawBody instanceof Uint8Array
    ? rawBody
    : rawBody instanceof ArrayBuffer
      ? new Uint8Array(rawBody)
      : null;
const bodyText = typeof rawBody === "string" ? rawBody : "";
const payload = {
  capturedAt: new Date().toISOString(),
  url: $request.url,
  method: $request.method,
  endpoint: endpointFromUrl($request.url),
  status: $response.status,
  requestHeaders: $request.headers || {},
  responseHeaders: $response.headers || {},
  bodyKind: Object.prototype.toString.call(rawBody),
  bodyType: typeof rawBody,
  size: bodyBytes ? bodyBytes.length : bodyText.length,
  bodyText,
  bodyBase64: toBase64(bodyBytes),
};

$httpClient.post(
  {
    url: "http://127.0.0.1:18765/capture",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  },
  () => $done({})
);
