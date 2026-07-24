// Shared avatar configuration for non-React pages.
// Map emails or user_ids to filenames inside docs/assets/img/.
(function(global){
  const root = global || window;
  if (root.__VINTTI_AVATAR_MAP__) return;

  const AVATAR_BASE = './assets/img/';
  const AVATAR_DIRECTORY_KEY = 'user_avatar_directory_v1';
  const AVATAR_BY_EMAIL = {
    'agostina@vintti.com':         'agos.png',
    'bahia@vintti.com':            'bahia.png',
    'lara@vintti.com':             'lara.png',
    'jazmin@vintti.com':           'jaz.png',
    'pilar@vintti.com':            'pilar.png',
    'agustin@vintti.com':          'agus.png',
    'agustina@vintti.com':         'agusvalentini.png',
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
    'juliana@vintti.com':          'juliana.png',
    'paz@vintti.com':              'paz.png',
    'vianney@vintti.com':          'vianney.png',
    'valentina@vintti.com':        'valentina.png',
    'sofia@vintti.com':            'sofia.png',
    'magali@vintti.com':           'magali.png',
    'manuela@vintti.com':          'manuela.png',
    'pilaraiassa@vintti.com':      'piliaissa.png',
    'valeria@vintti.com':          'valeria.png',
    'ana@vintti.com':              'ana.png',
    'lucia@vintti.com':            'lufrey.png',
    'justo@vintti.com':            'justo.png'
  };
  const AVATAR_BY_USER_ID = {
    // '123': 'avatar.png',
    // 456: 'avatar.png'
  };

  function readAvatarDirectory(){
    try{
      const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(AVATAR_DIRECTORY_KEY) : '';
      if (!raw) return { byEmail:{}, byUserId:{} };
      const parsed = JSON.parse(raw);
      return {
        byEmail: parsed?.byEmail && typeof parsed.byEmail === 'object' ? parsed.byEmail : {},
        byUserId: parsed?.byUserId && typeof parsed.byUserId === 'object' ? parsed.byUserId : {},
      };
    }catch{
      return { byEmail:{}, byUserId:{} };
    }
  }

  function writeAvatarDirectory(directory){
    try{
      if (typeof localStorage === 'undefined') return;
      localStorage.setItem(AVATAR_DIRECTORY_KEY, JSON.stringify({
        byEmail: directory?.byEmail || {},
        byUserId: directory?.byUserId || {},
      }));
    }catch{}
  }

  function rememberUserAvatar({ avatar_url, email_vintti, email, user_id } = {}){
    const direct = typeof avatar_url === 'string' ? avatar_url.trim() : '';
    const normalizedEmail = String(email_vintti || email || '').trim().toLowerCase();
    const normalizedUserId = user_id === undefined || user_id === null ? '' : String(user_id).trim();
    if (!direct && !normalizedEmail && !normalizedUserId) return;

    const directory = readAvatarDirectory();
    if (normalizedEmail){
      if (direct) directory.byEmail[normalizedEmail] = direct;
      else delete directory.byEmail[normalizedEmail];
    }
    if (normalizedUserId){
      if (direct) directory.byUserId[normalizedUserId] = direct;
      else delete directory.byUserId[normalizedUserId];
    }
    writeAvatarDirectory(directory);

    try{
      const currentEmail = String(localStorage.getItem('user_email') || '').trim().toLowerCase();
      if (normalizedEmail && normalizedEmail === currentEmail){
        if (direct) localStorage.setItem('user_avatar', direct);
        else localStorage.removeItem('user_avatar');
      }
    }catch{}
  }

  function resolveAvatar(email){
    if (!email) return null;
    const key = String(email).trim().toLowerCase();
    const cached = readAvatarDirectory().byEmail[key];
    if (cached) return cached;
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

    const directory = readAvatarDirectory();
    const normalizedEmail = String(email_vintti || email || '').trim().toLowerCase();
    if (normalizedEmail){
      if (directory.byEmail[normalizedEmail]) return directory.byEmail[normalizedEmail];
      const mapped = resolveAvatar(normalizedEmail);
      if (mapped) return mapped;
    }

    const userIdKey = user_id === undefined || user_id === null ? '' : String(user_id).trim();
    if (userIdKey && directory.byUserId[userIdKey]) return directory.byUserId[userIdKey];

    const byId = resolveAvatarByUserId(user_id);
    if (byId) return byId;

    const cached = typeof localStorage !== 'undefined'
      ? localStorage.getItem('user_avatar')
      : null;
    const currentEmail = typeof localStorage !== 'undefined'
      ? String(localStorage.getItem('user_email') || '').trim().toLowerCase()
      : '';
    return cached && normalizedEmail && normalizedEmail === currentEmail ? cached : '';
  }

  root.AVATAR_BASE = AVATAR_BASE;
  root.AVATAR_BY_EMAIL = AVATAR_BY_EMAIL;
  root.AVATAR_BY_USER_ID = AVATAR_BY_USER_ID;
  root.resolveAvatar = resolveAvatar;
  root.resolveAvatarByUserId = resolveAvatarByUserId;
  root.resolveUserAvatar = resolveUserAvatar;
  root.rememberUserAvatar = rememberUserAvatar;
  root.__VINTTI_AVATAR_MAP__ = true;
})(typeof window !== 'undefined' ? window : this);
