/*
 * Self-written WeChat official-account advertisement cleaner for Surge.
 *
 * Security boundaries:
 * - Only processes mp.weixin.qq.com/mp/getappmsgad JSON responses.
 * - Only changes the explicit root-level advertisement_num and
 *   advertisement_info fields.
 * - Does not issue network requests, read cookies or tokens, upload data,
 *   use eval, or include third-party source code.
 * - Leaves unknown endpoints, schemas and malformed bodies untouched.
 */

const DEFAULTS = {
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

function logbook(message) {
  const text = `[WeChat Self] ${message}`;
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

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function isSupportedRequest(request) {
  return /^https:\/\/mp\.weixin\.qq\.com\/mp\/getappmsgad(?:[?#]|$)/i.test(
    String(request && request.url ? request.url : ""),
  );
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function isAdvertisementCount(value) {
  if (typeof value === "number") return Number.isFinite(value) && value >= 0;
  return typeof value === "string" && /^\d+$/.test(value.trim());
}

function cleanAdvertisementPayload(payload) {
  const stats = {
    recognized: 0,
    resetCount: false,
    removedItems: 0,
  };

  if (!isPlainObject(payload)) return stats;

  if (hasOwn(payload, "advertisement_num") && isAdvertisementCount(payload.advertisement_num)) {
    stats.recognized += 1;
    if (Number(payload.advertisement_num) !== 0) {
      payload.advertisement_num = 0;
      stats.resetCount = true;
    }
  }

  if (hasOwn(payload, "advertisement_info") && Array.isArray(payload.advertisement_info)) {
    stats.recognized += 1;
    if (payload.advertisement_info.length > 0) {
      stats.removedItems = payload.advertisement_info.length;
      payload.advertisement_info = [];
    }
  }

  return stats;
}

if (!isSupportedRequest($request)) {
  $done({});
} else {
  const text = bodyText($response && $response.body);
  if (!text) {
    $done({});
  } else {
    try {
      const payload = JSON.parse(text);
      const stats = cleanAdvertisementPayload(payload);
      const changed = stats.resetCount || stats.removedItems > 0;

      if (!stats.recognized || !changed) {
        $done({});
      } else {
        debug(`cleaned advertisement fields; removed_items=${stats.removedItems}`);
        $done({ body: JSON.stringify(payload) });
      }
    } catch {
      $done({});
    }
  }
}
