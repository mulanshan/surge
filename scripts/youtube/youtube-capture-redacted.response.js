/*
 * Surge response-script: capture iOS YouTube App get_watch / player
 * responses, REDACT long token-shaped substrings, then DUMP the redacted
 * bytes as base64 chunks into Surge console.log lines. An external puller
 * reads the console log via Surge HTTP API and reassembles.
 *
 * Privacy: redactBytes() replaces every run of >=20 [A-Za-z0-9_-] with 'R'
 * BEFORE base64 encoding, so OAuth tokens / channel IDs / visitorData
 * never appear in the log.
 *
 * Log format (one line per chunk):
 *   [YTC] id=<sessionId> ep=<endpoint> idx=<i>/<n> len=<totalBytes> data=<base64chunk>
 */

const ENDPOINTS = ["get_watch", "player"];
const MAX_BYTES = 1_500_000;
const CHUNK = 1200;          // base64 chars per log line
const SESSION_ID = String(Date.now()).slice(-8) + Math.floor(Math.random() * 10000);

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
  const out = new Uint8Array(bytes);
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
      if (j - i >= 20) for (let k = i; k < j; k++) out[k] = 0x52;
      i = j;
    } else {
      i += 1;
    }
  }
  return out;
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function toBase64(bytes) {
  let result = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i] || 0;
    const b = bytes[i + 1] || 0;
    const c = bytes[i + 2] || 0;
    const t = (a << 16) | (b << 8) | c;
    result += B64[(t >> 18) & 0x3f] + B64[(t >> 12) & 0x3f];
    result += i + 1 < bytes.length ? B64[(t >> 6) & 0x3f] : "=";
    result += i + 2 < bytes.length ? B64[t & 0x3f] : "=";
  }
  return result;
}

const ep = endpointFromUrl($request.url);
const body = $response.body !== undefined ? $response.body : $response.bodyBytes;
const bytes = bytesFromBody(body);

if (ENDPOINTS.includes(ep) && bytes.length > 0 && bytes.length <= MAX_BYTES) {
  const safe = redactBytes(bytes);
  const b64 = toBase64(safe);
  const total = Math.ceil(b64.length / CHUNK);
  const reqId = SESSION_ID + "_" + Math.floor(Math.random() * 1e6);
  for (let i = 0; i < total; i++) {
    const slice = b64.slice(i * CHUNK, (i + 1) * CHUNK);
    console.log(`[YTC] id=${reqId} ep=${ep} idx=${i + 1}/${total} len=${bytes.length} data=${slice}`);
  }
  console.log(`[YTC] DONE id=${reqId} ep=${ep} bytes=${bytes.length} chunks=${total}`);
}

$done({});
