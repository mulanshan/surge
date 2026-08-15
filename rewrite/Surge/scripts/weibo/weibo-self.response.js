/*
 * Self-written Weibo response cleaner for Surge.
 *
 * Security boundaries:
 * - Only processes selected feed, search, detail and comment JSON APIs.
 * - Removes array entries only when they carry explicit advertisement fields.
 * - Does not forge membership, skins, icons, balances, account state or access.
 * - Does not issue network requests, read cookies or tokens, upload data, use
 *   eval, or include third-party source code.
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
    /^https:\/\/(?:api\.weibo\.cn|mapi\.weibo\.(?:cn|com))(\/2\/[^?]*)(?:\?|$)/i,
  );
  if (!match) return "";
  const endpoint = match[1];

  const commentPatterns = [
    /^\/2\/comments\/(?:build_comments|mix_comments)$/i,
    /^\/2\/statuses\/container_detail(?:_comment|_mix|_forward)?$/i,
  ];
  if (commentPatterns.some((pattern) => pattern.test(endpoint))) return "comment";

  const feedPatterns = [
    /^\/2\/(?:cardlist|page|flowlist|flowpage|container\/asyn|searchall)$/i,
    /^\/2\/groups\/timeline$/i,
    /^\/2\/search\/(?:finder|container_timeline|container_discover)$/i,
    /^\/2\/statuses\/(?:container_timeline(?:_hot|_topic|_topicpage|_unread)?|extend|show|repost_timeline|unread_hot_timeline|unread_friends_timeline|friends_timeline)$/i,
    /^\/2\/video\/(?:community_tab|full_screen_stream|remind_info|tiny_stream_mid_detail|tiny_stream_video_list)$/i,
  ];
  if (feedPatterns.some((pattern) => pattern.test(endpoint))) return "feed";

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

function exactAdvertisementLabel(value) {
  return typeof value === "string" && value.trim() === "广告";
}

function explicitAdvertisement(value) {
  if (!isPlainObject(value)) return false;

  for (const key of ["is_ad", "isAd", "is_ads", "isAds", "ad_state", "adFlag", "ad_flag"]) {
    if (hasOwn(value, key) && trueFlag(value[key])) return true;
  }
  if (adType(value.type) || adType(value.category) || adType(value.ad_type) || adType(value.adType)) {
    return true;
  }
  if (isPlainObject(value.promotion) && adType(value.promotion.type)) return true;
  if (isPlainObject(value.ads_material_info) && trueFlag(value.ads_material_info.is_ads)) return true;
  if (exactAdvertisementLabel(value.mblogtypename)) return true;
  if (
    isPlainObject(value.content_auth_info)
    && exactAdvertisementLabel(value.content_auth_info.content_auth_title)
  ) return true;
  return false;
}

function advertisementEnvelope(value) {
  if (explicitAdvertisement(value)) return true;
  if (!isPlainObject(value)) return false;

  for (const key of ["data", "mblog", "card", "status", "comment"]) {
    const child = value[key];
    if (explicitAdvertisement(child)) return true;
    if (isPlainObject(child) && explicitAdvertisement(child.mblog)) return true;
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

function clearRootAdContainers(payload, stats) {
  for (const key of ["ad", "ads", "advertises"]) {
    if (!hasOwn(payload, key)) continue;
    const value = payload[key];
    if (Array.isArray(value) && value.length > 0) {
      stats.removedAds += value.length;
      payload[key] = [];
    } else if (isPlainObject(value) && Object.keys(value).length > 0) {
      stats.removedAds += 1;
      payload[key] = {};
    }
  }
}

function cleanAdvertisementPaths(payload, kind, stats) {
  const feedPaths = [
    ["items"],
    ["statuses"],
    ["cards"],
    ["data", "items"],
    ["data", "statuses"],
    ["data", "cards"],
    ["cards", "*", "card_group"],
    ["data", "cards", "*", "card_group"],
  ];
  const commentPaths = [
    ["root_comments"],
    ["comments"],
    ["data", "root_comments"],
    ["data", "comments"],
  ];
  const paths = kind === "comment" ? commentPaths : feedPaths;
  for (const path of paths) cleanArrayAtPath(payload, path, stats);
}

function logbook(message) {
  const text = `[Weibo Self] ${message}`;
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
    debug("pass-through reason=non-success");
    return {};
  }
  if (!config.cleanAds) return {};

  const text = jsonText($response && $response.body);
  if (!text) {
    debug("pass-through reason=empty-body");
    return {};
  }

  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    debug("pass-through reason=invalid-json");
    return {};
  }
  if (!isPlainObject(payload)) {
    debug("pass-through reason=unsupported-root");
    return {};
  }

  const stats = { removedAds: 0 };
  clearRootAdContainers(payload, stats);
  cleanAdvertisementPaths(payload, kind, stats);
  if (stats.removedAds === 0) {
    debug("pass-through reason=no-change");
    return {};
  }

  debug(`cleaned removed_ads=${stats.removedAds}`);
  return { body: JSON.stringify(payload) };
}

$done(processResponse());
