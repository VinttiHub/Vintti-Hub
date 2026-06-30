import { AVATAR_BASE_PATH, AVATAR_BY_EMAIL } from '../constants/avatars.js';

const AVATAR_CACHE_KEY = 'user_avatar_directory_v1';

function safeStorage() {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readAvatarDirectory() {
  const storage = safeStorage();
  if (!storage) return { byEmail: {}, byUserId: {} };
  try {
    const raw = storage.getItem(AVATAR_CACHE_KEY);
    if (!raw) return { byEmail: {}, byUserId: {} };
    const parsed = JSON.parse(raw);
    return {
      byEmail: parsed?.byEmail && typeof parsed.byEmail === 'object' ? parsed.byEmail : {},
      byUserId: parsed?.byUserId && typeof parsed.byUserId === 'object' ? parsed.byUserId : {},
    };
  } catch {
    return { byEmail: {}, byUserId: {} };
  }
}

function writeAvatarDirectory(directory) {
  const storage = safeStorage();
  if (!storage) return;
  storage.setItem(AVATAR_CACHE_KEY, JSON.stringify({
    byEmail: directory?.byEmail || {},
    byUserId: directory?.byUserId || {},
  }));
}

function normalizeUrl(value) {
  return typeof value === 'string' ? value.trim() : '';
}

export function resolveAvatar(email) {
  if (!email) return null;
  const key = String(email).trim().toLowerCase();
  const cached = readAvatarDirectory().byEmail[key];
  if (cached) return cached;
  const filename = AVATAR_BY_EMAIL[key];
  return filename ? `${AVATAR_BASE_PATH}${filename}` : null;
}

export function rememberUserAvatar({ email, userId, avatarUrl } = {}) {
  const trimmedUrl = normalizeUrl(avatarUrl);
  const normalizedEmail = String(email || '').trim().toLowerCase();
  const normalizedUserId = userId == null ? '' : String(userId).trim();
  if (!trimmedUrl && !normalizedEmail && !normalizedUserId) return;

  const directory = readAvatarDirectory();
  if (normalizedEmail) {
    if (trimmedUrl) directory.byEmail[normalizedEmail] = trimmedUrl;
    else delete directory.byEmail[normalizedEmail];
  }
  if (normalizedUserId) {
    if (trimmedUrl) directory.byUserId[normalizedUserId] = trimmedUrl;
    else delete directory.byUserId[normalizedUserId];
  }
  writeAvatarDirectory(directory);

  const storage = safeStorage();
  if (!storage) return;
  const currentEmail = String(storage.getItem('user_email') || '').trim().toLowerCase();
  if (normalizedEmail && normalizedEmail === currentEmail) {
    if (trimmedUrl) storage.setItem('user_avatar', trimmedUrl);
    else storage.removeItem('user_avatar');
  }
}

export function resolveUserAvatar({ avatarUrl, email, userId } = {}) {
  const direct = normalizeUrl(avatarUrl);
  if (direct) return direct;

  const normalizedEmail = String(email || '').trim().toLowerCase();
  const normalizedUserId = userId == null ? '' : String(userId).trim();
  const directory = readAvatarDirectory();

  if (normalizedEmail && directory.byEmail[normalizedEmail]) {
    return directory.byEmail[normalizedEmail];
  }
  if (normalizedUserId && directory.byUserId[normalizedUserId]) {
    return directory.byUserId[normalizedUserId];
  }

  if (normalizedEmail) {
    const filename = AVATAR_BY_EMAIL[normalizedEmail];
    if (filename) return `${AVATAR_BASE_PATH}${filename}`;
  }

  const storage = safeStorage();
  if (!storage) return null;
  const currentEmail = String(storage.getItem('user_email') || '').trim().toLowerCase();
  const cachedAvatar = normalizeUrl(storage.getItem('user_avatar'));
  if (cachedAvatar && (!normalizedEmail || normalizedEmail === currentEmail)) {
    return cachedAvatar;
  }
  return null;
}
