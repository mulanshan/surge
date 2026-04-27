/*
 * Self-written YouTube response cleaner for Surge.
 *
 * Scope:
 * - Handles JSON youtubei responses, such as YouTube Web.
 * - Does not parse protobuf. iOS/YouTube Music app protobuf support requires
 *   captured binary samples and a maintained schema.
 */

const DEFAULTS = {
  captionLang: "off",
  lyricLang: "off",
  blockUpload: true,
  blockImmersive: true,
  blockShorts: false,
  debug: false,
};

function parseArgument() {
  try {
    return Object.assign({}, DEFAULTS, JSON.parse($argument || "{}"));
  } catch {
    return DEFAULTS;
  }
}

function log(...args) {
  if (config.debug) console.log("[YouTube Readable]", ...args);
}

function bodyToText(body) {
  if (typeof body === "string") return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));
  return "";
}

function textToBody(text, originalBody) {
  if (originalBody instanceof Uint8Array || originalBody instanceof ArrayBuffer) {
    return new TextEncoder().encode(text);
  }
  return text;
}

function endpointFromUrl(url) {
  const match = String(url || "").match(/\/youtubei\/v1\/([^?]+)/);
  return match ? match[1] : "";
}

function hasAnyKey(object, names) {
  return names.some((name) => Object.prototype.hasOwnProperty.call(object, name));
}

function isAdLikeObject(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (
    hasAnyKey(value, [
      "adSlotRenderer",
      "displayAdRenderer",
      "promotedSparklesWebRenderer",
      "promotedVideoRenderer",
      "searchPyvRenderer",
      "inFeedAdLayoutRenderer",
      "carouselAdRenderer",
      "playerLegacyDesktopYpcOfferRenderer",
    ])
  ) {
    return true;
  }

  const json = JSON.stringify(value).toLowerCase();
  return (
    json.includes('"simpleadbadge"') ||
    json.includes('"adbadge"') ||
    json.includes('"promoted"') ||
    json.includes('"pagead"')
  );
}

function isBlockedGuideItem(value) {
  if (!value || typeof value !== "object") return false;
  const json = JSON.stringify(value);
  if (config.blockUpload && json.includes("FEuploads")) return true;
  if (config.blockImmersive && json.includes("FEmusic_immersive")) return true;
  if (config.blockShorts && json.includes("FEshorts")) return true;
  return false;
}

function walkAndClean(value) {
  if (!value || typeof value !== "object") return value;

  if (Array.isArray(value)) {
    for (let index = value.length - 1; index >= 0; index -= 1) {
      const item = value[index];
      if (isAdLikeObject(item) || isBlockedGuideItem(item)) {
        value.splice(index, 1);
      } else {
        walkAndClean(item);
      }
    }
    return value;
  }

  for (const key of Object.keys(value)) {
    if (
      key === "adPlacements" ||
      key === "adSlots" ||
      key === "playerAds" ||
      key === "adBreakHeartbeatParams"
    ) {
      delete value[key];
      continue;
    }
    if (key === "pageadViewthroughconversion") {
      delete value[key];
      continue;
    }
    walkAndClean(value[key]);
  }
  return value;
}

function enhancePlayer(payload) {
  delete payload.adPlacements;
  delete payload.adSlots;
  delete payload.playerAds;
  delete payload.adBreakHeartbeatParams;

  if (payload.playbackTracking) {
    delete payload.playbackTracking.pageadViewthroughconversion;
  }

  payload.playabilityStatus = payload.playabilityStatus || {};
  payload.playabilityStatus.pictureInPictureRender = {
    pictureInPictureAbility: { active: true, f4: 0, f6: 0, f8: 1 },
  };
  payload.playabilityStatus.backgroundPlayerRender = {
    backgroundAbility: { active: true },
  };

  addTranslatedCaptionTrack(payload);
}

function addTranslatedCaptionTrack(payload) {
  const lang = String(config.captionLang || "off").trim();
  if (lang === "off") return;

  const captions = payload.captions?.playerCaptionsTracklistRenderer;
  const tracks = captions?.captionTracks;
  if (!Array.isArray(tracks) || tracks.length === 0) return;

  for (const track of tracks) {
    track.isTranslatable = true;
  }

  if (tracks.some((track) => track.languageCode === lang)) return;
  const base = tracks.find((track) => track.languageCode === "en") || tracks[0];
  if (!base?.baseUrl) return;

  tracks.push({
    ...base,
    baseUrl: `${base.baseUrl}&tlang=${encodeURIComponent(lang)}`,
    languageCode: lang,
    vssId: `.${lang}`,
    name: { simpleText: `@Readable (${lang})` },
  });
}

const config = parseArgument();
const originalBody = $response.bodyBytes || $response.body;
const text = bodyToText(originalBody);

try {
  const endpoint = endpointFromUrl($request.url);
  const payload = JSON.parse(text);

  if (endpoint === "player") enhancePlayer(payload);
  walkAndClean(payload);

  const output = JSON.stringify(payload);
  log("processed", endpoint, text.length, output.length);
  $done({ body: textToBody(output, originalBody) });
} catch (error) {
  log("skip", error.message);
  $done({});
}
