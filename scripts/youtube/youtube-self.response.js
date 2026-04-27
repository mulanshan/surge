/*
 * Self-written YouTube cleaner for Surge.
 *
 * Behavior:
 * - JSON responses (Web/desktop YouTube): conservative ad-field removal,
 *   plus optional player capability enhancement for picture-in-picture
 *   and background playback.
 * - Binary protobuf responses (iOS/Android YouTube App, YouTube Music App):
 *   schema-light wire editing for the YouTube player response only:
 *   remove known ad fields and inject background/PiP capability fields.
 *
 * Does not include any third-party source code.
 */

const DEFAULTS = {
  captionLang: "off",
  lyricLang: "off",
  blockUpload: true,
  blockImmersive: true,
  blockShorts: false,
  enhancePlayer: true,
  debug: false,
};

const config = parseArgument();

function parseArgument() {
  try {
    return Object.assign({}, DEFAULTS, JSON.parse(typeof $argument === "string" ? $argument : "{}"));
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

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function bodyBytes(body) {
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (typeof body === "string") return new TextEncoder().encode(body);
  return new Uint8Array(0);
}

// Only delete fields that are unambiguously ads. Keep this list narrow so
// we never strip something the YouTube client needs to play a video.
const AD_KEYS_TO_DELETE = [
  "adPlacements",
  "adSlots",
  "playerAds",
  "adBreakHeartbeatParams",
  "pageadViewthroughconversion",
];

const AD_RENDERER_KEYS = [
  "adSlotRenderer",
  "displayAdRenderer",
  "promotedSparklesWebRenderer",
  "promotedVideoRenderer",
  "searchPyvRenderer",
  "inFeedAdLayoutRenderer",
  "carouselAdRenderer",
];

function isAdRenderer(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  for (const key of Object.keys(value)) {
    if (AD_RENDERER_KEYS.includes(key)) return true;
  }
  return false;
}

function isBlockedGuide(value) {
  if (!config.blockUpload && !config.blockImmersive && !config.blockShorts) return false;
  if (!value || typeof value !== "object") return false;
  // Guide entries carry a browseId we can match on.
  const browseId =
    (value.browseEndpoint && value.browseEndpoint.browseId) ||
    (value.endpoint && value.endpoint.browseEndpoint && value.endpoint.browseEndpoint.browseId) ||
    value.browseId;
  if (!browseId || typeof browseId !== "string") return false;
  if (config.blockUpload && browseId === "FEuploads") return true;
  if (config.blockImmersive && browseId === "FEmusic_immersive") return true;
  if (config.blockShorts && browseId === "FEshorts") return true;
  return false;
}

function walkJson(value) {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (let i = value.length - 1; i >= 0; i -= 1) {
      const item = value[i];
      if (isAdRenderer(item) || isBlockedGuide(item)) {
        value.splice(i, 1);
        continue;
      }
      walkJson(item);
    }
    return;
  }
  for (const key of Object.keys(value)) {
    if (AD_KEYS_TO_DELETE.includes(key)) {
      delete value[key];
      continue;
    }
    walkJson(value[key]);
  }
}

function enhanceJsonPlayer(payload) {
  if (!config.enhancePlayer) return;
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
  // player and get_watch both return playabilityStatus / streamingData;
  // inject PiP + background playback capability on either.
  if (endpoint === "player" || endpoint === "get_watch") {
    enhanceJsonPlayer(payload);
  }
  walkJson(payload);
  return JSON.stringify(payload);
}

// Minimal protobuf wire editor. It preserves all unknown fields byte-for-byte
// and only rewrites length-delimited messages that contain fields we explicitly
// know. Field numbers below are observed from YouTube iOS player responses.
const WIRE_VARINT = 0;
const WIRE_64BIT = 1;
const WIRE_LENGTH = 2;
const WIRE_32BIT = 5;

const PLAYER_FIELDS = {
  playabilityStatus: 2,
  adPlacements: 7,
  playbackTracking: 9,
  adSlots: 68,
};

const PLAYABILITY_FIELDS = {
  backgroundPlayerRender: 11,
  pictureInPictureRender: 21,
};

const PLAYBACK_TRACKING_FIELDS = {
  pageadViewthroughconversion: 18,
};

const WATCH_FIELDS = {
  contents: 1,
};

const WATCH_CONTENT_FIELDS = {
  player: 2,
};

const AD_MARKERS = [
  "pagead",
  "googleads",
  "googleadservices",
  "doubleclick.net",
  "adPlacement",
  "adSlots",
];

function readVarint(bytes, offset) {
  let value = 0;
  let shift = 0;
  let pos = offset;
  while (pos < bytes.length && shift <= 35) {
    const byte = bytes[pos++];
    value += (byte & 0x7f) * Math.pow(2, shift);
    if ((byte & 0x80) === 0) return { value, offset: pos };
    shift += 7;
  }
  throw new Error("invalid protobuf varint");
}

function writeVarint(value) {
  const out = [];
  let n = value;
  while (n > 0x7f) {
    out.push((n & 0x7f) | 0x80);
    n = Math.floor(n / 128);
  }
  out.push(n);
  return new Uint8Array(out);
}

function concatBytes(parts) {
  const length = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function encodeTag(fieldNo, wireType) {
  return writeVarint(fieldNo * 8 + wireType);
}

function encodeVarintField(fieldNo, value) {
  return concatBytes([encodeTag(fieldNo, WIRE_VARINT), writeVarint(value)]);
}

function encodeLengthField(fieldNo, payload) {
  return concatBytes([encodeTag(fieldNo, WIRE_LENGTH), writeVarint(payload.length), payload]);
}

function parseFields(bytes) {
  const fields = [];
  let pos = 0;
  while (pos < bytes.length) {
    const start = pos;
    const tag = readVarint(bytes, pos);
    pos = tag.offset;
    const fieldNo = Math.floor(tag.value / 8);
    const wireType = tag.value & 7;
    let valueStart = pos;
    let valueEnd;
    let payload = null;

    if (fieldNo <= 0) throw new Error("invalid protobuf field number");

    if (wireType === WIRE_VARINT) {
      valueEnd = readVarint(bytes, pos).offset;
    } else if (wireType === WIRE_64BIT) {
      valueEnd = pos + 8;
    } else if (wireType === WIRE_LENGTH) {
      const length = readVarint(bytes, pos);
      valueStart = length.offset;
      valueEnd = valueStart + length.value;
      payload = bytes.slice(valueStart, valueEnd);
    } else if (wireType === WIRE_32BIT) {
      valueEnd = pos + 4;
    } else {
      throw new Error(`unsupported protobuf wire type ${wireType}`);
    }

    if (valueEnd > bytes.length) throw new Error("protobuf field exceeds message length");
    fields.push({
      fieldNo,
      wireType,
      start,
      end: valueEnd,
      payload,
      raw: bytes.slice(start, valueEnd),
    });
    pos = valueEnd;
  }
  return fields;
}

function rebuildFields(fields) {
  return concatBytes(fields.map((field) => field.raw));
}

function makeBackgroundPlayerRender() {
  const backgroundAbility = encodeVarintField(1, 1); // active=true
  return encodeLengthField(64657230, backgroundAbility);
}

function makePictureInPictureRender() {
  const pictureAbility = concatBytes([
    encodeVarintField(1, 1), // active=true
    encodeVarintField(8, 1), // observed iOS capability flag
  ]);
  return encodeLengthField(151635310, pictureAbility);
}

function makePlayabilityStatus() {
  return concatBytes([
    encodeLengthField(PLAYABILITY_FIELDS.pictureInPictureRender, makePictureInPictureRender()),
    encodeLengthField(PLAYABILITY_FIELDS.backgroundPlayerRender, makeBackgroundPlayerRender()),
  ]);
}

function enhancePlayabilityStatus(payload) {
  const kept = parseFields(payload).filter(
    (field) =>
      field.fieldNo !== PLAYABILITY_FIELDS.pictureInPictureRender &&
      field.fieldNo !== PLAYABILITY_FIELDS.backgroundPlayerRender,
  );
  kept.push({ raw: encodeLengthField(PLAYABILITY_FIELDS.pictureInPictureRender, makePictureInPictureRender()) });
  kept.push({ raw: encodeLengthField(PLAYABILITY_FIELDS.backgroundPlayerRender, makeBackgroundPlayerRender()) });
  return rebuildFields(kept);
}

function cleanPlaybackTracking(payload) {
  return rebuildFields(
    parseFields(payload).filter((field) => {
      if (field.fieldNo === PLAYBACK_TRACKING_FIELDS.pageadViewthroughconversion) return false;
      if (field.wireType === WIRE_LENGTH && field.payload && bytesContainAdMarker(field.payload)) return false;
      return true;
    }),
  );
}

function cleanPlayerProtobuf(bytes) {
  let sawPlayability = false;
  let changed = false;
  const out = [];

  for (const field of parseFields(bytes)) {
    if (field.fieldNo === PLAYER_FIELDS.adPlacements || field.fieldNo === PLAYER_FIELDS.adSlots) {
      changed = true;
      continue;
    }

    if (field.fieldNo === PLAYER_FIELDS.playabilityStatus && field.wireType === WIRE_LENGTH && field.payload) {
      sawPlayability = true;
      const payload = enhancePlayabilityStatus(field.payload);
      out.push({ raw: encodeLengthField(PLAYER_FIELDS.playabilityStatus, payload) });
      changed = true;
      continue;
    }

    if (field.fieldNo === PLAYER_FIELDS.playbackTracking && field.wireType === WIRE_LENGTH && field.payload) {
      const payload = cleanPlaybackTracking(field.payload);
      out.push({ raw: encodeLengthField(PLAYER_FIELDS.playbackTracking, payload) });
      changed = true;
      continue;
    }

    out.push(field);
  }

  if (!sawPlayability && config.enhancePlayer) {
    out.push({ raw: encodeLengthField(PLAYER_FIELDS.playabilityStatus, makePlayabilityStatus()) });
    changed = true;
  }

  return changed ? rebuildFields(out) : bytes;
}

function cleanWatchContentProtobuf(bytes) {
  let changed = false;
  const out = [];

  for (const field of parseFields(bytes)) {
    if (field.fieldNo === WATCH_CONTENT_FIELDS.player && field.wireType === WIRE_LENGTH && field.payload) {
      const payload = cleanPlayerProtobuf(field.payload);
      out.push({ raw: encodeLengthField(WATCH_CONTENT_FIELDS.player, payload) });
      changed = true;
      continue;
    }
    out.push(field);
  }

  return changed ? rebuildFields(out) : bytes;
}

function cleanWatchProtobuf(bytes) {
  let changed = false;
  const out = [];

  for (const field of parseFields(bytes)) {
    if (field.fieldNo === WATCH_FIELDS.contents && field.wireType === WIRE_LENGTH && field.payload) {
      const payload = cleanWatchContentProtobuf(field.payload);
      out.push({ raw: encodeLengthField(WATCH_FIELDS.contents, payload) });
      changed = true;
      continue;
    }
    out.push(field);
  }

  return changed ? rebuildFields(out) : bytes;
}

function bytesContainAdMarker(bytes) {
  const text = new TextDecoder().decode(bytes);
  return AD_MARKERS.some((marker) => text.includes(marker));
}

function cleanAdMarkedNestedProtobuf(bytes, depth) {
  if (depth <= 0) return bytes;

  let changed = false;
  const out = [];
  for (const field of parseFields(bytes)) {
    if (field.wireType !== WIRE_LENGTH || !field.payload || field.payload.length === 0) {
      out.push(field);
      continue;
    }

    if (bytesContainAdMarker(field.payload)) {
      changed = true;
      continue;
    }

    try {
      const payload = cleanAdMarkedNestedProtobuf(field.payload, depth - 1);
      if (payload !== field.payload) {
        out.push({ raw: encodeLengthField(field.fieldNo, payload) });
        changed = true;
      } else {
        out.push(field);
      }
    } catch {
      out.push(field);
    }
  }

  return changed ? rebuildFields(out) : bytes;
}

function cleanProtobuf(bytes, endpoint) {
  if (endpoint === "player") return cleanPlayerProtobuf(bytes);
  if (endpoint === "get_watch") return cleanAdMarkedNestedProtobuf(cleanWatchProtobuf(bytes), 8);
  if (endpoint === "browse" || endpoint === "next" || endpoint === "search") {
    return cleanAdMarkedNestedProtobuf(bytes, 8);
  }
  return bytes;
}

const endpoint = endpointFromUrl($request.url);
const originalBody = $response.body !== undefined ? $response.body : $response.bodyBytes;

try {
  const text = bodyText(originalBody);
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const output = cleanJson(text, endpoint);
    // Always log JSON path length-change so we can see hits in Surge logs.
    console.log(`[YouTube Self] json ${endpoint} ${text.length} -> ${output.length}`);
    $done({ body: output });
  } else {
    const input = bodyBytes(originalBody);
    const output = cleanProtobuf(input, endpoint);
    if (output.length !== input.length || output !== input) {
      console.log(`[YouTube Self] protobuf ${endpoint} ${input.length} -> ${output.length}`);
      // Surge exposes binary response bodies as $response.body when
      // binary-body-mode is enabled, and accepts a Uint8Array in body.
      $done({ body: output });
    } else {
      console.log(`[YouTube Self] protobuf-passthrough ${endpoint} bytes=${input.length}`);
      $done({});
    }
  }
} catch (error) {
  debug("error", endpoint, error && error.message);
  // On any failure, never return a partial body — let the original through.
  $done({});
}
