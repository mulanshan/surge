/*
 * Self-written WeChat official-account advertisement cleaner for Surge.
 *
 * Security boundaries:
 * - Only processes whitelisted mp.weixin.qq.com/mp/* JSON responses:
 *   getappmsgad, getappmsgext, cps_product_info, masonryfeed, relatedarticle.
 * - Preserves article stats (read/like counts), albums, rewards, comments,
 *   and base_resp envelopes; leaves unknown schemas and error responses untouched.
 * - Honors explicit user switches (cleanAds, hideBottomFeed, debug).
 * - Does not issue network requests, read cookies or tokens, upload data,
 *   use eval, or include third-party source code.
 */

const DEFAULTS = {
  cleanAds: true,
  hideBottomFeed: false,
  debug: false,
};

const ARTICLE_AD_ARRAY_KEYS = [
  "advertisement_info",
  "promotion_info",
  "cps_ad_info",
  "drama_advertisement_info",
];

const CPS_ARRAY_KEYS = [
  "product_list",
  "goods_list",
  "cps_list",
  "item_list",
  "card_list",
  "appmsg_cps_list",
];

const CPS_OBJECT_KEYS = [
  "product_info",
  "cps_info",
  "goods_info",
  "product",
  "card_info",
  "appmsg_cps_info",
];

const CPS_COUNT_KEYS = ["total_count", "count", "product_num", "goods_num"];

const BOTTOM_FEED_ARRAY_KEYS = [
  "list",
  "article_list",
  "related_article_list",
  "related_article",
  "feed_list",
  "items",
  "recommend_list",
];

const BOTTOM_FEED_FLAG_KEYS = [
  "continue_flag",
  "is_continue",
  "has_more",
  "can_load_more",
];

const BOTTOM_FEED_COUNT_KEYS = ["total_count", "count", "article_count"];

const config = parseArgument();

function parseArgument() {
  try {
    const parsed = JSON.parse(typeof $argument === "string" ? $argument : "{}");
    if (!isPlainObject(parsed)) return { ...DEFAULTS };
    return {
      cleanAds: typeof parsed.cleanAds === "boolean" ? parsed.cleanAds : DEFAULTS.cleanAds,
      hideBottomFeed: parsed.hideBottomFeed === true,
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

function classifyEndpoint(request) {
  const url = String(request && request.url ? request.url : "");
  if (!url || url.includes("#")) return "";
  const match = url.match(
    /^https:\/\/mp\.weixin\.qq\.com\/mp\/(getappmsgad|getappmsgext|cps_product_info|masonryfeed|relatedarticle)(?:\?[^#]*)?$/i,
  );
  return match ? match[1].toLowerCase() : "";
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

function isNonNegativeCount(value) {
  if (typeof value === "number") return Number.isSafeInteger(value) && value >= 0;
  if (typeof value !== "string" || !/^\d+$/.test(value.trim())) return false;
  return Number.isSafeInteger(Number(value.trim()));
}

function zeroOfSameType(value) {
  return typeof value === "string" ? "0" : 0;
}

function isBackendErrorEnvelope(payload) {
  if (!hasOwn(payload, "base_resp")) return false;
  if (!isPlainObject(payload.base_resp)) return true;
  if (!hasOwn(payload.base_resp, "ret")) return false;
  const ret = payload.base_resp.ret;
  if (typeof ret === "number") return ret !== 0;
  if (typeof ret === "string" && /^-?\d+$/.test(ret.trim())) return Number(ret.trim()) !== 0;
  return true;
}

function resetTruthyFlag(obj, key) {
  if (!hasOwn(obj, key)) return false;
  const val = obj[key];
  if (val === true) {
    obj[key] = false;
    return true;
  }
  if (typeof val === "number" && Number.isSafeInteger(val) && val > 0) {
    obj[key] = 0;
    return true;
  }
  if (typeof val === "string" && /^\d+$/.test(val.trim()) && Number(val.trim()) > 0) {
    obj[key] = "0";
    return true;
  }
  return false;
}

function cleanArticleAdPayload(payload) {
  const stats = {
    recognized: 0,
    validSchema: false,
    resetCount: false,
    removedItems: 0,
  };

  if (!isPlainObject(payload) || isBackendErrorEnvelope(payload)) return stats;

  const hasCount = hasOwn(payload, "advertisement_num");
  const presentArrays = ARTICLE_AD_ARRAY_KEYS.filter((key) => hasOwn(payload, key));
  stats.recognized = Number(hasCount) + presentArrays.length;
  if (!stats.recognized) return stats;

  const validCount = !hasCount || isNonNegativeCount(payload.advertisement_num);
  const validArrays = presentArrays.every((key) => {
    const val = payload[key];
    if (key === "advertisement_info") return Array.isArray(val);
    return Array.isArray(val) || val === null;
  });
  if (!validCount || !validArrays) return stats;
  stats.validSchema = true;

  if (hasCount && Number(payload.advertisement_num) !== 0) {
    payload.advertisement_num = zeroOfSameType(payload.advertisement_num);
    stats.resetCount = true;
  }

  for (const key of presentArrays) {
    if (Array.isArray(payload[key]) && payload[key].length > 0) {
      stats.removedItems += payload[key].length;
      payload[key] = [];
    }
  }

  return stats;
}

function cleanCpsProductPayload(payload) {
  const stats = {
    recognized: 0,
    validSchema: false,
    resetCount: false,
    removedItems: 0,
  };

  if (!isPlainObject(payload) || isBackendErrorEnvelope(payload)) return stats;

  for (const key of CPS_ARRAY_KEYS) {
    if (hasOwn(payload, key) && !Array.isArray(payload[key]) && payload[key] !== null) {
      stats.recognized = 1;
      return stats;
    }
  }
  for (const key of CPS_COUNT_KEYS) {
    if (hasOwn(payload, key) && !isNonNegativeCount(payload[key])) {
      stats.recognized = 1;
      return stats;
    }
  }

  stats.recognized = 1;
  stats.validSchema = true;

  if (!hasOwn(payload, "base_resp")) {
    payload.base_resp = { ret: 0 };
    stats.resetCount = true;
  }

  for (const key of CPS_ARRAY_KEYS) {
    if (Array.isArray(payload[key]) && payload[key].length > 0) {
      stats.removedItems += payload[key].length;
      payload[key] = [];
    }
  }

  for (const key of CPS_OBJECT_KEYS) {
    if (hasOwn(payload, key) && payload[key] !== null) {
      delete payload[key];
      stats.removedItems += 1;
    }
  }

  for (const key of CPS_COUNT_KEYS) {
    if (hasOwn(payload, key) && Number(payload[key]) !== 0) {
      payload[key] = zeroOfSameType(payload[key]);
      stats.resetCount = true;
    }
  }

  return stats;
}

function cleanBottomFeedPayload(payload) {
  const stats = {
    recognized: 0,
    validSchema: false,
    resetCount: false,
    removedItems: 0,
  };

  if (!isPlainObject(payload) || isBackendErrorEnvelope(payload)) return stats;

  const presentArrays = BOTTOM_FEED_ARRAY_KEYS.filter((key) => hasOwn(payload, key));
  stats.recognized = presentArrays.length;
  if (!stats.recognized) return stats;

  if (!presentArrays.every((key) => Array.isArray(payload[key]))) {
    return stats;
  }
  for (const key of BOTTOM_FEED_COUNT_KEYS) {
    if (hasOwn(payload, key) && !isNonNegativeCount(payload[key])) {
      return stats;
    }
  }
  stats.validSchema = true;

  for (const key of presentArrays) {
    if (payload[key].length > 0) {
      stats.removedItems += payload[key].length;
      payload[key] = [];
    }
  }

  for (const key of BOTTOM_FEED_FLAG_KEYS) {
    if (resetTruthyFlag(payload, key)) {
      stats.resetCount = true;
    }
  }

  for (const key of BOTTOM_FEED_COUNT_KEYS) {
    if (hasOwn(payload, key) && Number(payload[key]) !== 0) {
      payload[key] = zeroOfSameType(payload[key]);
      stats.resetCount = true;
    }
  }

  return stats;
}

const endpoint = classifyEndpoint($request);

if (!endpoint) {
  $done({});
} else if (
  (endpoint === "getappmsgad" || endpoint === "getappmsgext" || endpoint === "cps_product_info") &&
  !config.cleanAds
) {
  debug(`pass-through: cleanAds disabled on ${endpoint}`);
  $done({});
} else if (
  (endpoint === "masonryfeed" || endpoint === "relatedarticle") &&
  !config.hideBottomFeed
) {
  debug(`pass-through: hideBottomFeed disabled on ${endpoint}`);
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
      let stats;
      if (endpoint === "cps_product_info") {
        stats = cleanCpsProductPayload(payload);
      } else if (endpoint === "masonryfeed" || endpoint === "relatedarticle") {
        stats = cleanBottomFeedPayload(payload);
      } else {
        stats = cleanArticleAdPayload(payload);
      }
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
          `cleaned ${endpoint}; reset_count=${stats.resetCount ? 1 : 0}; removed_items=${stats.removedItems}`,
        );
        $done({ body: JSON.stringify(payload) });
      }
    } catch {
      debug("pass-through: invalid JSON");
      $done({});
    }
  }
}
