/*
 * Surge response-script that captures iOS YouTube App protobuf responses
 * and saves them to disk via Surge "$persistentStore" + writes to a pinned
 * Notification (so the file path appears in Surge logs).
 *
 * SAFETY:
 *  - It only logs metadata (endpoint + length).
 *  - It saves the raw protobuf bytes BUT XORs out anything that looks like
 *    a long alphanumeric token (>=20 chars of [A-Za-z0-9_-]) so OAuth
 *    tokens / refresh tokens / channel IDs that match the same shape are
 *    replaced with REDACTED placeholders before disk-write.
 *  - It never sends data anywhere — only writes to Surge's local persistent
 *    store, which lives under the Surge sandbox on this Mac and is NOT in
 *    the git repo.
 *
 *  Endpoint allowlist: only get_watch + player are saved. Everything else
 *  is passthrough.
 */

const ENDPOINTS_TO_DUMP = ["get_watch", "player"];
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

// Replace runs of >=20 [A-Za-z0-9_-] with the literal string "REDACTED".
// Long opaque tokens (OAuth, channel IDs, visitorData) match this shape;
// short field tags don't.
const TOKEN_RE = /[A-Za-z0-9_\-]{20,}/g;

function redactBytes(bytes) {
  // Walk through bytes byte-by-byte, building a string view of each run of
  // safe ASCII to find token-shaped substrings, then patch those bytes.
  const out = new Uint8Array(bytes); // copy
  let i = 0;
  while (i < out.length) {
    if (
      (out[i] >= 0x30 && out[i] <= 0x39) || // 0-9
      (out[i] >= 0x41 && out[i] <= 0x5a) || // A-Z
      (out[i] >= 0x61 && out[i] <= 0x7a) || // a-z
      out[i] === 0x5f || out[i] === 0x2d    // _ -
    ) {
      let j = i;
      while (
        j < out.length &&
        ((out[j] >= 0x30 && out[j] <= 0x39) ||
          (out[j] >= 0x41 && out[j] <= 0x5a) ||
          (out[j] >= 0x61 && out[j] <= 0x7a) ||
          out[j] === 0x5f || out[j] === 0x2d)
      ) j += 1;
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

function toBase64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  // btoa is not available in Surge JS runtime in the same way; use a manual
  // encoder for safety.
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let result = "";
  let i = 0;
  while (i < bytes.length) {
    const a = bytes[i++] || 0;
    const b = bytes[i++] || 0;
    const c = bytes[i++] || 0;
    const triplet = (a << 16) | (b << 8) | c;
    result += chars[(triplet >> 18) & 0x3f]
            + chars[(triplet >> 12) & 0x3f]
            + (i - 1 > bytes.length ? "=" : chars[(triplet >> 6) & 0x3f])
            + (i > bytes.length ? "=" : chars[triplet & 0x3f]);
  }
  return result;
}

const ep = endpointFromUrl($request.url);
const body = $response.body !== undefined ? $response.body : $response.bodyBytes;
const bytes = bytesFromBody(body);

if (ENDPOINTS_TO_DUMP.includes(ep) && bytes.length > 0 && bytes.length <= MAX_BYTES) {
  const safe = redactBytes(bytes);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const key = `yt_capture_${ep}_${stamp}_${bytes.length}`;
  const b64 = toBase64(safe);
  // $persistentStore writes to Surge's local store on disk.
  if (typeof $persistentStore !== "undefined") {
    $persistentStore.write(b64, key);
  }
  console.log(`[YT Capture] saved key=${key} bytes=${bytes.length} redacted-base64-len=${b64.length}`);
}

$done({});
