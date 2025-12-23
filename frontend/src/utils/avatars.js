import { AVATAR_BASE_PATH, AVATAR_BY_EMAIL } from '../constants/avatars.js';

export function resolveAvatar(email) {
  if (!email) return null;
  const key = String(email).trim().toLowerCase();
  const filename = AVATAR_BY_EMAIL[key];
  return filename ? `${AVATAR_BASE_PATH}${filename}` : null;
}
