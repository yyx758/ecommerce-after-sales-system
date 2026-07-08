const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080');
const TOKEN_KEY = 'admin_console_token';

let token = localStorage.getItem(TOKEN_KEY) || '';
let adminProfile = {
  adminId: null,
  account: '',
  realName: '',
  role: 'ADMIN',
  scope: '',
  phone: ''
};

function normalizeBaseUrl(url) {
  return url.replace(/\/+$/, '').replace(/\/api$/, '');
}

function buildUrl(path) {
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

function saveToken(newToken) {
  token = newToken || '';
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

async function request(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };
  const response = await fetch(buildUrl(path), {
    ...options,
    headers
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(text || `管理员接口返回格式错误（HTTP ${response.status}）`);
    }
  }
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `管理员接口请求失败（HTTP ${response.status}）`);
  }
  return payload.data;
}

export async function loginAdmin(credentials) {
  const data = await request('/api/admin/auth/login', {
    method: 'POST',
    body: JSON.stringify(credentials)
  });
  saveToken(data.token);
  adminProfile = { ...adminProfile, ...(data.admin || {}) };
  return data;
}

export async function logoutAdmin() {
  try {
    await request('/api/admin/auth/logout', { method: 'POST' });
  } finally {
    saveToken('');
    adminProfile = {
      adminId: null,
      account: '',
      realName: '',
      role: 'ADMIN',
      scope: '',
      phone: ''
    };
  }
}

export async function getCurrentAdmin() {
  const data = await request('/api/admin/auth/me');
  adminProfile = { ...adminProfile, ...data };
  return data;
}

export async function getAdminOverview() {
  return request('/api/admin/overview');
}

export async function getAgentAccounts() {
  return request('/api/admin/service-accounts');
}

export async function createAgentAccount(payload) {
  return request('/api/admin/service-accounts', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function updateAgentAccount(accountId, payload) {
  return request(`/api/admin/service-accounts/${accountId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

export async function resetAgentPassword(accountId) {
  return request(`/api/admin/service-accounts/${accountId}/reset-password`, {
    method: 'POST'
  });
}

export async function getKnowledgeLibraries() {
  return request('/api/admin/knowledge-bases');
}

export async function updateKnowledgeLibrary(libraryId, payload) {
  return request(`/api/admin/knowledge-bases/${libraryId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

export async function createKnowledgeLibrary(payload) {
  return request('/api/admin/knowledge-bases', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function syncKnowledgeLibrary(libraryId) {
  return request(`/api/admin/knowledge-bases/${libraryId}/sync`, {
    method: 'POST'
  });
}
