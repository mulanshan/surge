/*
 * Self-written WeChat official-account advertisement cleaner for Surge.
 *
 * Security boundaries:
 * - Only processes mp.weixin.qq.com/mp/getappmsgad JSON responses.
 * - Only changes successful responses whose explicit root-level
 *   advertisement_num and advertisement_info fields pass validation together.
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
    const parsed = JSON.parse(typeof $argument === "string" ? $argument : "{}");
    if (!isPlainObject(parsed)) return { ...DEFAULTS };
    return {
      debug: parsed.debug === true,
    };
  } catch {
    return { ...DEFAULTS };
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

function jsonText(body) {
  const text = bodyText(body);
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

function isSupportedRequest(request) {
  return /^https:\/\/mp\.weixin\.qq\.com\/mp\/getappmsgad(?:\?|$)/i.test(
    String(request && request.url ? request.url : ""),
  );
}

function isSuccessfulResponse(response) {
  const status = response && response.status;
  return typeof status !== "number" || (status >= 200 && status < 300);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function isAdvertisementCount(value) {
  if (typeof value === "number") return Number.isSafeInteger(value) && value >= 0;
  if (typeof value !== "string" || !/^\d+$/.test(value.trim())) return false;
  return Number.isSafeInteger(Number(value.trim()));
}

function zeroOfSameType(value) {
  return typeof value === "string" ? "0" : 0;
}

function cleanAdvertisementPayload(payload) {
  const stats = {
    recognized: 0,
    validSchema: false,
    resetCount: false,
    removedItems: 0,
  };

  if (!isPlainObject(payload)) return stats;

  const hasCount = hasOwn(payload, "advertisement_num");
  const hasInfo = hasOwn(payload, "advertisement_info");
  stats.recognized = Number(hasCount) + Number(hasInfo);
  if (!stats.recognized) return stats;

  const validCount = !hasCount || isAdvertisementCount(payload.advertisement_num);
  const validInfo = !hasInfo || Array.isArray(payload.advertisement_info);
  if (!validCount || !validInfo) return stats;
  stats.validSchema = true;

  if (hasCount) {
    if (Number(payload.advertisement_num) !== 0) {
      payload.advertisement_num = zeroOfSameType(payload.advertisement_num);
      stats.resetCount = true;
    }
  }

  if (hasInfo) {
    if (payload.advertisement_info.length > 0) {
      stats.removedItems = payload.advertisement_info.length;
      payload.advertisement_info = [];
    }
  }

  return stats;
}

if (!isSupportedRequest($request)) {
  $done({});
} else if (!isSuccessfulResponse($response)) {
  debug("pass-through: non-success response");
  $done({});
} else {
  const text = jsonText($response && $response.body);
  if (!text) {
    debug("pass-through: empty body");
    $done({});
  } else {
    try {
      const payload = JSON.parse(text);
      const stats = cleanAdvertisementPayload(payload);
      const changed = stats.resetCount || stats.removedItems > 0;

      if (!stats.recognized) {
        debug("pass-through: unrecognized schema");
        $done({});
      } else if (!stats.validSchema) {
        debug("pass-through: invalid advertisement schema");
        $done({});
      } else if (!changed) {
        debug("pass-through: no ad changes");
        $done({});
      } else {
        debug(
          `cleaned advertisement fields; reset_count=${stats.resetCount ? 1 : 0}; removed_items=${stats.removedItems}`,
        );
        $done({ body: JSON.stringify(payload) });
      }
    } catch {
      debug("pass-through: invalid JSON");
      $done({});
    }
  }
}
