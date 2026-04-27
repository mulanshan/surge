/*
 * Self-written YouTube cleaner for Surge.
 *
 * Handles:
 * - JSON youtubei responses with readable field edits.
 * - Binary protobuf youtubei responses with a conservative generic cleaner.
 *
 * Does not include third-party source code.
 */

const DEFAULTS = {
  captionLang: "off",
  lyricLang: "off",
  blockUpload: true,
  blockImmersive: true,
  blockShorts: false,
  debug: false,
};

const config = parseArgument();
const textDecoder = new TextDecoder();
const textEncoder = new TextEncoder();

const AD_MARKERS = [
  "pagead",
  "googleadservices",
  "doubleclick.net",
  "/aclk?",
  "/pagead/",
  "adview",
  "ad_break",
  "adformat",
  "initplayback",
  "&oad=",
];

function parseArgument() {
  try {
    return Object.assign({}, DEFAULTS, JSON.parse($argument || "{}"));
  } catch {
    return DEFAULTS;
  }
}

function debug(...args) {
  if (config.debug) console.log("[YouTube Self]", ...args);
}

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return match ? match[1] : "";
}

function bytesFromBody(body) {
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (typeof body === "string") return textEncoder.encode(body);
  return new Uint8Array();
}

function bodyText(body) {
  if (typeof body === "string") return body;
  return textDecoder.decode(bytesFromBody(body));
}

function hasMarker(text) {
  const lower = text.toLowerCase();
  return AD_MARKERS.some((marker) => lower.includes(marker));
}

function hasBlockedGuideMarker(text) {
  if (config.blockUpload && text.includes("FEuploads")) return true;
  if (config.blockImmersive && text.includes("FEmusic_immersive")) return true;
  if (config.blockShorts && text.includes("FEshorts")) return true;
  return false;
}

function readVarint(buf, pos, end) {
  let value = 0;
  let shift = 0;
  const start = pos;
  while (pos < end && shift < 35) {
    const byte = buf[pos++];
    value += (byte & 0x7f) * 2 ** shift;
    if ((byte & 0x80) === 0) return { value, pos, raw: buf.slice(start, pos) };
    shift += 7;
  }
  throw new Error("invalid varint");
}

function writeVarint(value, out) {
  value = Number(value);
  while (value > 127) {
    out.push((value & 0x7f) | 0x80);
    value = Math.floor(value / 128);
  }
  out.push(value);
}

function parseFields(buf, start = 0, end = buf.length) {
  const fields = [];
  let pos = start;
  while (pos < end) {
    const fieldStart = pos;
    const tag = readVarint(buf, pos, end);
    pos = tag.pos;
    const no = Math.floor(tag.value / 8);
    const wire = tag.value & 7;
    if (no <= 0 || wire > 5) throw new Error("invalid tag");

    if (wire === 0) {
      const value = readVarint(buf, pos, end);
      pos = value.pos;
      fields.push({ no, wire, raw: buf.slice(fieldStart, pos) });
    } else if (wire === 1) {
      if (pos + 8 > end) throw new Error("overflow fixed64");
      pos += 8;
      fields.push({ no, wire, raw: buf.slice(fieldStart, pos) });
    } else if (wire === 2) {
      const len = readVarint(buf, pos, end);
      pos = len.pos;
      if (pos + len.value > end) throw new Error("overflow bytes");
      const data = buf.slice(pos, pos + len.value);
      pos += len.value;
      fields.push({ no, wire, tag: tag.raw, data, raw: buf.slice(fieldStart, pos) });
    } else if (wire === 5) {
      if (pos + 4 > end) throw new Error("overflow fixed32");
      pos += 4;
      fields.push({ no, wire, raw: buf.slice(fieldStart, pos) });
    } else {
      throw new Error("unsupported group");
    }
  }
  return fields;
}

function isLikelyText(bytes) {
  if (bytes.length === 0) return true;
  let printable = 0;
  for (const b of bytes) {
    if (b === 9 || b === 10 || b === 13 || (b >= 32 && b <= 126) || b >= 0x80) printable += 1;
  }
  return printable / bytes.length > 0.9;
}

function serializeLengthField(field, data) {
  const out = Array.from(field.tag);
  writeVarint(data.length, out);
  out.push(...data);
  return new Uint8Array(out);
}

function concat(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function cleanProtobufMessage(buf, depth = 0) {
  if (depth > 24 || buf.length === 0) return { bytes: buf, changed: false };

  let fields;
  try {
    fields = parseFields(buf);
  } catch {
    return { bytes: buf, changed: false };
  }

  let changed = false;
  const chunks = [];
  for (const field of fields) {
    if (field.wire !== 2) {
      chunks.push(field.raw);
      continue;
    }

    const text = isLikelyText(field.data) ? textDecoder.decode(field.data) : "";
    if (text && (hasMarker(text) || hasBlockedGuideMarker(text))) {
      changed = true;
      continue;
    }

    const nested = cleanProtobufMessage(field.data, depth + 1);
    if (nested.changed) {
      chunks.push(serializeLengthField(field, nested.bytes));
      changed = true;
      continue;
    }

    if (field.data.length > 16) {
      const looseText = text || textDecoder.decode(field.data);
      if (hasMarker(looseText) || hasBlockedGuideMarker(looseText)) {
        changed = true;
        continue;
      }
    }

    chunks.push(field.raw);
  }

  return changed ? { bytes: concat(chunks), changed: true } : { bytes: buf, changed: false };
}

function isAdLikeObject(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  if (
    keys.some((key) =>
      [
        "adSlotRenderer",
        "displayAdRenderer",
        "promotedSparklesWebRenderer",
        "promotedVideoRenderer",
        "searchPyvRenderer",
        "inFeedAdLayoutRenderer",
        "carouselAdRenderer",
      ].includes(key)
    )
  ) {
    return true;
  }
  const text = JSON.stringify(value);
  return hasMarker(text);
}

function walkJson(value) {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (let i = value.length - 1; i >= 0; i -= 1) {
      if (isAdLikeObject(value[i]) || hasBlockedGuideMarker(JSON.stringify(value[i] || ""))) {
        value.splice(i, 1);
      } else {
        walkJson(value[i]);
      }
    }
    return;
  }
  for (const key of Object.keys(value)) {
    if (["adPlacements", "adSlots", "playerAds", "adBreakHeartbeatParams"].includes(key)) {
      delete value[key];
      continue;
    }
    if (key === "pageadViewthroughconversion") {
      delete value[key];
      continue;
    }
    walkJson(value[key]);
  }
}

function enhanceJsonPlayer(payload) {
  payload.playabilityStatus = payload.playabilityStatus || {};
  payload.playabilityStatus.pictureInPictureRender = {
    pictureInPictureAbility: { active: true, f4: 0, f6: 0, f8: 1 },
  };
  payload.playabilityStatus.backgroundPlayerRender = {
    backgroundAbility: { active: true },
  };
}

function cleanJson(text, endpoint) {
  const payload = JSON.parse(text);
  if (endpoint === "player") enhanceJsonPlayer(payload);
  walkJson(payload);
  return JSON.stringify(payload);
}

const endpoint = endpointFromUrl($request.url);
const originalBody = $response.bodyBytes || $response.body;
const bytes = bytesFromBody(originalBody);

try {
  const text = bodyText(originalBody);
  if (text.trim().startsWith("{") || text.trim().startsWith("[")) {
    const output = cleanJson(text, endpoint);
    debug("json", endpoint, text.length, output.length);
    $done({ body: output });
  } else {
    const result = cleanProtobufMessage(bytes);
    debug("protobuf", endpoint, bytes.length, result.bytes.length, result.changed);
    $done(result.changed ? { bodyBytes: result.bytes } : {});
  }
} catch (error) {
  debug("skip", endpoint, error.message);
  $done({});
}
