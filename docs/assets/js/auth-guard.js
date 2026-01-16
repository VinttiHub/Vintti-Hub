/**
 * Simple auth gate for Hub pages.
 * - Ensures we have a stored email (login completed)
 * - Verifies the email belongs to a registered Hub user
 * - Redirects to index if verification fails
 */
(function guardHubAccess() {
  const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
  const CACHE_KEY = "vintti_hub_registration_cache";
  const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

  const pathname = (window.location.pathname || "").toLowerCase();
  if (pathname.endsWith("/index.html") || pathname === "/") {
    // These pages manage authentication themselves; skip guard.
    return;
  }

  const safeStorage = {
    get(storage, key) {
      try {
        return storage.getItem(key);
      } catch (err) {
        console.warn("[auth-guard] Unable to read storage", err);
        return null;
      }
    },
    set(storage, key, value) {
      try {
        storage.setItem(key, value);
      } catch (err) {
        console.warn("[auth-guard] Unable to write storage", err);
      }
    },
  };

  function getStoredEmail() {
    const sources = [window.localStorage, window.sessionStorage];
    for (const store of sources) {
      if (!store) continue;
      const raw = safeStorage.get(store, "user_email");
      if (raw) return raw.toLowerCase().trim();
    }
    return "";
  }

  function readCache() {
    const raw = safeStorage.get(window.localStorage, CACHE_KEY);
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function writeCache(cache) {
    safeStorage.set(window.localStorage, CACHE_KEY, JSON.stringify(cache || {}));
  }

  function getCachedEntry(email) {
    if (!email) return null;
    const cache = readCache();
    const entry = cache[email];
    if (!entry) return null;
    if (Date.now() - entry.ts > CACHE_TTL_MS) {
      delete cache[email];
      writeCache(cache);
      return null;
    }
    return entry;
  }

  function markRegistered(email) {
    if (!email) return;
    const cache = readCache();
    cache[email] = { ts: Date.now() };
    writeCache(cache);
  }

  function clearRegistration(email) {
    if (!email) return;
    const cache = readCache();
    if (cache[email]) {
      delete cache[email];
      writeCache(cache);
    }
  }

  function redirectToLogin(reason) {
    console.warn("[auth-guard] Redirecting to login:", reason);
    const redirectParam = encodeURIComponent(
      `${window.location.pathname}${window.location.search}${window.location.hash}`,
    );
    const target = `index.html?redirect=${redirectParam}`;
    window.location.replace(target);
  }

  async function ensureUserIsRegistered() {
    const email = getStoredEmail();
    if (!email) {
      redirectToLogin("missing-email");
      return;
    }

    const cached = getCachedEntry(email);
    if (cached) return;

    try {
      const response = await fetch(
        `${API_BASE}/users?email=${encodeURIComponent(email)}`,
        { credentials: "include" },
      );

      if (!response.ok) {
        throw new Error(`Unexpected status ${response.status}`);
      }

      const users = await response.json();
      if (Array.isArray(users) && users.length > 0) {
        markRegistered(email);
        return;
      }

      clearRegistration(email);
      redirectToLogin("not-registered");
    } catch (error) {
      console.error("[auth-guard] Unable to validate registration", error);
      clearRegistration(email);
      redirectToLogin("validation-error");
    }
  }

  ensureUserIsRegistered();
})();
