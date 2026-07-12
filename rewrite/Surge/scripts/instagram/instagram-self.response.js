/*
 * Instagram Self response cleaner for Surge.
 *
 * Scope:
 * - www.instagram.com web feed, explore, clips/reels and GraphQL responses.
 * - Removes only nodes with direct sponsored/ad markers.
 * - Keeps the pinned i.instagram.com native API outside MITM.
 * - Does not issue requests, read cookies, or upload any data.
 */

const DEFAULTS = {
  debug: false,
};

const config = parseArgument();

const AD_LABEL_RE = /(?:\b(?:sponsored|promoted|advertisement|paid partnership|branded content)\b|赞助|推广|广告)/i;
const AD_TYPE_RE = /(?:^|[_\-\s])(?:ad|ads|advertisement|advertiser|promoted|promotion|sponsored)(?:$|[_\-\s])/i;
const AD_TYPE_FIELDS = ["__typename", "type", "product_type", "content_type", "item_type", "view_type"];
const AD_LABEL_FIELDS = ["label", "title", "subtitle", "headline", "message", "reason", "badge_text"];
const DIRECT_FLAG_FIELDS = [
  "is_ad",
  "is_sponsored",
  "sponsored",
  "is_promoted",
  "is_promotion",
  "is_paid_partnership",
  "has_ad",
  "branded_content",
];
const STRONG_MARKER_FIELDS = [
  "ad_id",
  "advertiser_id",
  "ad_metadata",
  "ad_info",
  "ad_action",
  "ad_tracking_token",
  "ads_tracking_token",
  "ad_impression_token",
  "sponsored_label",
  "sponsored_by",
  "sponsor_tags",
];
const AD_COLLECTION_KEYS = new Set([
  "ads",
  "ad_items",
  "injected_ads",
  "sponsored_items",
  "promoted_items",
]);
const AD_METADATA_KEYS = new Set([
  "ad_metadata",
  "ad_info",
  "ad_action",
  "ad_tracking_token",
  "ads_tracking_token",
  "ad_impression_token",
]);
const PRIMARY_WRAPPER_KEYS = new Set([
  "node",
  "item",
  "media",
  "media_or_ad",
  "post",
  "content",
]);

function parseArgument() {
  try {
    return Object.assign({}, DEFAULTS, JSON.parse(typeof $argument === "string" ? $argument : "{}"));
  } catch {
    return DEFAULTS;
  }
}

function logbook(message) {
  const text = `[Instagram Self] ${message}`;
  console.log(text);
  try {
    if (typeof $surge !== "undefined" && typeof $surge.logbook === "function") {
      $surge.logbook(text);
    }
  } catch {
    // Diagnostics only.
  }
}

function debug(message) {
  if (config.debug) logbook(message);
}

function endpointFromUrl(url) {
  const raw = String(url || "");
  const stripped = raw.replace(/^https?:\/\/[^/]+/, "");
  return stripped.split("?")[0];
}

function isSupportedEndpoint(endpoint) {
  return /^\/(?:api\/graphql\/?|graphql\/query\/?|api\/v1\/(?:feed\/|discover\/|clips\/))/.test(endpoint);
}

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function parseJsonBody(text) {
  const prefixes = ["for (;;);", ")]}'"];
  for (const prefix of prefixes) {
    if (text.startsWith(prefix)) {
      return { prefix, payload: JSON.parse(text.slice(prefix.length)) };
    }
  }
  return { prefix: "", payload: JSON.parse(text) };
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function isPlainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function isTruthyFlag(value) {
  if (value === true || value === 1) return true;
  if (typeof value !== "string") return false;
  const normalized = value.trim().toLowerCase();
  return normalized === "true" || normalized === "1" || normalized === "yes";
}

function isTruthyValue(value) {
  if (value === null || value === undefined || value === false) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value) && value !== 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isPlainObject(value)) return Object.keys(value).length > 0;
  return Boolean(value);
}

function isAdType(value) {
  const text = textOf(value).trim();
  if (!text) return false;
  if (AD_TYPE_RE.test(text)) return true;
  return /^XDT(?:GraphQL)?(?:Ad|Sponsored)(?:$|[A-Z_])/.test(text);
}

function hasAdLabel(value) {
  return AD_LABEL_FIELDS.some((key) => AD_LABEL_RE.test(textOf(value[key]).trim()));
}

function hasStrongMarker(value) {
  return STRONG_MARKER_FIELDS.some((key) => hasOwn(value, key) && isTruthyValue(value[key]));
}

function hasAdUnion(value) {
  if (!hasOwn(value, "ad") || !isTruthyValue(value.ad)) return false;
  const keys = Object.keys(value);
  return hasOwn(value, "media") || hasOwn(value, "media_or_ad") || hasOwn(value, "node") || keys.length <= 4;
}

function isAdEntity(value) {
  if (!isPlainObject(value)) return false;

  if (DIRECT_FLAG_FIELDS.some((key) => isTruthyFlag(value[key]))) return true;
  if (STRONG_MARKER_FIELDS.some((key) => key === "sponsor_tags" && isTruthyValue(value[key]))) return true;
  if (hasStrongMarker(value)) return true;
  if (AD_TYPE_FIELDS.some((key) => isAdType(value[key]))) return true;
  if (hasAdLabel(value)) return true;
  if (hasAdUnion(value)) return true;

  const commerciality = textOf(value.commerciality_status).trim();
  if (commerciality && /(?:sponsored|commercial|paid[_\-\s]?partnership|branded)/i.test(commerciality)) return true;

  if (isPlainObject(value.media_or_ad)) {
    if (hasAdUnion(value.media_or_ad) || isAdEntity(value.media_or_ad)) return true;
  }

  return false;
}

function pruneValue(value, stats) {
  if (Array.isArray(value)) {
    const next = [];
    for (const item of value) {
      const cleaned = pruneValue(item, stats);
      if (cleaned !== undefined) next.push(cleaned);
    }
    return next;
  }

  if (!isPlainObject(value)) return value;

  if (isAdEntity(value)) {
    stats.filtered += 1;
    return undefined;
  }

  for (const key of Object.keys(value)) {
    const child = value[key];

    if (AD_COLLECTION_KEYS.has(key) && Array.isArray(child) && child.length > 0) {
      stats.filtered += child.length;
      value[key] = [];
      stats.collections += 1;
      continue;
    }

    if (AD_METADATA_KEYS.has(key) && isTruthyValue(child)) {
      delete value[key];
      stats.deleted += 1;
      continue;
    }

    if (PRIMARY_WRAPPER_KEYS.has(key) && isAdEntity(child)) {
      stats.filtered += 1;
      return undefined;
    }

    const cleaned = pruneValue(child, stats);
    if (cleaned === undefined) {
      if (PRIMARY_WRAPPER_KEYS.has(key)) return undefined;
      delete value[key];
      stats.deleted += 1;
      continue;
    }

    value[key] = cleaned;
  }

  return value;
}

function cleanPayload(payload) {
  const stats = {
    deleted: 0,
    filtered: 0,
    collections: 0,
  };
  const cleaned = pruneValue(payload, stats);
  return {
    payload: cleaned === undefined ? {} : cleaned,
    stats,
  };
}

function doneUnchanged(reason) {
  debug(`unchanged: ${reason}`);
  $done({});
}

try {
  const endpoint = endpointFromUrl($request.url);
  if (!isSupportedEndpoint(endpoint)) {
    doneUnchanged("unsupported endpoint");
  } else {
    const text = bodyText($response.body);
    if (!text) {
      doneUnchanged("empty body");
    } else {
      const parsed = parseJsonBody(text);
      const result = cleanPayload(parsed.payload);
      const changed = result.stats.deleted + result.stats.filtered + result.stats.collections;
      debug(`${endpoint} deleted=${result.stats.deleted} filtered=${result.stats.filtered} collections=${result.stats.collections}`);
      if (!changed) $done({});
      else $done({ body: parsed.prefix + JSON.stringify(result.payload) });
    }
  }
} catch (error) {
  logbook(`error: ${error && error.message ? error.message : error}`);
  $done({});
}
