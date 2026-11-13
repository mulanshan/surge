/*
 * Self-hosted Bilibili response sanitizer for Surge.
 *
 * Scope:
 * - Clean explicit commercial ads on whitelisted JSON endpoints (splash,
 *   home/story feeds, search square, live room ad banners) and optional
 *   bottom Mall tab hiding when explicitly enabled via module arguments.
 * - Clean explicit commercial fields/cards on whitelisted unary gRPC
 *   Protobuf endpoints (View/View, View/RelatesFeed in view.v1 & viewunite.v1,
 *   Reply/MainList, Dynamic/DynAll) when the gRPC frame is uncompressed.
 * - Preserve organic recommendations (including is_ad_loc slots without
 *   ad_info), creator-pinned comments (up_top), playback streams, danmaku,
 *   account/VIP state, and unknown/compressed frames.
 *
 * Clean-room MIT implementation. Makes no network requests, persists no state,
 * and never logs user identifiers, URLs with query parameters, or raw bodies.
 */
"use strict";

const DEFAULTS = {
  cleanAds: true,
  hideMallTab: false,
  debug: false,
};

const WIRE_VARINT = 0;
const WIRE_64BIT = 1;
const WIRE_LENGTH = 2;
const WIRE_32BIT = 5;

const SPLASH_FAR_FUTURE_BEGIN = 2524608000;
const SPLASH_FAR_FUTURE_END = 2524608001;
const SPLASH_LONG_INTERVAL = 86400;

const VIEW_V1_AD_FIELDS = new Set([
  30, // cms
  31, // cm_config
  41, // cm_ipad
  48, // cm_under_player
]);
const VIEW_V1_RELATES_FIELD = 10;
const RELATE_V1_GOTO_FIELD = 7;
const RELATE_V1_CM_FIELD = 28;

const VIEWUNITE_TAB_FIELD = 5;
const VIEWUNITE_CM_FIELD = 7;
const TAB_MODULE_FIELD = 1;
const TAB_INTRODUCTION_FIELD = 2;
const INTRO_MODULES_FIELD = 2;
const MODULE_RELATES_FIELD = 22;
const RELATES_CARDS_FIELD = 1;
const RELATE_CARD_TYPE_FIELD = 1;
const RELATE_CARD_TYPE_CM = 5;
const RELATE_CARD_CM_FIELD = 6;
const RELATE_CARD_CM_STOCK_FIELD = 11;

const REPLY_MAIN_CM_FIELD = 11;

const DYN_ALL_LIST_FIELD = 1;
const DYN_LIST_ITEMS_FIELD = 1;
const DYN_ITEM_CARD_TYPE_FIELD = 1;
const DYN_ITEM_ITEM_TYPE_FIELD = 2;
const DYNAMIC_TYPE_AD = 15;

const UTF8_DECODER = new TextDecoder("utf-8");
const UTF8_ENCODER = new TextEncoder();

const JSON_HOST_ALLOWLIST = new Set([
  "app.bilibili.com",
  "api.bilibili.com",
  "api.live.bilibili.com",
]);

const GRPC_HOST_ALLOWLIST = new Set([
  "grpc.biliapi.net",
  "app.bilibili.com",
]);

const JSON_ROUTE_MAP = Object.freeze({
  "/x/v2/splash/list": "splash_list",
  "/x/v2/splash/show": "splash_show",
  "/x/v2/splash/event/list2": "splash_event",
  "/x/v2/splash/brand/list": "splash_brand",
  "/x/v2/feed/index": "feed_index",
  "/x/v2/feed/index/story": "feed_story",
  "/x/v2/search/square": "search_square",
  "/x/resource/show/tab/v2": "show_tab",
  "/xlive/app-room/v1/index/getInfoByRoom": "live_room_info",
});

const GRPC_ROUTE_MAP = Object.freeze({
  "/bilibili.app.view.v1.View/View": "grpc_view_v1",
  "/bilibili.app.view.v1.View/RelatesFeed": "grpc_relates_v1",
  "/bilibili.app.viewunite.v1.View/View": "grpc_viewunite_v1",
  "/bilibili.app.viewunite.v1.View/RelatesFeed": "grpc_relates_unite_v1",
  "/bilibili.main.community.reply.v1.Reply/MainList": "grpc_reply_main",
  "/bilibili.app.dynamic.v2.Dynamic/DynAll": "grpc_dynamic_all",
});

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasNonEmptyObject(value) {
  return isPlainObject(value) && Object.keys(value).length > 0;
}

function parseBool(value, fallback) {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true" || normalized === "1") return true;
    if (normalized === "false" || normalized === "0") return false;
  }
  return fallback;
}

function parseArgument(raw) {
  const result = Object.assign({}, DEFAULTS);
  if (!raw) return result;

  if (isPlainObject(raw)) {
    result.cleanAds = parseBool(raw.cleanAds, result.cleanAds);
    result.hideMallTab = parseBool(raw.hideMallTab, result.hideMallTab);
    result.debug = parseBool(raw.debug, result.debug);
    return result;
  }

  if (typeof raw !== "string") return result;
  const trimmed = raw.trim();
  if (!trimmed) return result;

  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (isPlainObject(parsed)) return parseArgument(parsed);
    } catch {
      return result;
    }
  }

  for (const part of trimmed.split(/[&,]/)) {
    const eq = part.indexOf("=");
    const colon = part.indexOf(":");
    const sep = eq !== -1 ? eq : colon;
    if (sep === -1) continue;
    const key = part.slice(0, sep).trim();
    const val = part.slice(sep + 1).trim();
    if (key === "cleanAds" || key === "清理明确广告") {
      result.cleanAds = parseBool(val, result.cleanAds);
    } else if (key === "hideMallTab" || key === "隐藏底栏会员购") {
      result.hideMallTab = parseBool(val, result.hideMallTab);
    } else if (key === "debug" || key === "启用调试模式") {
      result.debug = parseBool(val, result.debug);
    }
  }
  return result;
}

function logDiagnostic(enabled, message) {
  if (!enabled) return;
  const line = `[Bilibili Self] ${message}`;
  console.log(line);
  try {
    if (typeof $surge !== "undefined" && typeof $surge.logbook === "function") {
      $surge.logbook(line);
    }
  } catch {
    // Diagnostic logging must never break response handling.
  }
}

function resolveRoute(url) {
  const match = /^https:\/\/([^/?#]+)(\/[^?#]*)/.exec(String(url || ""));
  if (!match) return null;
  const host = match[1].toLowerCase();
  const path = match[2];

  if ( Object.prototype.hasOwnProperty.call(GRPC_ROUTE_MAP, path) && GRPC_HOST_ALLOWLIST.has(host) ) {
    return { kind: "grpc", route: GRPC_ROUTE_MAP[path] };
  }
  if ( Object.prototype.hasOwnProperty.call(JSON_ROUTE_MAP, path) && JSON_HOST_ALLOWLIST.has(host) ) {
    return { kind: "json", route: JSON_ROUTE_MAP[path] };
  }
  return null;
}

function isHttpSuccess(response) {
  if (!response || response.status === undefined || response.status === null) return true;
  const code = Number(response.status);
  return Number.isFinite(code) && code >= 200 && code < 300;
}

function readRawBody(response) {
  if (!response) return null;
  if (response.bodyBytes !== undefined && response.bodyBytes !== null) return response.bodyBytes;
  if (response.body !== undefined && response.body !== null) return response.body;
  return null;
}

function toBytes(raw) {
  if (raw instanceof Uint8Array) return raw;
  if (raw instanceof ArrayBuffer) return new Uint8Array(raw);
  if (ArrayBuffer.isView(raw)) return new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength);
  if (typeof raw === "string") {
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) {
      out[i] = raw.charCodeAt(i) & 0xff;
    }
    return out;
  }
  return new Uint8Array(0);
}

function toUtf8Text(raw) {
  if (typeof raw === "string") return raw;
  if (raw instanceof Uint8Array) return UTF8_DECODER.decode(raw);
  if (raw instanceof ArrayBuffer) return UTF8_DECODER.decode(new Uint8Array(raw));
  if (ArrayBuffer.isView(raw)) {
    return UTF8_DECODER.decode(new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength));
  }
  return "";
}

function fromUtf8Text(text, originalRaw) {
  if (typeof originalRaw === "string") return text;
  return UTF8_ENCODER.encode(text);
}

function fromBytes(bytes, originalRaw) {
  if (typeof originalRaw === "string") {
    const chunk = 0x8000;
    let out = "";
    for (let i = 0; i < bytes.length; i += chunk) {
      out += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + chunk, bytes.length)));
    }
    return out;
  }
  return bytes;
}

function isBannerAdEntry(entry) {
  if (!isPlainObject(entry)) return false;
  if (entry.is_ad === true) return true;
  if (typeof entry.type === "string" && entry.type.toLowerCase() === "ad") return true;
  if (hasNonEmptyObject(entry.ad_info) || hasNonEmptyObject(entry.ads_info)) return true;
  if (typeof entry.ad_cb === "string" && entry.ad_cb.length > 0) return true;
  if (typeof entry.cm_mark === "number" && entry.cm_mark > 0) return true;
  return false;
}

function isFeedAdItem(item) {
  if (!isPlainObject(item)) return false;
  // Note: Never filter on `is_ad_loc` alone; Bilibili marks organic fallback
  // videos in ad-eligible slots with `is_ad_loc: true` and no `ad_info`.
  if (item.is_ad === true) return true;
  if (hasNonEmptyObject(item.ad_info) || hasNonEmptyObject(item.ads_info)) return true;
  if (typeof item.ad_cb === "string" && item.ad_cb.length > 0) return true;

  const gotoVal = typeof item.goto === "string" ? item.goto.toLowerCase() : "";
  if (gotoVal === "ad" || gotoVal.startsWith("ad_") || gotoVal === "cm") return true;

  const cardGoto = typeof item.card_goto === "string" ? item.card_goto.toLowerCase() : "";
  if (
    cardGoto === "ad" ||
    cardGoto.startsWith("ad_") ||
    cardGoto.startsWith("cm_") ||
    cardGoto === "live_ad"
  ) {
    return true;
  }

  return false;
}

function cleanSplashJson(payload, route) {
  if (!isPlainObject(payload) || !isPlainObject(payload.data)) return 0;
  const data = payload.data;
  let removed = 0;

  if (Array.isArray(data.show) && data.show.length > 0) {
    removed += data.show.length;
    data.show = [];
  }

  // Keep user-selectable launch logos in /x/v2/splash/brand/list while clearing
  // forced commercial `show` schedules.
  if (route === "splash_brand") {
    return removed;
  }

  if (Array.isArray(data.event_list) && data.event_list.length > 0) {
    removed += data.event_list.length;
    data.event_list = [];
  }

  if (route === "splash_show" || route === "splash_event") {
    if (Array.isArray(data.list) && data.list.length > 0) {
      removed += data.list.length;
      data.list = [];
    }
    return removed;
  }

  // /x/v2/splash/list: neutralize schedule intervals and push cached items
  // into the far future with zero duration so iOS evicts disk-cached splashes.
  if (typeof data.max_time === "number" && data.max_time !== 0) {
    data.max_time = 0;
    removed += 1;
  }
  if (typeof data.min_interval === "number" && data.min_interval < SPLASH_LONG_INTERVAL) {
    data.min_interval = SPLASH_LONG_INTERVAL;
    removed += 1;
  }
  if (typeof data.pull_interval === "number" && data.pull_interval < SPLASH_LONG_INTERVAL) {
    data.pull_interval = SPLASH_LONG_INTERVAL;
    removed += 1;
  }
  if (Array.isArray(data.list)) {
    for (const item of data.list) {
      if (!isPlainObject(item)) continue;
      if (
        item.duration !== 0 ||
        item.begin_time !== SPLASH_FAR_FUTURE_BEGIN ||
        item.end_time !== SPLASH_FAR_FUTURE_END
      ) {
        item.duration = 0;
        item.begin_time = SPLASH_FAR_FUTURE_BEGIN;
        item.end_time = SPLASH_FAR_FUTURE_END;
        if ("enable_pre_download" in item) item.enable_pre_download = false;
        removed += 1;
      }
    }
  }
  return removed;
}

function cleanFeedJson(payload) {
  if (!isPlainObject(payload) || !isPlainObject(payload.data)) return 0;
  const items = payload.data.items;
  if (!Array.isArray(items) || items.length === 0) return 0;

  let removed = 0;
  const kept = [];

  for (const item of items) {
    if (isFeedAdItem(item)) {
      removed += 1;
      continue;
    }

    if (isPlainObject(item) && Array.isArray(item.banner_item)) {
      const cleanBanners = item.banner_item.filter((entry) => !isBannerAdEntry(entry));
      const droppedBanners = item.banner_item.length - cleanBanners.length;
      if (droppedBanners > 0) {
        removed += droppedBanners;
        if (cleanBanners.length === 0) {
          continue;
        }
        item.banner_item = cleanBanners;
      }
    }

    kept.push(item);
  }

  if (removed > 0) {
    payload.data.items = kept;
  }
  return removed;
}

function isSearchSquareAdBlock(block) {
  if (!isPlainObject(block)) return false;
  const type = typeof block.type === "string" ? block.type.toLowerCase() : "";
  if (type === "ada" || type === "ad" || type === "cm") return true;
  if (block.is_ad === true || hasNonEmptyObject(block.ad_info)) return true;
  return false;
}

function cleanSearchSquareJson(payload) {
  if (!isPlainObject(payload) || !Array.isArray(payload.data)) return 0;
  let removed = 0;
  const keptBlocks = [];

  for (const block of payload.data) {
    if (isSearchSquareAdBlock(block)) {
      removed += 1;
      continue;
    }
    if (isPlainObject(block) && isPlainObject(block.data) && Array.isArray(block.data.list)) {
      const list = block.data.list;
      const cleanList = list.filter((entry) => !isFeedAdItem(entry) && !isBannerAdEntry(entry));
      if (cleanList.length !== list.length) {
        removed += list.length - cleanList.length;
        block.data.list = cleanList;
      }
    }
    keptBlocks.push(block);
  }

  if (keptBlocks.length !== payload.data.length) {
    payload.data = keptBlocks;
  }
  return removed;
}

function cleanLiveRoomJson(payload) {
  if (!isPlainObject(payload) || !isPlainObject(payload.data)) return 0;
  let removed = 0;
  if (payload.data.activity_banner_info !== null && payload.data.activity_banner_info !== undefined) {
    payload.data.activity_banner_info = null;
    removed += 1;
  }
  if (payload.data.ad_banner_info !== null && payload.data.ad_banner_info !== undefined) {
    payload.data.ad_banner_info = null;
    removed += 1;
  }
  return removed;
}

function isMallBottomTab(tab) {
  if (!isPlainObject(tab)) return false;
  const tabId = typeof tab.tab_id === "string" ? tab.tab_id.toLowerCase() : "";
  if (tabId === "global_mall" || tabId === "mall" || tabId === "会员购bottom") return true;
  const uri = typeof tab.uri === "string" ? tab.uri.toLowerCase() : "";
  if (uri.startsWith("bilibili://mall/")) return true;
  if (tab.name === "会员购") return true;
  return false;
}

function cleanShowTabJson(payload, config) {
  if (!config.hideMallTab) return 0;
  if (!isPlainObject(payload) || !isPlainObject(payload.data)) return 0;
  const bottom = payload.data.bottom;
  if (!Array.isArray(bottom) || bottom.length === 0) return 0;

  const kept = bottom.filter((item) => !isMallBottomTab(item));
  const removed = bottom.length - kept.length;
  if (removed > 0 && kept.length > 0) {
    if (kept.every((item) => isPlainObject(item) && typeof item.pos === "number")) {
      for (let i = 0; i < kept.length; i += 1) {
        kept[i].pos = i + 1;
      }
    }
    payload.data.bottom = kept;
    return removed;
  }
  return 0;
}

function handleJsonRoute(route, rawBody, config) {
  if (route === "show_tab" && !config.hideMallTab) return null;
  if (route !== "show_tab" && !config.cleanAds) return null;

  const text = toUtf8Text(rawBody);
  if (!text) return null;
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) return null;

  const payload = JSON.parse(text);
  let removed = 0;
  if (
    route === "splash_list" ||
    route === "splash_show" ||
    route === "splash_event" ||
    route === "splash_brand"
  ) {
    removed = cleanSplashJson(payload, route);
  } else if (route === "feed_index" || route === "feed_story") {
    removed = cleanFeedJson(payload);
  } else if (route === "search_square") {
    removed = cleanSearchSquareJson(payload);
  } else if (route === "live_room_info") {
    removed = cleanLiveRoomJson(payload);
  } else if (route === "show_tab") {
    removed = cleanShowTabJson(payload, config);
  }

  if (removed <= 0) return null;
  const serialized = JSON.stringify(payload);
  return {
    body: fromUtf8Text(serialized, rawBody),
    removed,
    inLen: text.length,
    outLen: serialized.length,
  };
}

// --- Clean-room Protobuf & gRPC unary wire helpers ---

function readVarint(bytes, offset) {
  let value = 0;
  let multiplier = 1;
  let pos = offset;
  // Support full 64-bit unsigned/twos-complement varints (up to 10 bytes) so
  // negative int32/int64 varints in unknown fields skip cleanly without throwing.
  for (let count = 0; count < 10 && pos < bytes.length; count += 1) {
    const byte = bytes[pos];
    pos += 1;
    if (count < 7) {
      value += (byte & 0x7f) * multiplier;
      multiplier *= 128;
    }
    if ((byte & 0x80) === 0) {
      return { value, offset: pos };
    }
  }
  throw new Error("invalid protobuf varint");
}

function writeVarint(value) {
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("invalid non-negative varint");
  }
  const out = [];
  let n = Math.floor(value);
  while (n > 0x7f) {
    out.push((n & 0x7f) | 0x80);
    n = Math.floor(n / 128);
  }
  out.push(n);
  return new Uint8Array(out);
}

function concatBytes(parts) {
  let total = 0;
  for (const part of parts) total += part.length;
  const out = new Uint8Array(total);
  let pos = 0;
  for (const part of parts) {
    out.set(part, pos);
    pos += part.length;
  }
  return out;
}

function encodeLengthField(fieldNo, payload) {
  const tag = writeVarint(fieldNo * 8 + WIRE_LENGTH);
  const len = writeVarint(payload.length);
  return concatBytes([tag, len, payload]);
}

function parseFields(bytes) {
  const fields = [];
  let pos = 0;
  while (pos < bytes.length) {
    const start = pos;
    const tagInfo = readVarint(bytes, pos);
    pos = tagInfo.offset;
    const wireType = tagInfo.value & 7;
    const fieldNo = Math.floor(tagInfo.value / 8);
    if (fieldNo <= 0) throw new Error("invalid protobuf field number");

    let end;
    let payload = null;
    let varintValue = null;

    if (wireType === WIRE_VARINT) {
      const valInfo = readVarint(bytes, pos);
      varintValue = valInfo.value;
      end = valInfo.offset;
    } else if (wireType === WIRE_64BIT) {
      end = pos + 8;
    } else if (wireType === WIRE_LENGTH) {
      const lenInfo = readVarint(bytes, pos);
      const startPayload = lenInfo.offset;
      end = startPayload + lenInfo.value;
      if (end <= bytes.length) {
        payload = bytes.subarray(startPayload, end);
      }
    } else if (wireType === WIRE_32BIT) {
      end = pos + 4;
    } else {
      throw new Error(`unsupported wire type ${wireType}`);
    }

    if (end > bytes.length) throw new Error("truncated protobuf field");
    fields.push({
      fieldNo,
      wireType,
      varintValue,
      payload,
      raw: bytes.subarray(start, end),
    });
    pos = end;
  }
  return fields;
}

function rebuildFields(fields) {
  return concatBytes(fields.map((field) => field.raw));
}

function isRelateV1Ad(payload) {
  const fields = parseFields(payload);
  for (const field of fields) {
    if (field.fieldNo === RELATE_V1_CM_FIELD && field.wireType === WIRE_LENGTH && field.payload && field.payload.length > 0) {
      return true;
    }
    if (field.fieldNo === RELATE_V1_GOTO_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const gotoStr = UTF8_DECODER.decode(field.payload).toLowerCase();
      if (gotoStr === "cm" || gotoStr === "ad") return true;
    }
  }
  return false;
}

function cleanViewV1Protobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (VIEW_V1_AD_FIELDS.has(field.fieldNo)) {
      removed += 1;
      continue;
    }
    if (field.fieldNo === VIEW_V1_RELATES_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      if (isRelateV1Ad(field.payload)) {
        removed += 1;
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanRelatesFeedV1Protobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === 1 && field.wireType === WIRE_LENGTH && field.payload) {
      if (isRelateV1Ad(field.payload)) {
        removed += 1;
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function isRelateCardUniteAd(payload) {
  const fields = parseFields(payload);
  for (const field of fields) {
    if (field.fieldNo === RELATE_CARD_TYPE_FIELD && field.wireType === WIRE_VARINT && field.varintValue === RELATE_CARD_TYPE_CM) {
      return true;
    }
    if (
      (field.fieldNo === RELATE_CARD_CM_FIELD || field.fieldNo === RELATE_CARD_CM_STOCK_FIELD) &&
      field.wireType === WIRE_LENGTH &&
      field.payload &&
      field.payload.length > 0
    ) {
      return true;
    }
  }
  return false;
}

function cleanCommonRelatesProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;
  let keptCards = 0;

  for (const field of fields) {
    if (field.fieldNo === RELATES_CARDS_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      if (isRelateCardUniteAd(field.payload)) {
        removed += 1;
        continue;
      }
      keptCards += 1;
    }
    out.push(field);
  }

  if (removed === 0) return null;
  return { bytes: rebuildFields(out), removed, keptCards };
}

function cleanIntroductionModuleProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;
  let dropEntireModule = false;

  for (const field of fields) {
    if (field.fieldNo === MODULE_RELATES_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const cleaned = cleanCommonRelatesProtobuf(field.payload);
      if (cleaned) {
        removed += cleaned.removed;
        if (cleaned.keptCards === 0) {
          dropEntireModule = true;
          continue;
        }
        out.push({ raw: encodeLengthField(field.fieldNo, cleaned.bytes) });
        continue;
      }
    }
    out.push(field);
  }

  if (removed === 0) return null;
  return { bytes: dropEntireModule ? null : rebuildFields(out), removed };
}

function cleanIntroductionTabProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === INTRO_MODULES_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const cleaned = cleanIntroductionModuleProtobuf(field.payload);
      if (cleaned) {
        removed += cleaned.removed;
        if (cleaned.bytes !== null) {
          out.push({ raw: encodeLengthField(field.fieldNo, cleaned.bytes) });
        }
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanTabModuleProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === TAB_INTRODUCTION_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const cleaned = cleanIntroductionTabProtobuf(field.payload);
      if (cleaned) {
        removed += cleaned.removed;
        out.push({ raw: encodeLengthField(field.fieldNo, cleaned.bytes) });
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanViewUniteTabProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === TAB_MODULE_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const cleaned = cleanTabModuleProtobuf(field.payload);
      if (cleaned) {
        removed += cleaned.removed;
        out.push({ raw: encodeLengthField(field.fieldNo, cleaned.bytes) });
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanViewUniteProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === VIEWUNITE_CM_FIELD) {
      removed += 1;
      continue;
    }
    if (field.fieldNo === VIEWUNITE_TAB_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const cleanedTab = cleanViewUniteTabProtobuf(field.payload);
      if (cleanedTab) {
        removed += cleanedTab.removed;
        out.push({ raw: encodeLengthField(field.fieldNo, cleanedTab.bytes) });
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanRelatesFeedUniteProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === 1 && field.wireType === WIRE_LENGTH && field.payload) {
      if (isRelateCardUniteAd(field.payload)) {
        removed += 1;
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanReplyMainProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    // Strip only explicit `CM cm = 11`; preserve `up_top = 4` creator-pinned notes.
    if (field.fieldNo === REPLY_MAIN_CM_FIELD) {
      removed += 1;
      continue;
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function isDynamicAdItem(payload) {
  const fields = parseFields(payload);
  for (const field of fields) {
    if (
      (field.fieldNo === DYN_ITEM_CARD_TYPE_FIELD || field.fieldNo === DYN_ITEM_ITEM_TYPE_FIELD) &&
      field.wireType === WIRE_VARINT &&
      field.varintValue === DYNAMIC_TYPE_AD
    ) {
      return true;
    }
  }
  return false;
}

function cleanDynamicListProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === DYN_LIST_ITEMS_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      if (isDynamicAdItem(field.payload)) {
        removed += 1;
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function cleanDynamicAllProtobuf(bytes) {
  const fields = parseFields(bytes);
  const out = [];
  let removed = 0;

  for (const field of fields) {
    if (field.fieldNo === DYN_ALL_LIST_FIELD && field.wireType === WIRE_LENGTH && field.payload) {
      const cleaned = cleanDynamicListProtobuf(field.payload);
      if (cleaned) {
        removed += cleaned.removed;
        out.push({ raw: encodeLengthField(field.fieldNo, cleaned.bytes) });
        continue;
      }
    }
    out.push(field);
  }

  return removed > 0 ? { bytes: rebuildFields(out), removed } : null;
}

function unwrapUnaryGrpcFrame(frameBytes) {
  if (!frameBytes || frameBytes.length < 5) return null;
  // Byte 0 is Compressed-Flag. Only 0x00 (uncompressed) can be safely parsed
  // without zlib; any compressed or trailer frame must pass through untouched.
  if (frameBytes[0] !== 0x00) return null;
  const payloadLength =
    ((frameBytes[1] << 24) >>> 0) +
    (frameBytes[2] << 16) +
    (frameBytes[3] << 8) +
    frameBytes[4];
  if (payloadLength === 0 || 5 + payloadLength !== frameBytes.length) return null;
  return frameBytes.subarray(5, 5 + payloadLength);
}

function wrapUnaryGrpcFrame(payloadBytes) {
  const len = payloadBytes.length;
  const out = new Uint8Array(5 + len);
  out[0] = 0x00;
  out[1] = (len >>> 24) & 0xff;
  out[2] = (len >>> 16) & 0xff;
  out[3] = (len >>> 8) & 0xff;
  out[4] = len & 0xff;
  out.set(payloadBytes, 5);
  return out;
}

function handleGrpcRoute(route, rawBody, config) {
  if (!config.cleanAds) return null;
  const inputBytes = toBytes(rawBody);
  const payload = unwrapUnaryGrpcFrame(inputBytes);
  if (!payload) return null;

  let cleaned = null;
  if (route === "grpc_view_v1") {
    cleaned = cleanViewV1Protobuf(payload);
  } else if (route === "grpc_relates_v1") {
    cleaned = cleanRelatesFeedV1Protobuf(payload);
  } else if (route === "grpc_viewunite_v1") {
    cleaned = cleanViewUniteProtobuf(payload);
  } else if (route === "grpc_relates_unite_v1") {
    cleaned = cleanRelatesFeedUniteProtobuf(payload);
  } else if (route === "grpc_reply_main") {
    cleaned = cleanReplyMainProtobuf(payload);
  } else if (route === "grpc_dynamic_all") {
    cleaned = cleanDynamicAllProtobuf(payload);
  }

  if (!cleaned || cleaned.removed <= 0) return null;
  const outputFrame = wrapUnaryGrpcFrame(cleaned.bytes);

  // Strict non-inflation invariant: stripping ads must never grow a gRPC frame.
  if (outputFrame.length > inputBytes.length) {
    logDiagnostic(
      true,
      `grpc-inflation-abort route=${route} bytes=${inputBytes.length}->${outputFrame.length}`,
    );
    return null;
  }

  return {
    body: fromBytes(outputFrame, rawBody),
    removed: cleaned.removed,
    inLen: inputBytes.length,
    outLen: outputFrame.length,
  };
}

function main() {
  const config = parseArgument(typeof $argument !== "undefined" ? $argument : undefined);
  const requestUrl = typeof $request !== "undefined" && $request ? $request.url : "";
  const response = typeof $response !== "undefined" ? $response : null;

  if (!isHttpSuccess(response)) {
    $done({});
    return;
  }

  const target = resolveRoute(requestUrl);
  if (!target) {
    $done({});
    return;
  }

  const rawBody = readRawBody(response);
  if (rawBody === null) {
    $done({});
    return;
  }

  try {
    const result =
      target.kind === "grpc"
        ? handleGrpcRoute(target.route, rawBody, config)
        : handleJsonRoute(target.route, rawBody, config);

    if (!result) {
      logDiagnostic(config.debug, `passthrough route=${target.route} removed_ads=0`);
      $done({});
      return;
    }

    logDiagnostic(
      config.debug,
      `cleaned route=${target.route} removed_ads=${result.removed} bytes=${result.inLen}->${result.outLen}`,
    );
    $done({ body: result.body });
  } catch (error) {
    const reason = error && error.message ? error.message : "unexpected_error";
    logDiagnostic(config.debug, `passthrough_error route=${target.route} reason=${reason}`);
    $done({});
  }
}

main();
