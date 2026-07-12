/*
 * Self-written YouTube cleaner for Surge.
 *
 * Behavior:
 * - JSON responses (Web/desktop YouTube): conservative ad-field removal,
 *   plus optional player capability enhancement for picture-in-picture
 *   and background playback.
 * - Binary protobuf responses (iOS/Android YouTube App, YouTube Music App):
 *   schema-light wire editing for player/get_watch/account settings, plus
 *   guarded cleanup for next ad fragments and home/search feed ad cards.
 *   Binary bodies are handled as raw bytes (never UTF-8 re-encoded).
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
  if (config.debug) logbook(args.join(" "));
}

function logbook(message) {
  const text = `[YouTube Self] ${message}`;
  console.log(text);
  try {
    if (typeof $surge !== "undefined" && typeof $surge.logbook === "function") {
      $surge.logbook(text);
    }
  } catch {
    // Logbook is diagnostic-only; never let it affect response processing.
  }
}

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return match ? match[1] : "";
}

function isTypedBinary(body) {
  return body instanceof Uint8Array || body instanceof ArrayBuffer;
}

// Surge may expose binary bodies as Uint8Array (binary-body-mode) or, on some
// builds, as a byte-string where each character is one raw byte (0..255).
// Never UTF-8-encode those byte-strings: that inflates protobufs and destroys
// UTF-8 ad markers such as "赞助商广告".
function bodyBytes(body) {
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (typeof body === "string") {
    const out = new Uint8Array(body.length);
    for (let i = 0; i < body.length; i += 1) out[i] = body.charCodeAt(i) & 0xff;
    return out;
  }
  return new Uint8Array(0);
}

function bodyText(body) {
  if (typeof body === "string") {
    // Only treat as real text when it already looks like JSON text.
    const trimmed = body.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) return body;
    // Byte-string binary payload: decode as UTF-8 bytes, not JS string semantics.
    return new TextDecoder().decode(bodyBytes(body));
  }
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function responseBodyRaw() {
  if ($response.bodyBytes !== undefined && $response.bodyBytes !== null) return $response.bodyBytes;
  if ($response.body !== undefined && $response.body !== null) return $response.body;
  return new Uint8Array(0);
}

function looksLikeJsonText(body) {
  if (typeof body === "string") {
    const trimmed = body.trim();
    return trimmed.startsWith("{") || trimmed.startsWith("[");
  }
  if (!isTypedBinary(body) && typeof body !== "string") return false;
  // For binary views, only sniff a small ASCII prefix.
  const bytes = bodyBytes(body);
  let i = 0;
  while (i < bytes.length && (bytes[i] === 0x20 || bytes[i] === 0x0a || bytes[i] === 0x0d || bytes[i] === 0x09)) i += 1;
  return bytes[i] === 0x7b /* { */ || bytes[i] === 0x5b /* [ */;
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
  next: 3,
};

const SETTING_FIELDS = {
  settingItems: 6,
  collectionItems: 7,
};

const SETTING_ITEM_FIELDS = {
  backgroundPlayBackSettingRenderer: 88478200,
  settingCategoryCollectionRenderer: 66930374,
};

const BACKGROUND_PLAYBACK_SETTING_FIELDS = {
  backgroundPlayback: 2,
  download: 3,
  downloadQualitySelection: 9,
  smartDownload: 10,
  icon: 14,
};

const ICON_FIELDS = {
  iconType: 1,
};

const SETTING_CATEGORY_COLLECTION_FIELDS = {
  subSettings: 3,
  categoryId: 4,
};

const SUB_SETTING_FIELDS = {
  settingBooleanRenderer: 61331416,
};

const SETTING_BOOLEAN_RENDERER_FIELDS = {
  enableServiceEndpoint: 5,
  disableServiceEndpoint: 6,
};

const SERVICE_ENDPOINT_FIELDS = {
  setClientSettingEndpoint: 81212182,
};

const SET_CLIENT_SETTING_ENDPOINT_FIELDS = {
  settingData: 1,
};

const SETTING_DATA_FIELDS = {
  clientSettingEnum: 1,
  boolValue: 3,
};

const CLIENT_SETTING_ENUM_FIELDS = {
  item: 1,
};

const BACKGROUND_PLAYBACK_CATEGORY_ID = 10135;
const BACKGROUND_PLAYBACK_SETTING_ITEM = 151;
const BACKGROUND_PLAYBACK_ICON_TYPE = 1093;

const AD_MARKERS = [
  "pagead",
  "googleads",
  "googleadservices",
  "googleadservices.com",
  "doubleclick.net",
  "doubleclick",
  "ytcs",
  "activeview",
  "aclk",
  "adclick",
  "ad_click",
  "clickserve",
  "adformat",
  "adcontext",
  "adhost",
  "adpromoted",
  "is_ad",
  "ad_cpn",
  "adurl",
  "adview",
  "ad_type",
  "google_ad",
  "googlevideo_ad",
  "break_type",
  "adPlacement",
  "adSlots",
  "WATCH_NEXT_ADS_STATE",
  "ad_badge.eml-fe",
  "ad_avatar.eml-fe",
  "ad_button.eml-fe",
  "ad_details_line.eml-fe",
  "ad_icon_text.eml-fe",
  "ad_rating.eml-fe",
  "inline_injection_entrypoint_layout.eml",
];

const FEED_AD_CARD_MARKERS = [
  "赞助",
  "赞助商",
  "赞助商广告",
  "广告主",
  "付费宣传",
  "Sponsored",
  "sponsored",
  "Sponsor",
  "sponsor",
  "Promoted",
  "promoted",
  "Advertisement",
  "advertisement",
  "ad_badge.eml-fe",
  "inline_injection_entrypoint_layout.eml",
  "in_feed_ad",
  "googleads",
  "googleadservices",
  "googleadservices.com",
  "doubleclick.net",
  "doubleclick",
  "pagead",
  "aclk",
  "adclick",
  "ad_click",
  "clickserve",
  "adurl",
  "adview",
  "ad_cpn",
  "ad_type",
];

const FEED_AD_STRONG_CARD_MARKERS = [
  "赞助",
  "赞助商",
  "赞助商广告",
  "广告主",
  "付费宣传",
  "付费推广",
  "推广内容",
  "包含付费推广",
  "Sponsored",
  "sponsored",
  "Sponsor",
  "sponsor",
  "Promoted",
  "promoted",
  "Advertisement",
  "advertisement",
  "Paid promotion",
  "paid promotion",
  "Includes paid promotion",
  "ad_badge.eml-fe",
  "ad_avatar.eml-fe",
  "ad_button.eml-fe",
  "ad_details_line.eml-fe",
  "ad_icon_text.eml-fe",
  "ad_rating.eml-fe",
  "inline_injection_entrypoint_layout.eml",
  "in_feed_ad",
  "promotedSparklesWebRenderer",
  "promotedVideoRenderer",
  "displayAdRenderer",
  "adSlotRenderer",
  "inFeedAdLayoutRenderer",
  "brandedContent",
  "VISIT_SITE",
  "visit_website",
  "Visit site",
  "Visit website",
  "访问网站",
];

const NEXT_AD_STRONG_MARKERS = [
  "pagead",
  "googleads",
  "googleadservices",
  "googleadservices.com",
  "doubleclick.net",
  "doubleclick",
  "activeview",
  "adclick",
  "ad_click",
  "clickserve",
  "adformat",
  "adcontext",
  "adhost",
  "adpromoted",
  "is_ad",
  "ad_cpn",
  "adurl",
  "adview",
  "ad_type",
  "google_ad",
  "googlevideo_ad",
  "break_type",
  "adPlacement",
  "adSlots",
  "WATCH_NEXT_ADS_STATE",
  "ad_badge.eml-fe",
  "ad_avatar.eml-fe",
  "ad_button.eml-fe",
  "ad_details_line.eml-fe",
  "ad_icon_text.eml-fe",
  "ad_rating.eml-fe",
  "inline_injection_entrypoint_layout.eml",
  "playerAd",
  "player_ads",
  "adBreakService",
  "adBreakHeartbeatParams",
  "instream",
  "instream_content",
];

let feedAdCardsRemoved = 0;
let nextAdFieldsRemoved = 0;

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

function readFieldVarintValue(field) {
  if (field.wireType !== WIRE_VARINT) return null;
  const tag = readVarint(field.raw, 0);
  return readVarint(field.raw, tag.offset).value;
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
  if (!config.enhancePlayer) return payload;
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
  let removed = 0;
  const out = [];

  for (const field of parseFields(bytes)) {
    // Known player ad containers observed on iOS.
    if (
      field.fieldNo === PLAYER_FIELDS.adPlacements ||
      field.fieldNo === PLAYER_FIELDS.adSlots
    ) {
      removed += 1;
      changed = true;
      continue;
    }

    // Drop any length field that is compact/medium and clearly ad-marked.
    if (
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      field.payload.length >= 80 &&
      field.payload.length <= 250000 &&
      bytesContainAnyMarker(field.payload, NEXT_AD_STRONG_MARKERS)
    ) {
      // Keep very large structural blobs unless they are obviously ad-only.
      if (field.payload.length <= 120000 || isLikelyNextAdFragment(field.payload)) {
        removed += 1;
        changed = true;
        continue;
      }
    }

    if (field.fieldNo === PLAYER_FIELDS.playabilityStatus && field.wireType === WIRE_LENGTH && field.payload) {
      sawPlayability = true;
      const payload = enhancePlayabilityStatus(field.payload);
      out.push({ raw: encodeLengthField(PLAYER_FIELDS.playabilityStatus, payload) });
      changed = changed || payload !== field.payload;
      continue;
    }

    if (field.fieldNo === PLAYER_FIELDS.playbackTracking && field.wireType === WIRE_LENGTH && field.payload) {
      const payload = cleanPlaybackTracking(field.payload);
      out.push({ raw: encodeLengthField(PLAYER_FIELDS.playbackTracking, payload) });
      changed = true;
      continue;
    }

    // Recurse one level into unknown length fields to strip nested ad slots.
    if (field.wireType === WIRE_LENGTH && field.payload && field.payload.length > 0 && field.payload.length < 800000) {
      try {
        const nested = cleanNextAdFragmentsProtobuf(field.payload, 4);
        if (nested !== field.payload) {
          out.push({ raw: encodeLengthField(field.fieldNo, nested) });
          changed = true;
          continue;
        }
      } catch {
        // ignore and keep original
      }
    }

    out.push(field);
  }

  if (!sawPlayability && config.enhancePlayer) {
    out.push({ raw: encodeLengthField(PLAYER_FIELDS.playabilityStatus, makePlayabilityStatus()) });
    changed = true;
  }

  if (removed) nextAdFieldsRemoved += removed;
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
    if (field.fieldNo === WATCH_CONTENT_FIELDS.next && field.wireType === WIRE_LENGTH && field.payload) {
      // The watch page recommendation feed uses the same richItemContents
      // structure as browse/next. Remove the complete sponsored item before
      // stripping any remaining non-card ad metadata.
      const structured = cleanFeedSurfaceProtobuf(field.payload, "watch-next");
      const payload = cleanNextAdFragmentsProtobuf(structured, 10);
      out.push({ raw: encodeLengthField(WATCH_CONTENT_FIELDS.next, payload) });
      changed = true;
      continue;
    }
    // Some iOS get_watch blobs nest ads outside classic player/next fields.
    if (field.wireType === WIRE_LENGTH && field.payload && field.payload.length >= 120 && field.payload.length <= 300000) {
      if (isLikelyNextAdFragment(field.payload) || bytesContainAnyMarker(field.payload, NEXT_AD_STRONG_MARKERS)) {
        nextAdFieldsRemoved += 1;
        changed = true;
        continue;
      }
      try {
        const nested = cleanNextAdFragmentsProtobuf(field.payload, 5);
        if (nested !== field.payload) {
          out.push({ raw: encodeLengthField(field.fieldNo, nested) });
          changed = true;
          continue;
        }
      } catch {
        // keep
      }
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

function makeIcon(iconType) {
  return encodeVarintField(ICON_FIELDS.iconType, iconType);
}

function makeBackgroundPlaybackSettingRenderer() {
  return concatBytes([
    encodeVarintField(BACKGROUND_PLAYBACK_SETTING_FIELDS.backgroundPlayback, 1),
    encodeVarintField(BACKGROUND_PLAYBACK_SETTING_FIELDS.download, 1),
    encodeVarintField(BACKGROUND_PLAYBACK_SETTING_FIELDS.downloadQualitySelection, 1),
    encodeVarintField(BACKGROUND_PLAYBACK_SETTING_FIELDS.smartDownload, 1),
    encodeLengthField(BACKGROUND_PLAYBACK_SETTING_FIELDS.icon, makeIcon(BACKGROUND_PLAYBACK_ICON_TYPE)),
  ]);
}

function makeBackgroundPlaybackSettingItem() {
  return encodeLengthField(
    SETTING_ITEM_FIELDS.backgroundPlayBackSettingRenderer,
    makeBackgroundPlaybackSettingRenderer(),
  );
}

function makeClientSettingEnum(item) {
  return encodeVarintField(CLIENT_SETTING_ENUM_FIELDS.item, item);
}

function makeSettingData(item, enabled) {
  const parts = [encodeLengthField(SETTING_DATA_FIELDS.clientSettingEnum, makeClientSettingEnum(item))];
  if (enabled) parts.push(encodeVarintField(SETTING_DATA_FIELDS.boolValue, 1));
  return concatBytes(parts);
}

function makeSetClientSettingEndpoint(item, enabled) {
  return encodeLengthField(SET_CLIENT_SETTING_ENDPOINT_FIELDS.settingData, makeSettingData(item, enabled));
}

function makeServiceEndpoint(item, enabled) {
  return encodeLengthField(
    SERVICE_ENDPOINT_FIELDS.setClientSettingEndpoint,
    makeSetClientSettingEndpoint(item, enabled),
  );
}

function makeSettingBooleanRenderer(item) {
  return concatBytes([
    encodeLengthField(SETTING_BOOLEAN_RENDERER_FIELDS.enableServiceEndpoint, makeServiceEndpoint(item, true)),
    encodeLengthField(SETTING_BOOLEAN_RENDERER_FIELDS.disableServiceEndpoint, makeServiceEndpoint(item, false)),
  ]);
}

function makeBackgroundPlaybackSubSetting() {
  return encodeLengthField(
    SUB_SETTING_FIELDS.settingBooleanRenderer,
    makeSettingBooleanRenderer(BACKGROUND_PLAYBACK_SETTING_ITEM),
  );
}

function settingDataHasClientSettingItem(payload, item) {
  for (const field of parseFields(payload)) {
    if (
      field.fieldNo === SETTING_DATA_FIELDS.clientSettingEnum &&
      field.wireType === WIRE_LENGTH &&
      field.payload
    ) {
      for (const enumField of parseFields(field.payload)) {
        if (
          enumField.fieldNo === CLIENT_SETTING_ENUM_FIELDS.item &&
          readFieldVarintValue(enumField) === item
        ) {
          return true;
        }
      }
    }
  }
  return false;
}

function setClientSettingEndpointHasItem(payload, item) {
  for (const field of parseFields(payload)) {
    if (
      field.fieldNo === SET_CLIENT_SETTING_ENDPOINT_FIELDS.settingData &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      settingDataHasClientSettingItem(field.payload, item)
    ) {
      return true;
    }
  }
  return false;
}

function serviceEndpointHasItem(payload, item) {
  for (const field of parseFields(payload)) {
    if (
      field.fieldNo === SERVICE_ENDPOINT_FIELDS.setClientSettingEndpoint &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      setClientSettingEndpointHasItem(field.payload, item)
    ) {
      return true;
    }
  }
  return false;
}

function settingBooleanRendererHasItem(payload, item) {
  for (const field of parseFields(payload)) {
    if (
      (field.fieldNo === SETTING_BOOLEAN_RENDERER_FIELDS.enableServiceEndpoint ||
        field.fieldNo === SETTING_BOOLEAN_RENDERER_FIELDS.disableServiceEndpoint) &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      serviceEndpointHasItem(field.payload, item)
    ) {
      return true;
    }
  }
  return false;
}

function subSettingHasItem(payload, item) {
  for (const field of parseFields(payload)) {
    if (
      field.fieldNo === SUB_SETTING_FIELDS.settingBooleanRenderer &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      settingBooleanRendererHasItem(field.payload, item)
    ) {
      return true;
    }
  }
  return false;
}

function settingCategoryHasItem(fields, item) {
  return fields.some(
    (field) =>
      field.fieldNo === SETTING_CATEGORY_COLLECTION_FIELDS.subSettings &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      subSettingHasItem(field.payload, item),
  );
}

function enhanceSettingCategoryCollection(payload) {
  const fields = parseFields(payload);
  const categoryId = fields
    .filter((field) => field.fieldNo === SETTING_CATEGORY_COLLECTION_FIELDS.categoryId)
    .map(readFieldVarintValue)
    .find((value) => value !== null);

  if (categoryId !== BACKGROUND_PLAYBACK_CATEGORY_ID) return payload;
  if (settingCategoryHasItem(fields, BACKGROUND_PLAYBACK_SETTING_ITEM)) return payload;

  const out = fields.slice();
  out.push({
    raw: encodeLengthField(SETTING_CATEGORY_COLLECTION_FIELDS.subSettings, makeBackgroundPlaybackSubSetting()),
  });
  return rebuildFields(out);
}

function settingItemHasBackgroundPlaybackRenderer(payload) {
  return parseFields(payload).some(
    (field) =>
      field.fieldNo === SETTING_ITEM_FIELDS.backgroundPlayBackSettingRenderer &&
      field.wireType === WIRE_LENGTH,
  );
}

function enhanceSettingItem(payload) {
  let changed = false;
  const out = [];

  for (const field of parseFields(payload)) {
    if (
      field.fieldNo === SETTING_ITEM_FIELDS.settingCategoryCollectionRenderer &&
      field.wireType === WIRE_LENGTH &&
      field.payload
    ) {
      const categoryPayload = enhanceSettingCategoryCollection(field.payload);
      if (categoryPayload !== field.payload) {
        out.push({ raw: encodeLengthField(field.fieldNo, categoryPayload) });
        changed = true;
        continue;
      }
    }
    out.push(field);
  }

  return changed ? rebuildFields(out) : payload;
}

function cleanSettingProtobuf(bytes) {
  let changed = false;
  let sawBackgroundPlaybackRenderer = false;
  const out = [];

  for (const field of parseFields(bytes)) {
    if (
      (field.fieldNo === SETTING_FIELDS.settingItems || field.fieldNo === SETTING_FIELDS.collectionItems) &&
      field.wireType === WIRE_LENGTH &&
      field.payload
    ) {
      sawBackgroundPlaybackRenderer =
        sawBackgroundPlaybackRenderer || settingItemHasBackgroundPlaybackRenderer(field.payload);
      const payload = enhanceSettingItem(field.payload);
      if (payload !== field.payload) {
        out.push({ raw: encodeLengthField(field.fieldNo, payload) });
        changed = true;
        continue;
      }
    }
    out.push(field);
  }

  if (!sawBackgroundPlaybackRenderer) {
    out.push({ raw: encodeLengthField(SETTING_FIELDS.settingItems, makeBackgroundPlaybackSettingItem()) });
    changed = true;
  }

  return changed ? rebuildFields(out) : bytes;
}

function bytesContainAdMarker(bytes) {
  const text = new TextDecoder().decode(bytes);
  return AD_MARKERS.some((marker) => text.includes(marker));
}

function bytesContainMarker(bytes, marker) {
  return new TextDecoder().decode(bytes).includes(marker);
}

function bytesContainAnyMarker(bytes, markers) {
  const text = new TextDecoder().decode(bytes);
  return markers.some((marker) => text.includes(marker));
}

function isLikelyNextAdFragment(payload) {
  if (payload.length < 180 || payload.length > 220000) return false;
  if (!bytesContainAnyMarker(payload, NEXT_AD_STRONG_MARKERS)) return false;

  try {
    const fields = parseFields(payload);
    const lengthFields = fields.filter((field) => field.wireType === WIRE_LENGTH).length;
    if (lengthFields === 0) return payload.length < 6000;
    if (payload.length > 90000 && lengthFields > 35) return false;
    return true;
  } catch {
    return payload.length < 6000;
  }
}

function cleanNextAdFragmentsProtobuf(bytes, depth) {
  if (depth <= 0) return bytes;

  let changed = false;
  const out = [];
  for (const field of parseFields(bytes)) {
    if (field.wireType !== WIRE_LENGTH || !field.payload || field.payload.length === 0) {
      out.push(field);
      continue;
    }

    try {
      const payload = cleanNextAdFragmentsProtobuf(field.payload, depth - 1);
      if (isLikelyNextAdFragment(payload)) {
        nextAdFieldsRemoved += 1;
        changed = true;
        continue;
      }
      if (payload !== field.payload) {
        out.push({ raw: encodeLengthField(field.fieldNo, payload) });
        changed = true;
      } else {
        out.push(field);
      }
    } catch {
      if (isLikelyNextAdFragment(field.payload)) {
        nextAdFieldsRemoved += 1;
        changed = true;
      } else {
        out.push(field);
      }
    }
  }

  return changed ? rebuildFields(out) : bytes;
}

function isLikelyNestedMessage(bytes) {
  try {
    const fields = parseFields(bytes);
    return fields.length >= 2 && fields.some((field) => field.wireType === WIRE_LENGTH);
  } catch {
    return false;
  }
}

function markerHits(bytes) {
  const checks = {
    badge_cn: ["赞助商广告"],
    sponsor_cn: ["赞助商"],
    paid_cn: ["付费宣传", "付费推广"],
    visit_cn: ["访问网站"],
    watch_cn: ["观看"],
    learn_cn: ["了解详情", "立即购买"],
    sponsored_en: ["Sponsored", "sponsored"],
    visit_en: ["Visit site", "Visit website", "VISIT_SITE"],
    ad_ui: [
      "ad_badge.eml-fe",
      "ad_button.eml-fe",
      "inline_injection_entrypoint_layout.eml",
      "in_feed_ad",
      "promotedVideoRenderer",
      "displayAdRenderer",
      "adSlotRenderer",
    ],
    brand_sample: ["Aikido", "aikido"],
  };
  const hits = [];
  for (const [name, markers] of Object.entries(checks)) {
    if (bytesContainAnyMarker(bytes, markers)) hits.push(name);
  }
  return hits;
}

function isExactSponsorBadgeCard(payload) {
  // Live logs proved badge_cn / sponsor_cn / brand_sample exist in browse.
  // Require card-like size so we remove whole homepage cards, not tiny labels.
  if (!payload || payload.length < 6000 || payload.length > 350000) return false;
  const hasBadge = bytesContainAnyMarker(payload, ["赞助商广告"]);
  const hasSponsor = bytesContainAnyMarker(payload, ["赞助商", "付费宣传", "付费推广"]);
  const hasBrand = bytesContainAnyMarker(payload, ["Aikido", "aikido"]);
  if (!hasBadge && !(hasSponsor && hasBrand) && !(hasBadge || (hasSponsor && hasBrand))) {
    // keep clear condition below
  }
  if (!hasBadge && !(hasSponsor && hasBrand)) return false;
  try {
    const fields = parseFields(payload);
    const lengthFields = fields.filter((field) => field.wireType === WIRE_LENGTH).length;
    if (lengthFields === 0) return false;
    // Allow larger cards; only skip extremely wide shelves.
    if (payload.length > 300000 && lengthFields > 40) return false;
    return true;
  } catch {
    return payload.length <= 200000;
  }
}

function isScreenshotStyleCtaAdCard(payload) {
  // Prefer whole homepage cards, not tiny label fragments.
  if (!payload || payload.length < 6000 || payload.length > 220000) return false;

  const hasWatch = bytesContainAnyMarker(payload, ["观看", "Watch"]);
  const hasLearn = bytesContainAnyMarker(payload, [
    "了解详情",
    "立即购买",
    "Learn more",
    "Shop now",
    "Install",
    "安装",
    "访问网站",
    "Visit site",
    "Visit website",
    "VISIT_SITE",
  ]);
  const hasAdUi = bytesContainAnyMarker(payload, [
    "ad_badge.eml-fe",
    "ad_button.eml-fe",
    "ad_details_line.eml-fe",
    "ad_icon_text.eml-fe",
    "inline_injection_entrypoint_layout.eml",
    "in_feed_ad",
    "promotedVideoRenderer",
    "promotedSparklesWebRenderer",
    "displayAdRenderer",
    "adSlotRenderer",
    "inFeedAdLayoutRenderer",
  ]);
  const hasSponsorText = bytesContainAnyMarker(payload, [
    "赞助商广告",
    "赞助商",
    "付费宣传",
    "付费推广",
    "Sponsored",
    "sponsored",
  ]);
  const hasBrand = bytesContainAnyMarker(payload, ["Aikido", "aikido"]);

  const strong =
    hasSponsorText ||
    hasBrand ||
    (hasAdUi && hasLearn) ||
    (hasAdUi && hasWatch && hasLearn);
  if (!strong) return false;

  try {
    const fields = parseFields(payload);
    const lengthFields = fields.filter((field) => field.wireType === WIRE_LENGTH).length;
    if (lengthFields < 2) return false;
    if (payload.length > 200000 && lengthFields > 40) return false;
    return true;
  } catch {
    return payload.length <= 160000;
  }
}

function scoreSponsorNode(payload) {
  if (!payload) return -1;
  // Ignore tiny label fragments and giant shelves; we want whole feed cards.
  if (payload.length < 6000 || payload.length > 220000) return -1;

  let score = 0;
  if (bytesContainAnyMarker(payload, ["赞助商广告"])) score += 10;
  if (bytesContainAnyMarker(payload, ["赞助商"])) score += 5;
  if (bytesContainAnyMarker(payload, ["付费宣传", "付费推广"])) score += 5;
  if (bytesContainAnyMarker(payload, ["Aikido", "aikido"])) score += 6;
  if (
    bytesContainAnyMarker(payload, [
      "ad_badge.eml-fe",
      "ad_button.eml-fe",
      "ad_details_line.eml-fe",
      "inline_injection_entrypoint_layout.eml",
      "in_feed_ad",
      "promotedVideoRenderer",
      "promotedSparklesWebRenderer",
      "displayAdRenderer",
      "adSlotRenderer",
      "inFeedAdLayoutRenderer",
    ])
  ) {
    score += 6;
  }
  if (
    bytesContainAnyMarker(payload, [
      "访问网站",
      "了解详情",
      "立即购买",
      "Learn more",
      "Shop now",
      "Visit site",
      "Visit website",
      "Install",
      "安装",
    ])
  ) {
    score += 4;
  }
  if (bytesContainAnyMarker(payload, ["观看", "Watch"])) score += 1;

  // Sweet spot for a single homepage card.
  if (payload.length >= 10000 && payload.length <= 120000) score += 4;
  else if (payload.length <= 180000) score += 2;

  // Need a clear commercial signal, not just "观看".
  if (score < 8) return -1;
  return score;
}

function isLikelyFeedAdCard(payload) {
  return isExactSponsorBadgeCard(payload) || isScreenshotStyleCtaAdCard(payload);
}

function cleanFeedAdCardsProtobuf(bytes, depth) {
  if (depth <= 0) return bytes;

  let changed = false;
  const out = [];

  for (const field of parseFields(bytes)) {
    if (field.wireType !== WIRE_LENGTH || !field.payload || field.payload.length === 0) {
      out.push(field);
      continue;
    }

    try {
      // Recurse first.
      const nested = cleanFeedAdCardsProtobuf(field.payload, depth - 1);
      if (nested !== field.payload) {
        // If nested deletion emptied/hollowed a card-sized ad container, drop parent.
        if (
          field.payload.length >= 8000 &&
          field.payload.length <= 220000 &&
          (isLikelyFeedAdCard(field.payload) || scoreSponsorNode(field.payload) >= 8)
        ) {
          feedAdCardsRemoved += 1;
          changed = true;
          continue;
        }
        out.push({ raw: encodeLengthField(field.fieldNo, nested) });
        changed = true;
        continue;
      }

      // Delete whole card-level sponsor nodes.
      if (isLikelyFeedAdCard(field.payload) && field.payload.length >= 6000) {
        feedAdCardsRemoved += 1;
        changed = true;
        continue;
      }

      out.push(field);
    } catch {
      out.push(field);
    }
  }

  return changed ? rebuildFields(out) : bytes;
}

function payloadHasExactSponsorBadge(payload) {
  return !!(payload && bytesContainAnyMarker(payload, ["赞助商广告"]));
}

// Current YouTube iOS browse protobufs place homepage cards in:
//   Content -> SectionListRenderer -> ItemSectionRenderer(50195462)
//   -> repeated RichItemContent(field 1)
// Removing the repeated field itself is important. Deleting an arbitrary
// ad-marked descendant only hollows the card and leaves a grey placeholder.
const ITEM_SECTION_RENDERER_FIELD = 50195462;
const RICH_ITEM_CONTENT_FIELD = 1;

function isDirectFeedAdItem(payload) {
  if (!payload || payload.length < 64) return false;

  // Structural UI identifiers and ad-network payloads are stronger than
  // translated CTA text and are stable across the live Chinese responses.
  if (
    bytesContainAnyMarker(payload, [
      "inline_injection_entrypoint_layout.eml",
      "ad_badge.eml-fe",
      "ad_avatar.eml-fe",
      "ad_button.eml-fe",
      "ad_details_line.eml-fe",
      "ad_icon_text.eml-fe",
      "ad_rating.eml-fe",
      "in_feed_ad",
      "promotedSparklesWebRenderer",
      "promotedVideoRenderer",
      "displayAdRenderer",
      "adSlotRenderer",
      "inFeedAdLayoutRenderer",
    ])
  ) {
    return true;
  }

  // Community implementations use pagead inside a sizeable unknown field as
  // the fallback when YouTube has not exposed a known renderer/EML name.
  if (
    payload.length >= 1000 &&
    bytesContainAnyMarker(payload, [
      "pagead",
      "googleads",
      "googleadservices",
      "doubleclick.net",
      "adclick",
      "adview",
    ])
  ) {
    return true;
  }

  // Text fallback for layouts whose technical EML marker has moved into an
  // unknown protobuf field. Keep it limited to explicit sponsorship labels.
  return bytesContainAnyMarker(payload, [
    "赞助商广告",
    "赞助商",
    "付费宣传",
    "付费推广",
    "Sponsored",
    "sponsored",
    "Advertisement",
    "advertisement",
  ]);
}

function cleanItemSectionRenderer(payload, counters) {
  let fields;
  try {
    fields = parseFields(payload);
  } catch {
    return payload;
  }

  counters.sections += 1;
  let changed = false;
  const out = [];
  for (const field of fields) {
    if (
      field.fieldNo === RICH_ITEM_CONTENT_FIELD &&
      field.wireType === WIRE_LENGTH &&
      field.payload
    ) {
      counters.items += 1;
      if (isDirectFeedAdItem(field.payload)) {
        counters.removed += 1;
        changed = true;
        continue;
      }
    }
    out.push(field);
  }

  return changed ? rebuildFields(out) : payload;
}

function cleanKnownFeedItemSections(bytes, depth, counters) {
  if (depth <= 0) return bytes;

  let fields;
  try {
    fields = parseFields(bytes);
  } catch {
    return bytes;
  }

  let changed = false;
  const out = [];
  for (const field of fields) {
    if (field.wireType !== WIRE_LENGTH || !field.payload || field.payload.length === 0) {
      out.push(field);
      continue;
    }

    let payload;
    if (field.fieldNo === ITEM_SECTION_RENDERER_FIELD) {
      payload = cleanItemSectionRenderer(field.payload, counters);
    } else {
      payload = cleanKnownFeedItemSections(field.payload, depth - 1, counters);
    }

    if (payload !== field.payload) {
      out.push({ raw: encodeLengthField(field.fieldNo, payload) });
      changed = true;
    } else {
      out.push(field);
    }
  }

  return changed ? rebuildFields(out) : bytes;
}

function cleanFeedSurfaceProtobuf(bytes, surface = "browse") {
  feedAdCardsRemoved = 0;
  const hits = markerHits(bytes);
  const counters = { sections: 0, items: 0, removed: 0 };
  const output = cleanKnownFeedItemSections(bytes, 18, counters);
  feedAdCardsRemoved = counters.removed;

  if (counters.removed === 0) {
    logbook(
      `${surface}-schema hits=${hits.join("|") || "none"} sections=${counters.sections} items=${counters.items} removed=0 bytes=${bytes.length}`
    );
    return bytes;
  }

  const ratio = output.length / Math.max(bytes.length, 1);
  const remainingItems = counters.items - counters.removed;
  // Judge safety by the repeated-item structure, not byte ratio. A single
  // promoted card can contain most of the response bytes while still being
  // only 1 of many homepage items. Preserve the response only if cleanup
  // would empty the item arrays or remove an implausibly large share of them.
  const tooManyItemsRemoved =
    remainingItems <= 0 ||
    counters.removed > Math.max(4, Math.floor(counters.items / 2));
  if (tooManyItemsRemoved) {
    logbook(
      `${surface}-schema-safety hits=${hits.join("|") || "none"} sections=${counters.sections} items=${counters.items} removed=${counters.removed} remaining=${remainingItems} ratio=${ratio.toFixed(3)}`
    );
    feedAdCardsRemoved = 0;
    return bytes;
  }

  logbook(
    `${surface}-schema hits=${hits.join("|") || "none"} sections=${counters.sections} items=${counters.items} removed=${counters.removed} remaining=${remainingItems} ratio=${ratio.toFixed(3)} ${bytes.length} -> ${output.length}`
  );
  return output;
}

function forceRemoveBestSponsorNode(bytes, depth) {
  // Find the best sponsor-like node, then remove the nearest suitable parent
  // item/card so the homepage does not leave a blank shell.
  let best = null;

  function walk(nodeBytes, d, trail) {
    if (d <= 0 || !nodeBytes || nodeBytes.length === 0) return;
    let fields;
    try {
      fields = parseFields(nodeBytes);
    } catch {
      return;
    }
    for (const field of fields) {
      if (field.wireType !== WIRE_LENGTH || !field.payload) continue;
      const path = trail.concat([
        {
          size: nodeBytes.length,
          fieldNo: field.fieldNo,
          payloadSize: field.payload.length,
          head: field.payload[0],
          mid: field.payload[Math.floor(field.payload.length / 2)],
          tail: field.payload[field.payload.length - 1],
          score: scoreSponsorNode(field.payload),
          isLikely: isLikelyFeedAdCard(field.payload),
        },
      ]);
      const score = scoreSponsorNode(field.payload);
      if (score >= 8) {
        // Choose a parent item size that looks like a whole feed card.
        let target = path[path.length - 1];
        for (let i = path.length - 1; i >= 0; i -= 1) {
          const cand = path[i];
          // Prefer larger card-sized ancestors so blank shells are less likely.
          if (cand.payloadSize >= 12000 && cand.payloadSize <= 260000) {
            target = cand;
            if (cand.score >= 8 || cand.isLikely) break;
          } else if (cand.payloadSize >= 8000 && cand.payloadSize <= 220000 && target === path[path.length - 1]) {
            target = cand;
          }
        }
        const candidate = {
          score,
          size: target.payloadSize,
          head: target.head,
          mid: target.mid,
          tail: target.tail,
          leafSize: field.payload.length,
        };
        if (
          !best ||
          candidate.score > best.score ||
          (candidate.score === best.score && candidate.size < best.size)
        ) {
          best = candidate;
        }
      }
      walk(field.payload, d - 1, path);
    }
  }

  walk(bytes, depth, []);
  if (!best) return { removed: 0, bytes };

  function sameNode(payload) {
    return (
      payload &&
      payload.length === best.size &&
      payload[0] === best.head &&
      payload[Math.floor(payload.length / 2)] === best.mid &&
      payload[payload.length - 1] === best.tail
    );
  }

  function removeOnce(nodeBytes, d) {
    if (d <= 0) return { changed: false, bytes: nodeBytes, removed: 0 };
    let fields;
    try {
      fields = parseFields(nodeBytes);
    } catch {
      return { changed: false, bytes: nodeBytes, removed: 0 };
    }
    const out = [];
    let changed = false;
    let removed = 0;
    for (const field of fields) {
      if (changed) {
        out.push(field);
        continue;
      }
      if (field.wireType !== WIRE_LENGTH || !field.payload) {
        out.push(field);
        continue;
      }
      if (sameNode(field.payload)) {
        changed = true;
        removed = 1;
        continue;
      }
      const child = removeOnce(field.payload, d - 1);
      if (child.changed) {
        out.push({ raw: encodeLengthField(field.fieldNo, child.bytes) });
        changed = true;
        removed = child.removed;
      } else {
        out.push(field);
      }
    }
    return {
      changed,
      removed,
      bytes: changed ? rebuildFields(out) : nodeBytes,
    };
  }

  const result = removeOnce(bytes, depth);
  return { removed: result.removed || 0, bytes: result.bytes };
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
  feedAdCardsRemoved = 0;
  nextAdFieldsRemoved = 0;
  if (endpoint === "player") return cleanPlayerProtobuf(bytes);
  if (endpoint === "next") {
    const structured = cleanFeedSurfaceProtobuf(bytes, "next");
    return cleanNextAdFragmentsProtobuf(structured, 8);
  }
  if (endpoint === "get_watch") return cleanWatchProtobuf(bytes);
  if (endpoint === "account/get_setting" || endpoint === "account/get_setting_values") {
    return cleanSettingProtobuf(bytes);
  }
  // Home/search feeds: only remove guarded ad cards. Keep guide/reel passthrough
  // because those surfaces previously regressed metadata when rewritten broadly.
  if (endpoint === "browse" || endpoint === "search") {
    return cleanFeedSurfaceProtobuf(bytes, endpoint);
  }
  if (endpoint === "guide" || endpoint === "reel/reel_watch_sequence") {
    return bytes;
  }
  return bytes;
}

const endpoint = endpointFromUrl($request.url);
const originalBody = responseBodyRaw();

function describeBodyType(body) {
  if (body instanceof Uint8Array) return "uint8";
  if (body instanceof ArrayBuffer) return "arraybuffer";
  if (typeof body === "string") return "string";
  if (body == null) return "null";
  return typeof body;
}

// Return body in the same shape Surge handed us. Some iOS builds corrupt
// protobufs when a Uint8Array is substituted for an original byte-string (or
// vice versa), which shows up as multi-megabyte Content-Length inflation.
function toResponseBody(bytes, original) {
  if (original instanceof Uint8Array || original instanceof ArrayBuffer) {
    return bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  }
  if (typeof original === "string") {
    const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const chunk = 0x8000;
    let out = "";
    for (let i = 0; i < arr.length; i += chunk) {
      out += String.fromCharCode.apply(null, arr.subarray(i, Math.min(i + chunk, arr.length)));
    }
    return out;
  }
  return bytes;
}

try {
  const inputType = describeBodyType(originalBody);
  if (looksLikeJsonText(originalBody)) {
    const textBody = typeof originalBody === "string" ? originalBody : bodyText(originalBody);
    const output = cleanJson(textBody, endpoint);
    logbook(`json ${endpoint} type=${inputType} ${textBody.length} -> ${output.length}`);
    $done({ body: output });
  } else {
    const input = bodyBytes(originalBody);
    let output = cleanProtobuf(input, endpoint);
    const removedCount = feedAdCardsRemoved + nextAdFieldsRemoved;

    // Hard safety: never ship an inflated protobuf body.
    if (output.length > input.length + 64) {
      logbook(
        `protobuf-inflation-abort ${endpoint} type=${inputType} ${input.length} -> ${output.length}`
      );
      $done({});
    } else if (output.length > Math.floor(input.length * 1.02) + 32) {
      logbook(
        `protobuf-growth-abort ${endpoint} type=${inputType} ${input.length} -> ${output.length}`
      );
      $done({});
    } else if (removedCount > 0 || output.length !== input.length) {
      // Compare bytes only when lengths match and no explicit removals were counted.
      let changed = removedCount > 0 || output.length !== input.length;
      if (!changed && output !== input) {
        for (let i = 0; i < input.length; i += 1) {
          if (output[i] !== input[i]) {
            changed = true;
            break;
          }
        }
      }
      if (!changed) {
        logbook(`protobuf-passthrough ${endpoint} type=${inputType} bytes=${input.length}`);
        $done({});
      } else {
        const removed = removedCount ? ` removed=${removedCount}` : "";
        logbook(`protobuf ${endpoint} type=${inputType} ${input.length} -> ${output.length}${removed}`);
        $done({ body: toResponseBody(output, originalBody) });
      }
    } else {
      // Length unchanged and no removals: keep original bytes untouched.
      logbook(`protobuf-passthrough ${endpoint} type=${inputType} bytes=${input.length}`);
      $done({});
    }
  }
} catch (error) {
  logbook(`error ${endpoint} ${error && error.message ? error.message : error}`);
  $done({});
}
