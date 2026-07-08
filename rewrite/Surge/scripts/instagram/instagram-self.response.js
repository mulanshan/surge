/*
 * Self-written Instagram cleaner for Surge.
 *
 * Behavior:
 * - Keeps the cleanup conservative and schema-tolerant.
 * - Removes objects that clearly look like sponsored, promoted, or ad payloads
 *   from selected Instagram feed and discovery responses.
 * - Does not issue network requests, read cookies, upload data, or include
 *   third-party source code.
 */

const DEFAULTS = {
  debug: false,
};

const config = parseArgument();

const AD_LABEL_RE = /\b(sponsored|promoted|advertisement|branded content|paid partnership)\b/i;
const AD_KEY_RE = /(^|[_-])(ad|ads|advertiser|advertisement|promotion|promoted|sponsor|sponsored|branded_content|paid_partnership)([_-]|$)/i;
const AD_LABEL_FIELDS = [
  "type",
  "product_type",
  "content_type",
  "label",
  "title",
  "text",
  "subtitle",
  "headline",
  "message",
  "reason",
  "name",
  "category",
];
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

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
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
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return normalized === "true" || normalized === "1" || normalized === "yes";
  }
  return false;
}

function isTruthyValue(value) {
  if (value === null || value === undefined || value === false) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.length > 0;
  if (isPlainObject(value)) return Object.keys(value).length > 0;
  return Boolean(value);
}

function matchesAdLabel(value) {
  const joined = AD_LABEL_FIELDS.map((key) => textOf(value[key]).trim()).filter(Boolean).join(" ");
  return AD_LABEL_RE.test(joined);
}

function isAdKey(key) {
  const name = String(key || "").toLowerCase();
  if (!name || name === "media_or_ad") return false;
  return AD_KEY_RE.test(name);
}

function isAdEntity(value) {
  if (!isPlainObject(value)) return false;

  for (const field of DIRECT_FLAG_FIELDS) {
    if (isTruthyFlag(value[field])) return true;
  }

  for (const key of Object.keys(value)) {
    if (isAdKey(key) && isTruthyValue(value[key])) return true;
  }

  if (hasOwn(value, "ad_metadata") && isTruthyValue(value.ad_metadata)) return true;
  if (hasOwn(value, "ad_info") && isTruthyValue(value.ad_info)) return true;
  if (hasOwn(value, "ad_id") && isTruthyValue(value.ad_id)) return true;
  if (hasOwn(value, "advertiser_id") && isTruthyValue(value.advertiser_id)) return true;
  if (hasOwn(value, "sponsor_tags") && isTruthyValue(value.sponsor_tags)) return true;
  if (hasOwn(value, "media_or_ad") && isAdEntity(value.media_or_ad)) return true;

  return matchesAdLabel(value);
}

function pruneValue(value, stats) {
  if (Array.isArray(value)) {
    const next = [];
    for (const item of value) {
      const cleaned = pruneValue(item, stats);
      if (cleaned === undefined) continue;
      if (isAdEntity(cleaned)) {
        stats.filtered += 1;
        continue;
      }
      next.push(cleaned);
    }
    return next;
  }

  if (!isPlainObject(value)) return value;

  if (isAdEntity(value)) {
    stats.filtered += 1;
    return undefined;
  }

  for (const key of Object.keys(value)) {
    if (key === "media_or_ad" && isAdEntity(value[key])) {
      delete value[key];
      stats.deleted += 1;
      continue;
    }

    const child = value[key];
    if (isAdKey(key) && isTruthyValue(child)) {
      delete value[key];
      stats.deleted += 1;
      continue;
    }

    const cleaned = pruneValue(child, stats);
    if (cleaned === undefined) {
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
  };

  pruneValue(payload, stats);
  return stats;
}

function doneUnchanged(reason) {
  debug(`unchanged: ${reason}`);
  $done({});
}

try {
  const endpoint = endpointFromUrl($request.url);
  if (!/\/api\/v1\/(?:feed\/|discover\/)|\/graphql\/query\//.test(endpoint)) {
    doneUnchanged("not a feed/discover endpoint");
  } else {
    const text = bodyText($response.body);
    if (!text) doneUnchanged("empty body");
    else {
      const payload = JSON.parse(text);
      const stats = cleanPayload(payload);
      debug(`${endpoint} deleted=${stats.deleted} filtered=${stats.filtered}`);
      $done({ body: JSON.stringify(payload) });
    }
  }
} catch (error) {
  logbook(`error: ${error && error.message ? error.message : error}`);
  $done({});
}
