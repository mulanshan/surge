/*
 * Self-written Xiaohongshu response cleaner for Surge.
 *
 * Security boundaries:
 * - Only processes selected feed, search-result, note and splash JSON responses.
 * - Removes array entries only when they carry explicit advertisement fields.
 * - Does not issue network requests, read cookies or tokens, upload data, use
 *   eval, forge account state, or include third-party source code.
 */

const DEFAULTS = {
  cleanAds: true,
  debug: false,
};

const config = parseArgument();

function parseArgument() {
  try {
    const parsed = JSON.parse(typeof $argument === "string" ? $argument : "{}");
    if (!isPlainObject(parsed)) return { ...DEFAULTS };
    return {
      cleanAds: typeof parsed.cleanAds === "boolean" ? parsed.cleanAds : DEFAULTS.cleanAds,
      debug: parsed.debug === true,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function jsonText(body) {
  const text = bodyText(body);
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

function requestKind(url) {
  const text = String(url || "");
  if (text.includes("#")) return "";
  const match = text.match(
    /^https:\/\/(?:edith|rec|so|www)\.xiaohongshu\.com(\/api\/sns\/[^?]*)(?:\?|$)/i,
  );
  if (!match) return "";
  const endpoint = match[1];

  if (/\/v\d+\/homefeed$/i.test(endpoint)) return "feed";
  if (/\/v\d+\/(?:followfeed|user\/followings\/followfeed)$/i.test(endpoint)) return "feed";
  if (/\/v\d+\/search\/notes$/i.test(endpoint)) return "feed";
  if (/\/v\d+\/note\/(?:imagefeed|feed|videofeed)$/i.test(endpoint)) {
    return "note";
  }
  if (/\/v\d+\/system_service\/splash_config$/i.test(endpoint)) return "splash-config";
  return "";
}

function isSuccessfulResponse(response) {
  const status = response && response.status;
  return typeof status !== "number" || (status >= 200 && status < 300);
}

function trueFlag(value) {
  return value === true || value === 1 || value === "1";
}

function adType(value) {
  return typeof value === "string"
    && ["ad", "ads", "advert", "advertise", "advertisement"].includes(value.trim().toLowerCase());
}

function explicitAdvertisement(value) {
  if (!isPlainObject(value)) return false;
  for (const key of ["is_ad", "isAd", "is_ads", "isAds", "ad_flag", "adFlag"]) {
    if (hasOwn(value, key) && trueFlag(value[key])) return true;
  }
  for (const key of ["ads_info", "ad_info", "advertise_info", "advertisement_info"]) {
    if (!hasOwn(value, key)) continue;
    const marker = value[key];
    if (isPlainObject(marker) && Object.keys(marker).length > 0) return true;
    if (Array.isArray(marker) && marker.length > 0) return true;
    if (typeof marker === "string" && marker.trim() !== "") return true;
  }
  if (adType(value.model_type) || adType(value.card_type) || adType(value.type)) return true;
  if (isPlainObject(value.promotion) && adType(value.promotion.type)) return true;
  return false;
}

function advertisementEnvelope(value) {
  if (explicitAdvertisement(value)) return true;
  if (!isPlainObject(value)) return false;
  for (const key of ["data", "note", "card", "mblog"]) {
    if (explicitAdvertisement(value[key])) return true;
  }
  return false;
}

function cleanArray(value, stats) {
  if (!Array.isArray(value)) return value;
  const kept = value.filter((item) => !advertisementEnvelope(item));
  stats.removedAds += value.length - kept.length;
  return kept;
}

function cleanArrayAtPath(root, path, stats) {
  if (path.length === 0) return;
  const [step, ...rest] = path;
  if (step === "*") {
    if (!Array.isArray(root)) return;
    for (const item of root) cleanArrayAtPath(item, rest, stats);
    return;
  }

  if (!isPlainObject(root)) return;
  if (!hasOwn(root, step)) return;
  if (rest.length === 0) {
    root[step] = cleanArray(root[step], stats);
    return;
  }
  cleanArrayAtPath(root[step], rest, stats);
}

function cleanAdvertisementPaths(payload, kind, stats) {
  const paths = kind === "feed"
    ? [["data"], ["data", "items"]]
    : [["data"], ["data", "note_list"], ["data", "*", "note_list"]];

  for (const path of paths) cleanArrayAtPath(payload, path, stats);
}

function cleanSplashGroups(payload, stats) {
  const data = payload.data;
  if (!isPlainObject(data)) return;
  if (!Array.isArray(data.ads_groups)) return;
  const kept = data.ads_groups.filter((item) => !advertisementEnvelope(item));
  stats.removedAds += data.ads_groups.length - kept.length;
  data.ads_groups = kept;
}

function logbook(message) {
  const text = `[Xiaohongshu Self] ${message}`;
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

function processResponse() {
  const kind = requestKind($request && $request.url);
  if (!kind) return {};
  if (!isSuccessfulResponse($response)) {
    debug(`pass-through kind=${kind}; reason=non-success`);
    return {};
  }

  const text = jsonText($response && $response.body);
  if (!text) {
    debug(`pass-through kind=${kind}; reason=empty-body`);
    return {};
  }

  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    debug(`pass-through kind=${kind}; reason=invalid-json`);
    return {};
  }
  if (!isPlainObject(payload)) {
    debug(`pass-through kind=${kind}; reason=unsupported-root`);
    return {};
  }

  const stats = {
    removedAds: 0,
  };

  if (config.cleanAds && kind === "splash-config") cleanSplashGroups(payload, stats);
  if (config.cleanAds && ["feed", "note"].includes(kind)) {
    cleanAdvertisementPaths(payload, kind, stats);
  }

  const changed = stats.removedAds > 0;
  if (!changed) {
    debug(`pass-through kind=${kind}; reason=no-change`);
    return {};
  }

  debug(`cleaned kind=${kind}; removed_ads=${stats.removedAds}`);
  return { body: JSON.stringify(payload) };
}

$done(processResponse());
