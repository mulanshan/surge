/*
 * Self-written YouTube cleaner for Surge.
 *
 * Behavior:
 * - JSON responses (Web/desktop YouTube): conservative ad-field removal,
 *   plus optional player capability enhancement for picture-in-picture,
 *   background playback, and translated caption tracks.
 * - Binary protobuf responses (iOS/Android YouTube App, YouTube Music App):
 *   schema-light wire editing for player/get_watch/account settings,
 *   zero-decode byte-pattern ad filtering for browse/search/next/Shorts feeds,
 *   and optional bottom-bar tab simplification (guide / pivotBarRenderer).
 *   Binary bodies are handled as raw bytes (never UTF-8 re-encoded).
 *
 * Does not include any third-party source code.
 */

const DEFAULTS = {
  blockUpload: false,
  blockImmersive: false,
  blockShorts: false,
  enhancePlayer: true,
  // BCP-47 language code for an auto-translated caption track appended to
  // JSON player responses (web clients); "off" disables the feature. Binary
  // protobuf player responses (iOS app) are not modified for captions.
  captionLang: "off",
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
  if (config.debug === true) logbook(args.join(" "));
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

function utf8Bytes(str) {
  const bytes = [];
  for (let i = 0; i < str.length; i += 1) {
    let cp = str.charCodeAt(i);
    if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < str.length) {
      const low = str.charCodeAt(i + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        cp = ((cp - 0xd800) << 10) + (low - 0xdc00) + 0x10000;
        i += 1;
      }
    }
    if (cp < 0x80) {
      bytes.push(cp);
    } else if (cp < 0x800) {
      bytes.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
    } else if (cp < 0x10000) {
      bytes.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    } else {
      bytes.push(
        0xf0 | (cp >> 18),
        0x80 | ((cp >> 12) & 0x3f),
        0x80 | ((cp >> 6) & 0x3f),
        0x80 | (cp & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
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

const UTF8_DECODER = new TextDecoder();

function bodyText(body) {
  if (typeof body === "string") {
    const trimmed = body.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) return body;
    return UTF8_DECODER.decode(bodyBytes(body));
  }
  if (body instanceof Uint8Array) return UTF8_DECODER.decode(body);
  if (body instanceof ArrayBuffer) return UTF8_DECODER.decode(new Uint8Array(body));
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
  const bytes = bodyBytes(body);
  let i = 0;
  while (i < bytes.length && (bytes[i] === 0x20 || bytes[i] === 0x0a || bytes[i] === 0x0d || bytes[i] === 0x09)) i += 1;
  return bytes[i] === 0x7b /* { */ || bytes[i] === 0x5b /* [ */;
}

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
  "actionCompanionAdRenderer",
  "adVideoRenderer",
  "compactPromotedItemRenderer",
  "compactPromotedVideoRenderer",
  "promotedItemRenderer",
  "promotedSparklesTextSearchRenderer",
  "videoMastheadAdV3Renderer",
  "primetimePromoRenderer",
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
  if (config.blockUpload && value.pivotBarIconOnlyItemRenderer) return true;
  const candidate = value.pivotBarItemRenderer || value.guideEntryRenderer || value;
  const browseId =
    (candidate.browseEndpoint && candidate.browseEndpoint.browseId) ||
    (candidate.navigationEndpoint &&
      candidate.navigationEndpoint.browseEndpoint &&
      candidate.navigationEndpoint.browseEndpoint.browseId) ||
    (candidate.endpoint && candidate.endpoint.browseEndpoint && candidate.endpoint.browseEndpoint.browseId) ||
    candidate.pivotIdentifier ||
    candidate.browseId;
  if (!browseId || typeof browseId !== "string") return false;
  if (config.blockUpload && browseId === "FEuploads") return true;
  if (config.blockImmersive && browseId === "FEmusic_immersive") return true;
  if (config.blockShorts && browseId === "FEshorts") return true;
  return false;
}

function walkJson(value, state) {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (let i = value.length - 1; i >= 0; i -= 1) {
      const item = value[i];
      if (isAdRenderer(item) || isBlockedGuide(item)) {
        value.splice(i, 1);
        state.changed = true;
        continue;
      }
      walkJson(item, state);
    }
    return;
  }
  for (const key of Object.keys(value)) {
    if (AD_KEYS_TO_DELETE.includes(key)) {
      delete value[key];
      state.changed = true;
      continue;
    }
    walkJson(value[key], state);
  }
}

function enhanceJsonPlayer(payload, state) {
  if (!config.enhancePlayer) return;
  payload.playabilityStatus = payload.playabilityStatus || {};
  payload.playabilityStatus.pictureInPictureRender = {
    pictureInPictureAbility: { active: true, f4: 0, f6: 0, f8: 1 },
  };
  payload.playabilityStatus.backgroundPlayerRender = {
    backgroundAbility: { active: true },
  };
  state.changed = true;
  addTranslatedCaptionTrack(payload, state);
}

function addTranslatedCaptionTrack(payload, state) {
  const lang = String(config.captionLang || "off").trim();
  if (lang === "off" || lang === "") return;

  const captions = payload.captions && payload.captions.playerCaptionsTracklistRenderer;
  const tracks = captions && captions.captionTracks;
  if (!Array.isArray(tracks) || tracks.length === 0) return;

  for (const track of tracks) {
    if (track.isTranslatable !== true) {
      track.isTranslatable = true;
      state.changed = true;
    }
  }

  if (tracks.some((track) => track.languageCode === lang)) return;
  const base = tracks.find((track) => track.languageCode === "en") || tracks[0];
  if (!base || !base.baseUrl) return;

  tracks.push({
    ...base,
    baseUrl: `${base.baseUrl}&tlang=${encodeURIComponent(lang)}`,
    languageCode: lang,
    vssId: `.${lang}`,
    name: { simpleText: `翻译 (${lang})` },
  });
  state.changed = true;
}

function cleanJsonResult(text, endpoint) {
  const payload = JSON.parse(text);
  const state = { changed: false };
  if (endpoint === "player" || endpoint === "get_watch") {
    enhanceJsonPlayer(payload, state);
  }
  walkJson(payload, state);
  if (!state.changed) return { changed: false, body: text };
  return { changed: true, body: JSON.stringify(payload) };
}

// Minimal protobuf wire editor. It preserves all unknown fields byte-for-byte
// and only rewrites length-delimited messages that contain fields we explicitly
// know.
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

const AD_MARKER_BYTES = AD_MARKERS.map(utf8Bytes);
const NEXT_AD_STRONG_MARKER_BYTES = NEXT_AD_STRONG_MARKERS.map(utf8Bytes);

let feedAdCardsRemoved = 0;
let nextAdFieldsRemoved = 0;
let guideItemsRemoved = 0;

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

function bytesEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function bytesContainsSubsequence(bytes, seq) {
  if (!seq || seq.length === 0) return true;
  const limit = bytes.length - seq.length;
  if (limit < 0) return false;
  const first = seq[0];
  let idx = bytes.indexOf(first);
  while (idx !== -1 && idx <= limit) {
    let matched = true;
    for (let j = 1; j < seq.length; j += 1) {
      if (bytes[idx + j] !== seq[j]) {
        matched = false;
        break;
      }
    }
    if (matched) return true;
    idx = bytes.indexOf(first, idx + 1);
  }
  return false;
}

function bytesContainsAnySubsequence(bytes, seqList) {
  for (let i = 0; i < seqList.length; i += 1) {
    if (bytesContainsSubsequence(bytes, seqList[i])) return true;
  }
  return false;
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
      payload = bytes.subarray(valueStart, valueEnd);
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
      raw: bytes.subarray(start, valueEnd),
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
  const backgroundAbility = encodeVarintField(1, 1);
  return encodeLengthField(64657230, backgroundAbility);
}

function makePictureInPictureRender() {
  const pictureAbility = concatBytes([
    encodeVarintField(1, 1),
    encodeVarintField(8, 1),
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
    if (
      field.fieldNo === PLAYER_FIELDS.adPlacements ||
      field.fieldNo === PLAYER_FIELDS.adSlots
    ) {
      removed += 1;
      changed = true;
      continue;
    }

    if (
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      field.payload.length >= 80 &&
      field.payload.length <= 250000 &&
      bytesContainStrongNextAdMarker(field.payload)
    ) {
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
      const structured = cleanFeedSurfaceProtobuf(field.payload, "watch-next");
      const payload = cleanNextAdFragmentsProtobuf(structured, 10);
      out.push({ raw: encodeLengthField(WATCH_CONTENT_FIELDS.next, payload) });
      changed = true;
      continue;
    }
    if (field.wireType === WIRE_LENGTH && field.payload && field.payload.length >= 120 && field.payload.length <= 300000) {
      if (isLikelyNextAdFragment(field.payload) || bytesContainStrongNextAdMarker(field.payload)) {
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

function textContainsAnyMarker(text, markers) {
  return markers.some((marker) => text.includes(marker));
}

function bytesContainAdMarker(bytes) {
  return bytesContainsAnySubsequence(bytes, AD_MARKER_BYTES);
}

function bytesContainStrongNextAdMarker(bytes) {
  return bytesContainsAnySubsequence(bytes, NEXT_AD_STRONG_MARKER_BYTES);
}

function isLikelyNextAdFragment(payload) {
  if (payload.length < 180 || payload.length > 220000) return false;
  if (!bytesContainStrongNextAdMarker(payload)) return false;

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
  if (depth <= 0 || bytes.length < 180 || !bytesContainStrongNextAdMarker(bytes)) {
    return bytes;
  }

  let changed = false;
  const out = [];
  for (const field of parseFields(bytes)) {
    if (
      field.wireType !== WIRE_LENGTH ||
      !field.payload ||
      field.payload.length < 180 ||
      !bytesContainStrongNextAdMarker(field.payload)
    ) {
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

function markerHits(bytes) {
  const text = UTF8_DECODER.decode(bytes);
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
  };
  const hits = [];
  for (const [name, markers] of Object.entries(checks)) {
    if (textContainsAnyMarker(text, markers)) hits.push(name);
  }
  return hits;
}

const ITEM_SECTION_RENDERER_FIELD = 50195462;
const ITEM_SECTION_RENDERER_TAG = encodeTag(ITEM_SECTION_RENDERER_FIELD, WIRE_LENGTH);
const RICH_ITEM_CONTENT_FIELD = 1;

const PIVOT_BAR_RENDERER_FIELD = 117866661;
const PIVOT_BAR_RENDERER_TAG = encodeTag(PIVOT_BAR_RENDERER_FIELD, WIRE_LENGTH);
const PIVOT_BAR_ITEM_FIELD = 1;
const PIVOT_BAR_ICON_ONLY_ITEM_RENDERER_FIELD = 318370163;
const GUIDE_SECTION_RENDERER_FIELD = 46887524;

const FE_UPLOADS_BYTES = utf8Bytes("FEuploads");
const FE_SHORTS_BYTES = utf8Bytes("FEshorts");
const FE_MUSIC_IMMERSIVE_BYTES = utf8Bytes("FEmusic_immersive");

const FEED_AD_UI_MARKER_BYTES = [
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
].map(utf8Bytes);

const FEED_AD_NETWORK_MARKER_BYTES = [
  "pagead",
  "googleads",
  "googleadservices",
  "doubleclick.net",
  "adclick",
  "adview",
].map(utf8Bytes);

const FEED_AD_BADGE_TEXT_MARKER_BYTES = [
  "赞助商广告",
  "付费宣传",
  "付费推广",
  "Sponsored",
].map(utf8Bytes);

const REEL_AD_UI_MARKER_BYTES = [
  "ad_badge.eml-fe",
  "ad_button.eml-fe",
  "inline_injection_entrypoint_layout.eml",
  "reel_player_overlay_ad",
  "reel_player_underlay_ad",
  "adSlotRenderer",
  "adClientParams",
].map(utf8Bytes);

function isDirectFeedAdItem(payload) {
  if (!payload || payload.length < 64) return false;

  if (bytesContainsAnySubsequence(payload, FEED_AD_UI_MARKER_BYTES)) {
    return true;
  }

  if (payload.length >= 1000 && bytesContainsAnySubsequence(payload, FEED_AD_NETWORK_MARKER_BYTES)) {
    return true;
  }

  if (payload.length < 4096) return false;
  return bytesContainsAnySubsequence(payload, FEED_AD_BADGE_TEXT_MARKER_BYTES);
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
  if (depth <= 0 || !bytesContainsSubsequence(bytes, ITEM_SECTION_RENDERER_TAG)) return bytes;

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
    } else if (bytesContainsSubsequence(field.payload, ITEM_SECTION_RENDERER_TAG)) {
      payload = cleanKnownFeedItemSections(field.payload, depth - 1, counters);
    } else {
      payload = field.payload;
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
  const counters = { sections: 0, items: 0, removed: 0 };
  const output = cleanKnownFeedItemSections(bytes, 18, counters);
  feedAdCardsRemoved = counters.removed;

  if (counters.removed === 0) {
    if (config.debug === true) {
      const hits = markerHits(bytes);
      debug(
        `${surface}-schema hits=${hits.join("|") || "none"} sections=${counters.sections} items=${counters.items} removed=0 bytes=${bytes.length}`,
      );
    }
    return bytes;
  }

  const ratio = output.length / Math.max(bytes.length, 1);
  const remainingItems = counters.items - counters.removed;
  const tooManyItemsRemoved =
    remainingItems <= 0 ||
    counters.removed > Math.max(4, Math.floor(counters.items / 2));
  if (tooManyItemsRemoved) {
    const hits = markerHits(bytes);
    logbook(
      `${surface}-schema-safety hits=${hits.join("|") || "none"} sections=${counters.sections} items=${counters.items} removed=${counters.removed} remaining=${remainingItems} ratio=${ratio.toFixed(3)}`,
    );
    feedAdCardsRemoved = 0;
    return bytes;
  }

  if (config.debug === true) {
    const hits = markerHits(bytes);
    debug(
      `${surface}-schema hits=${hits.join("|") || "none"} sections=${counters.sections} items=${counters.items} removed=${counters.removed} remaining=${remainingItems} ratio=${ratio.toFixed(3)} ${bytes.length} -> ${output.length}`,
    );
  }
  return output;
}

function activeBlockedGuideIds() {
  const blocked = [];
  if (config.blockUpload) blocked.push(FE_UPLOADS_BYTES);
  if (config.blockShorts) blocked.push(FE_SHORTS_BYTES);
  if (config.blockImmersive) blocked.push(FE_MUSIC_IMMERSIVE_BYTES);
  return blocked;
}

function protobufHasExactBytesField(bytes, targetBytes, depth) {
  if (depth <= 0 || !bytes || bytes.length < targetBytes.length) return false;
  if (!bytesContainsSubsequence(bytes, targetBytes)) return false;

  let fields;
  try {
    fields = parseFields(bytes);
  } catch {
    return false;
  }

  for (const field of fields) {
    if (field.wireType !== WIRE_LENGTH || !field.payload) continue;
    if (bytesEqual(field.payload, targetBytes)) return true;
    if (
      field.payload.length > targetBytes.length &&
      protobufHasExactBytesField(field.payload, targetBytes, depth - 1)
    ) {
      return true;
    }
  }
  return false;
}

function isBlockedPivotOrGuideItem(payload, blockedIds) {
  if (!payload || payload.length === 0) return false;
  if (config.blockUpload) {
    try {
      const topFields = parseFields(payload);
      if (
        topFields.some(
          (f) => f.fieldNo === PIVOT_BAR_ICON_ONLY_ITEM_RENDERER_FIELD && f.wireType === WIRE_LENGTH,
        )
      ) {
        return true;
      }
    } catch {
      // fall through
    }
  }
  for (let i = 0; i < blockedIds.length; i += 1) {
    if (protobufHasExactBytesField(payload, blockedIds[i], 8)) return true;
  }
  return false;
}

function cleanPivotOrGuideSectionItems(payload, blockedIds, counters) {
  let fields;
  try {
    fields = parseFields(payload);
  } catch {
    return payload;
  }

  let totalItems = 0;
  let removed = 0;
  const out = [];
  for (const field of fields) {
    if (field.fieldNo === PIVOT_BAR_ITEM_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      totalItems += 1;
      if (isBlockedPivotOrGuideItem(field.payload, blockedIds)) {
        removed += 1;
        continue;
      }
    }
    out.push(field);
  }

  // Never empty all navigation tabs in a bar/section.
  if (removed === 0 || totalItems - removed <= 0) return payload;
  counters.removed += removed;
  return rebuildFields(out);
}

function cleanGuideTree(bytes, depth, blockedIds, counters) {
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

    let payload = field.payload;
    if (
      field.fieldNo === PIVOT_BAR_RENDERER_FIELD ||
      field.fieldNo === GUIDE_SECTION_RENDERER_FIELD
    ) {
      payload = cleanPivotOrGuideSectionItems(field.payload, blockedIds, counters);
    } else if (
      bytesContainsSubsequence(field.payload, PIVOT_BAR_RENDERER_TAG) ||
      bytesContainsAnySubsequence(field.payload, blockedIds)
    ) {
      payload = cleanGuideTree(field.payload, depth - 1, blockedIds, counters);
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

function cleanGuideProtobuf(bytes) {
  const blockedIds = activeBlockedGuideIds();
  if (blockedIds.length === 0) return bytes;
  if (
    !bytesContainsSubsequence(bytes, PIVOT_BAR_RENDERER_TAG) &&
    !bytesContainsAnySubsequence(bytes, blockedIds)
  ) {
    return bytes;
  }

  const counters = { removed: 0 };
  const output = cleanGuideTree(bytes, 10, blockedIds, counters);
  if (counters.removed > 0) {
    guideItemsRemoved += counters.removed;
    debug(`guide-tabs removed=${counters.removed} ${bytes.length} -> ${output.length}`);
  }
  return output;
}

function isDirectReelAdEntry(payload) {
  if (!payload || payload.length < 64) return false;
  if (bytesContainsAnySubsequence(payload, REEL_AD_UI_MARKER_BYTES)) return true;
  if (payload.length >= 256 && bytesContainsAnySubsequence(payload, FEED_AD_NETWORK_MARKER_BYTES)) {
    return true;
  }
  if (payload.length >= 1024 && bytesContainsAnySubsequence(payload, FEED_AD_BADGE_TEXT_MARKER_BYTES)) {
    return true;
  }
  return false;
}

function cleanReelWatchSequenceProtobuf(bytes) {
  let fields;
  try {
    fields = parseFields(bytes);
  } catch {
    return bytes;
  }

  // ResponseContext is always field 1; sequence entries are repeated length-delimited messages.
  const fieldCounts = new Map();
  for (const field of fields) {
    if (field.fieldNo !== 1 && field.wireType === WIRE_LENGTH && field.payload && field.payload.length >= 64) {
      fieldCounts.set(field.fieldNo, (fieldCounts.get(field.fieldNo) || 0) + 1);
    }
  }

  let totalEntries = 0;
  let removedEntries = 0;
  const out = [];
  for (const field of fields) {
    const isEntryCandidate =
      field.fieldNo !== 1 &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      field.payload.length >= 64 &&
      ((fieldCounts.get(field.fieldNo) || 0) >= 2 || field.fieldNo === 5);

    if (isEntryCandidate) {
      totalEntries += 1;
      if (isDirectReelAdEntry(field.payload)) {
        removedEntries += 1;
        continue;
      }
    }
    out.push(field);
  }

  if (removedEntries === 0) return bytes;
  const remainingEntries = totalEntries - removedEntries;
  if (remainingEntries <= 0 || removedEntries > Math.max(3, Math.floor(totalEntries / 2))) {
    logbook(
      `reel-schema-safety entries=${totalEntries} removed=${removedEntries} remaining=${remainingEntries}`,
    );
    return bytes;
  }

  feedAdCardsRemoved += removedEntries;
  debug(`reel-sequence entries=${totalEntries} removed=${removedEntries} ${bytes.length} -> ${bytes.length}`);
  return rebuildFields(out);
}

function cleanProtobuf(bytes, endpoint) {
  feedAdCardsRemoved = 0;
  nextAdFieldsRemoved = 0;
  guideItemsRemoved = 0;
  if (endpoint === "player") return cleanPlayerProtobuf(bytes);
  if (endpoint === "next") {
    const structured = cleanFeedSurfaceProtobuf(bytes, "next");
    return cleanNextAdFragmentsProtobuf(structured, 8);
  }
  if (endpoint === "get_watch") return cleanWatchProtobuf(bytes);
  if (endpoint === "account/get_setting" || endpoint === "account/get_setting_values") {
    return cleanSettingProtobuf(bytes);
  }
  if (endpoint === "browse") {
    const cleanedFeed = cleanFeedSurfaceProtobuf(bytes, "browse");
    return cleanGuideProtobuf(cleanedFeed);
  }
  if (endpoint === "search") {
    return cleanFeedSurfaceProtobuf(bytes, "search");
  }
  if (endpoint === "guide") {
    return cleanGuideProtobuf(bytes);
  }
  if (endpoint === "reel/reel_watch_sequence") {
    return cleanReelWatchSequenceProtobuf(bytes);
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
    const result = cleanJsonResult(textBody, endpoint);
    if (!result.changed) {
      debug(`json-passthrough ${endpoint} type=${inputType} bytes=${textBody.length}`);
      $done({});
    } else {
      debug(`json ${endpoint} type=${inputType} ${textBody.length} -> ${result.body.length}`);
      $done({ body: result.body });
    }
  } else {
    const input = bodyBytes(originalBody);
    const output = cleanProtobuf(input, endpoint);
    const removedCount = feedAdCardsRemoved + nextAdFieldsRemoved + guideItemsRemoved;

    const isSettingEndpoint =
      endpoint === "account/get_setting" || endpoint === "account/get_setting_values";
    const maxInflationBytes = isSettingEndpoint ? 256 : 64;
    const maxOutputBytes = Math.max(
      Math.floor(input.length * 1.02) + 32,
      isSettingEndpoint ? input.length + 256 : 0,
    );
    if (output.length > input.length + maxInflationBytes) {
      logbook(
        `protobuf-inflation-abort ${endpoint} type=${inputType} ${input.length} -> ${output.length}`,
      );
      $done({});
    } else if (output.length > maxOutputBytes) {
      logbook(
        `protobuf-growth-abort ${endpoint} type=${inputType} ${input.length} -> ${output.length}`,
      );
      $done({});
    } else {
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
        debug(`protobuf-passthrough ${endpoint} type=${inputType} bytes=${input.length}`);
        $done({});
      } else {
        const removed = removedCount ? ` removed=${removedCount}` : "";
        debug(`protobuf ${endpoint} type=${inputType} ${input.length} -> ${output.length}${removed}`);
        $done({ body: toResponseBody(output, originalBody) });
      }
    }
  }
} catch (error) {
  logbook(`error ${endpoint} ${error && error.message ? error.message : error}`);
  $done({});
}
