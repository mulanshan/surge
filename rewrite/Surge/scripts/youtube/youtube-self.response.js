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
      changed = changed || payload !== field.payload;
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
    if (field.fieldNo === WATCH_CONTENT_FIELDS.next && field.wireType === WIRE_LENGTH && field.payload) {
      const payload = cleanNextAdFragmentsProtobuf(field.payload, 8);
      out.push({ raw: encodeLengthField(WATCH_CONTENT_FIELDS.next, payload) });
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

function isLikelyFeedAdCard(payload) {
  // Conservative homepage-safe matcher.
  // Prefer missing an ad over blanking the entire iOS home feed again.
  if (payload.length < 400 || payload.length > 90000) return false;

  const hasExactSponsorBadge = bytesContainAnyMarker(payload, [
    "赞助商广告",
    "付费宣传",
    "Paid promotion",
    "paid promotion",
  ]);
  // Avoid bare "Sponsored"/"sponsor" alone: those strings appear in non-ad UI.
  const hasEnglishSponsorBadge = bytesContainAnyMarker(payload, [
    "Sponsored",
    "sponsored by",
  ]);
  const hasCta = bytesContainAnyMarker(payload, [
    "访问网站",
    "Visit site",
    "Visit website",
    "VISIT_SITE",
    "Shop now",
    "Learn more",
    "立即购买",
    "了解详情",
    "Install",
    "安装",
  ]);
  const hasAdUi = bytesContainAnyMarker(payload, [
    "ad_badge.eml-fe",
    "ad_button.eml-fe",
    "ad_details_line.eml-fe",
    "inline_injection_entrypoint_layout.eml",
    "in_feed_ad",
    "promotedSparklesWebRenderer",
    "promotedVideoRenderer",
    "displayAdRenderer",
    "adSlotRenderer",
    "inFeedAdLayoutRenderer",
  ]);

  // Require a clear sponsor badge, or ad-UI marker + CTA.
  const strong =
    hasExactSponsorBadge ||
    (hasEnglishSponsorBadge && hasCta) ||
    (hasAdUi && (hasCta || hasExactSponsorBadge || hasEnglishSponsorBadge));
  if (!strong) return false;

  try {
    const fields = parseFields(payload);
    const lengthFields = fields.filter((field) => field.wireType === WIRE_LENGTH).length;
    if (lengthFields === 0) return false;
    // Giant containers can embed one ad; never delete the whole shelf.
    if (payload.length > 60000 && lengthFields > 18) return false;
    if (payload.length > 30000 && lengthFields > 28) return false;
    return true;
  } catch {
    // Only drop compact exact Chinese sponsor cards if parse fails.
    return hasExactSponsorBadge && payload.length <= 40000;
  }
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
      if (isLikelyFeedAdCard(field.payload)) {
        feedAdCardsRemoved += 1;
        changed = true;
        continue;
      }

      const payload = cleanFeedAdCardsProtobuf(field.payload, depth - 1);
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

function cleanFeedSurfaceProtobuf(bytes) {
  feedAdCardsRemoved = 0;
  const output = cleanFeedAdCardsProtobuf(bytes, 7);
  if (feedAdCardsRemoved === 0) {
    return bytes;
  }

  const ratio = output.length / Math.max(bytes.length, 1);
  // Homepage blanking usually comes from over-deletion of structural cards.
  // Keep this very conservative: few cards, small size delta only.
  if (feedAdCardsRemoved > 6) {
    logbook(`feed-safety-passthrough removed=${feedAdCardsRemoved} ${bytes.length} -> ${output.length}`);
    feedAdCardsRemoved = 0;
    return bytes;
  }
  if (bytes.length > 50000 && ratio < 0.93) {
    logbook(`feed-safety-passthrough ratio=${ratio.toFixed(3)} ${bytes.length} -> ${output.length}`);
    feedAdCardsRemoved = 0;
    return bytes;
  }
  if (bytes.length > 20000 && ratio < 0.80) {
    logbook(`feed-safety-passthrough ratio=${ratio.toFixed(3)} ${bytes.length} -> ${output.length}`);
    feedAdCardsRemoved = 0;
    return bytes;
  }
  return output;
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
  if (endpoint === "next") return cleanNextAdFragmentsProtobuf(cleanFeedAdCardsProtobuf(bytes, 7), 8);
  if (endpoint === "get_watch") return cleanWatchProtobuf(bytes);
  if (endpoint === "account/get_setting" || endpoint === "account/get_setting_values") {
    return cleanSettingProtobuf(bytes);
  }
  // Home/search feeds: only remove guarded ad cards. Keep guide/reel passthrough
  // because those surfaces previously regressed metadata when rewritten broadly.
  if (endpoint === "browse" || endpoint === "search") {
    return cleanFeedSurfaceProtobuf(bytes);
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
