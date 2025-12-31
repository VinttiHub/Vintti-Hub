// Shared avatar configuration for non-React pages.
// Map emails or user_ids to filenames inside docs/assets/img/.
(function(global){
  const root = global || window;
  if (root.__VINTTI_AVATAR_MAP__) return;

  const AVATAR_BASE = './assets/img/';
  const AVATAR_BY_EMAIL = {
    'agostina@vintti.com':         'agos.png',
    'bahia@vintti.com':            'bahia.png',
    'lara@vintti.com':             'lara.png',
    'jazmin@vintti.com':           'jaz.png',
    'pilar@vintti.com':            'pilar.png',
    'pilar.fernandez@vintti.com':  'pilar_fer.png',
    'agustin@vintti.com':          'agus.png',
    'agustina.barbero@vintti.com': 'agustina.png',
    'josefina@vintti.com':         'josefina.png',
    'constanza@vintti.com':        'constanza.png',
    'mariano@vintti.com':          'mariano.png',
    'julieta@vintti.com':          'julieta.png',
    'felicitas@vintti.com':        'felicitas.png',
    'pgonzales@vintti.com':        'pri.png',
    'mora@vintti.com':             'mora.png',
    'mia@vintti.com':              'mia_cavanagh.png',
    'luisa@vintti.com':            'luisa.png',
    'camila@vintti.com':           'camila.png',
    'felipe@vintti.com':           'felipe.png',
    'abril@vintti.com':            'abril.png',
    'angie@vintti.com':            'angie.png',
  };
  const AVATAR_BY_USER_ID = {
    // '123': 'avatar.png',
    // 456: 'avatar.png'
  };

  function resolveAvatar(email){
    if (!email) return null;
    const key = String(email).trim().toLowerCase();
    const filename = AVATAR_BY_EMAIL[key];
    return filename ? (AVATAR_BASE + filename) : null;
  }

  function resolveAvatarByUserId(userId){
    if (userId === undefined || userId === null) return null;
    const key = String(userId).trim();
    if (!key) return null;
    const filename = AVATAR_BY_USER_ID[key];
    return filename ? (AVATAR_BASE + filename) : null;
  }

  function resolveUserAvatar({ avatar_url, email_vintti, email, user_id } = {}){
    const direct = typeof avatar_url === 'string' ? avatar_url.trim() : '';
    if (direct) return direct;

    const normalizedEmail = String(email_vintti || email || '').trim().toLowerCase();
    if (normalizedEmail){
      const mapped = resolveAvatar(normalizedEmail);
      if (mapped) return mapped;
    }

    const byId = resolveAvatarByUserId(user_id);
    if (byId) return byId;

    const cached = typeof localStorage !== 'undefined'
      ? localStorage.getItem('user_avatar')
      : null;
    return cached || '';
  }

  root.AVATAR_BASE = AVATAR_BASE;
  root.AVATAR_BY_EMAIL = AVATAR_BY_EMAIL;
  root.AVATAR_BY_USER_ID = AVATAR_BY_USER_ID;
  root.resolveAvatar = resolveAvatar;
  root.resolveAvatarByUserId = resolveAvatarByUserId;
  root.resolveUserAvatar = resolveUserAvatar;
  root.__VINTTI_AVATAR_MAP__ = true;
})(typeof window !== 'undefined' ? window : this);
