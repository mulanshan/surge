/*
 * Surge response-script: capture iOS YouTube App protobuf get_watch / player
 * responses, REDACT long token-shaped substrings, and POST the redacted
 * bytes to a local-only sink at http://127.0.0.1:18819/capture.
 *
 * Privacy:
 *  - redactBytes() replaces every run of >=20 [A-Za-z0-9_-] with 'R'
 *    BEFORE the bytes leave this script. OAuth tokens, channel IDs,
 *    visitorData, etc. (which all match that shape) become R-runs first.
 *  - The destination is loopback 127.0.0.1 — never leaves this Mac.
 */

const SINK = "http://127.0.0.1:18819/capture";
const ENDPOINTS = ["get_watch", "player"];
const MAX_BYTES = 2_000_000;

function endpointFromUrl(url) {
  const m = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return m ? m[1] : "";
}

function bytesFromBody(body) {
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (typeof body === "string") return new TextEncoder().encode(body);
  return new Uint8Array();
}

function redactBytes(bytes) {
  const out = new Uint8Array(bytes); // copy
  let i = 0;
  while (i < out.length) {
    const c = out[i];
    const isWord =
      (c >= 0x30 && c <= 0x39) ||
      (c >= 0x41 && c <= 0x5a) ||
      (c >= 0x61 && c <= 0x7a) ||
      c === 0x5f || c === 0x2d;
    if (isWord) {
      let j = i;
      while (j < out.length) {
        const cc = out[j];
        if (
          (cc >= 0x30 && cc <= 0x39) ||
          (cc >= 0x41 && cc <= 0x5a) ||
          (cc >= 0x61 && cc <= 0x7a) ||
          cc === 0x5f || cc === 0x2d
        ) j += 1;
        else break;
      }
      if (j - i >= 20) {
        for (let k = i; k < j; k++) out[k] = 0x52; // 'R'
      }
      i = j;
    } else {
      i += 1;
    }
  }
  return out;
}

const ep = endpointFromUrl($request.url);
const body = $response.body !== undefined ? $response.body : $response.bodyBytes;
const bytes = bytesFromBody(body);

if (
  ENDPOINTS.includes(ep) &&
  bytes.length > 0 &&
  bytes.length <= MAX_BYTES
) {
  const safe = redactBytes(bytes);
  // Surge's $httpClient.post accepts {url, headers, body}. body can be a
  // Uint8Array. The local sink stores the bytes raw.
  $httpClient.post(
    {
      url: `${SINK}?endpoint=${encodeURIComponent(ep)}&len=${bytes.length}`,
      headers: { "Content-Type": "application/octet-stream" },
      body: safe,
      timeout: 5,
    },
    (err, resp, _data) => {
      if (err) {
        console.log(`[YT Capture] POST failed: ${err}`);
      } else {
        console.log(`[YT Capture] sent ${ep} bytes=${bytes.length} status=${resp && resp.status}`);
      }
    }
  );
}

$done({});
