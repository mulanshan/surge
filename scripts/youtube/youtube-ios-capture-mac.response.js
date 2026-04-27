/*
 * Temporary iOS YouTube capture helper.
 *
 * It sends redacted player/get_watch response samples to the Mac capture
 * server on the local network. Remove the module after sampling.
 */

const CAPTURE_URL = "http://192.168.50.102:18765/capture";
const MAX_BYTES = 1_500_000;

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return match ? match[1] : "unknown";
}

function bytesFromBody(body) {
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (typeof body === "string") return new TextEncoder().encode(body);
  return new Uint8Array();
}

function redactBytes(bytes) {
  const out = new Uint8Array(bytes);
  let i = 0;
  while (i < out.length) {
    const c = out[i];
    const isTokenChar =
      (c >= 0x30 && c <= 0x39) ||
      (c >= 0x41 && c <= 0x5a) ||
      (c >= 0x61 && c <= 0x7a) ||
      c === 0x5f ||
      c === 0x2d;
    if (!isTokenChar) {
      i += 1;
      continue;
    }

    let j = i + 1;
    while (j < out.length) {
      const cc = out[j];
      if (
        (cc >= 0x30 && cc <= 0x39) ||
        (cc >= 0x41 && cc <= 0x5a) ||
        (cc >= 0x61 && cc <= 0x7a) ||
        cc === 0x5f ||
        cc === 0x2d
      ) {
        j += 1;
      } else {
        break;
      }
    }
    if (j - i >= 20) {
      for (let k = i; k < j; k += 1) out[k] = 0x52;
    }
    i = j;
  }
  return out;
}

function toBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.slice(i, i + chunkSize));
  }
  return btoa(binary);
}

const rawBody = $response.body !== undefined ? $response.body : $response.bodyBytes;
const bytes = bytesFromBody(rawBody);
const endpoint = endpointFromUrl($request.url);

if (bytes.length > 0 && bytes.length <= MAX_BYTES) {
  const safe = redactBytes(bytes);
  const payload = {
    capturedAt: new Date().toISOString(),
    endpoint,
    url: $request.url,
    method: $request.method,
    status: $response.status,
    requestHeaders: $request.headers || {},
    responseHeaders: $response.headers || {},
    bodyKind: Object.prototype.toString.call(rawBody),
    bodyType: typeof rawBody,
    size: bytes.length,
    redacted: true,
    bodyBase64: toBase64(safe),
  };

  $httpClient.post(
    {
      url: CAPTURE_URL,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    () => $done({}),
  );
} else {
  $done({});
}
