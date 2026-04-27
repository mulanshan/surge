/*
 * Self-written YouTube cleaner for Surge — SAFE mode.
 *
 * Behavior:
 * - JSON responses (Web/desktop YouTube): conservative ad-field removal,
 *   plus optional player capability enhancement for picture-in-picture
 *   and background playback.
 * - Binary protobuf responses (iOS/Android YouTube App, YouTube Music App):
 *   PASS THROUGH UNCHANGED. The previous generic protobuf cleaner could
 *   corrupt wire-format messages and break normal playback, so we no
 *   longer modify protobuf payloads here.
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
  if (config.debug) console.log("[YouTube Self]", ...args);
}

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return match ? match[1] : "";
}

function bodyText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
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
  if (endpoint === "player") enhanceJsonPlayer(payload);
  walkJson(payload);
  return JSON.stringify(payload);
}

const endpoint = endpointFromUrl($request.url);
const originalBody = $response.body !== undefined ? $response.body : $response.bodyBytes;

try {
  const text = bodyText(originalBody);
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const output = cleanJson(text, endpoint);
    debug("json", endpoint, text.length, "->", output.length);
    $done({ body: output });
  } else {
    // Binary / protobuf — do NOT modify. Pass response through untouched.
    debug("protobuf-passthrough", endpoint);
    $done({});
  }
} catch (error) {
  debug("error", endpoint, error && error.message);
  // On any failure, never return a partial body — let the original through.
  $done({});
}
