const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080');
const TOKEN_KEY = 'merchant_cs_token';

let token = localStorage.getItem(TOKEN_KEY) || '';
let staffProfile = {
  staffId: null,
  staffNo: '',
  merchantCode: '',
  account: '',
  realName: '',
  phone: '',
  role: 'CUSTOMER_SERVICE',
  onlineStatus: 'OFFLINE',
  maxSessionCount: 8
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

function buildQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return;
    }
    query.set(key, value);
  });
  return query.toString();
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
      throw new Error(text || `接口返回格式错误（HTTP ${response.status}）`);
    }
  }
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `接口请求失败（HTTP ${response.status}）`);
  }
  return payload.data;
}

export function resolveAssetUrl(url) {
  if (!url) {
    return '';
  }
  if (/^(https?:)?\/\//.test(url) || url.startsWith('data:') || url.startsWith('blob:')) {
    return url;
  }
  if (url.startsWith('/uploads/') || url.startsWith('/static/')) {
    return buildUrl(`/api${url}`);
  }
  return buildUrl(url);
}

function resolveUploadUrl(payload) {
  const data = payload?.data ?? payload;
  if (typeof data === 'string') {
    return data;
  }
  return data?.url || data?.fileUrl || data?.path || data?.src || '';
}

export async function login(credentials) {
  const data = await request('/api/merchant-cs/auth/login', {
    method: 'POST',
    body: JSON.stringify(credentials)
  });
  saveToken(data.token);
  staffProfile = data.staff;
  return data;
}

export async function registerStaff(payload) {
  return request('/api/merchant-cs/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function sendAuthCode(payload) {
  return request('/api/merchant-cs/auth/code', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function resetPassword(payload) {
  return request('/api/merchant-cs/auth/password/reset', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function logout() {
  try {
    await request('/api/merchant-cs/auth/logout', { method: 'POST' });
  } finally {
    saveToken('');
    staffProfile = {
      staffId: null,
      staffNo: '',
      merchantCode: '',
      account: '',
      realName: '',
      phone: '',
      role: 'CUSTOMER_SERVICE',
      onlineStatus: 'OFFLINE',
      maxSessionCount: 8
    };
  }
}

export async function getCurrentStaff() {
  const data = await request('/api/merchant-cs/auth/me');
  staffProfile = { ...staffProfile, ...data };
  return data;
}

export async function updateWorkStatus(onlineStatus) {
  const data = await request('/api/merchant-cs/work-status', {
    method: 'PUT',
    body: JSON.stringify({ onlineStatus })
  });
  staffProfile.onlineStatus = data.onlineStatus;
  return data;
}

export async function getDashboardOverview() {
  return request('/api/merchant-cs/dashboard/overview');
}

export async function getDashboardTodos() {
  return request('/api/merchant-cs/dashboard/todos');
}

export async function getDashboardPerformance() {
  return request('/api/merchant-cs/dashboard/performance');
}

export async function getSessions(params = {}) {
  const query = buildQuery({
    status: params.status,
    keyword: params.keyword,
    page: params.page || 1,
    size: params.size || 20
  });
  return request(`/api/merchant-cs/sessions?${query}`);
}

export async function getSession(sessionId) {
  return request(`/api/merchant-cs/sessions/${sessionId}`);
}

export async function getSessionMessages(sessionId) {
  return request(`/api/merchant-cs/sessions/${sessionId}/messages`);
}

export async function getSessionAiAssist(sessionId) {
  return request(`/api/merchant-cs/sessions/${sessionId}/ai-assist`);
}

export async function sendSessionMessage(sessionId, content) {
  return request(`/api/merchant-cs/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ messageType: 'TEXT', content })
  });
}

export async function requestSessionEvaluation(sessionId) {
  return request(`/api/merchant-cs/sessions/${sessionId}/evaluation-request`, { method: 'POST' });
}

export async function submitSessionEvaluation(sessionId, rating, content) {
  return request(`/api/merchant-cs/sessions/${sessionId}/evaluation`, {
    method: 'POST',
    body: JSON.stringify({ rating, content })
  });
}

export async function closeSession(sessionId) {
  return request(`/api/merchant-cs/sessions/${sessionId}/close`, { method: 'POST' });
}

export async function getTickets(params = {}) {
  const query = buildQuery({
    status: params.status,
    type: params.type,
    keyword: params.keyword,
    page: params.page || 1,
    size: params.size || 20
  });
  return request(`/api/merchant-cs/tickets?${query}`);
}

export async function getTicket(ticketId) {
  return request(`/api/merchant-cs/tickets/${ticketId}`);
}

export async function getTicketLogs(ticketId) {
  return request(`/api/merchant-cs/tickets/${ticketId}/logs`);
}

export async function approveTicket(ticketId, auditOpinion) {
  return request(`/api/merchant-cs/tickets/${ticketId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ auditOpinion })
  });
}

export async function rejectTicket(ticketId, rejectReason) {
  return request(`/api/merchant-cs/tickets/${ticketId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ rejectReason })
  });
}

export async function completeTicket(ticketId, completeNote) {
  return request(`/api/merchant-cs/tickets/${ticketId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ completeNote })
  });
}

export async function getOrders(params = {}) {
  const query = buildQuery({
    status: params.status,
    keyword: params.keyword,
    page: params.page || 1,
    size: params.size || 20
  });
  return request(`/api/merchant-cs/orders?${query}`);
}

export async function getOrder(orderId) {
  return request(`/api/merchant-cs/orders/${orderId}`);
}

export async function shipOrder(orderId) {
  return request(`/api/merchant-cs/orders/${orderId}/ship`, { method: 'POST' });
}

export async function getNotices(params = {}) {
  const query = buildQuery({
    readStatus: params.readStatus,
    level: params.level,
    page: params.page || 1,
    size: params.size || 20
  });
  return request(`/api/merchant-cs/notices?${query}`);
}

export async function markNoticeRead(noticeId) {
  return request(`/api/merchant-cs/notices/${noticeId}/read`, { method: 'PUT' });
}

export async function getReviews(params = {}) {
  const query = buildQuery({
    score: params.score,
    keyword: params.keyword,
    page: params.page || 1,
    size: params.size || 20
  });
  return request(`/api/merchant-cs/reviews?${query}`);
}

export async function getProducts(params = {}) {
  const query = buildQuery({
    status: params.status,
    keyword: params.keyword,
    page: params.page || 1,
    size: params.size || 20
  });
  return request(`/api/merchant-cs/products?${query}`);
}

export async function getProduct(productId) {
  return request(`/api/merchant-cs/products/${productId}`);
}

export async function createProduct(productData) {
  return request('/api/merchant-cs/products', {
    method: 'POST',
    body: JSON.stringify(productData)
  });
}

export async function uploadProductImage(file) {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(buildUrl('/api/upload/image'), {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: formData
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(text || '图片上传接口返回格式错误');
    }
  }
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `图片上传失败（HTTP ${response.status}）`);
  }
  const url = resolveUploadUrl(payload);
  if (!url) {
    throw new Error('图片上传成功，但响应中没有图片地址');
  }
  return { ...(payload.data || {}), url };
}

export async function updateProduct(productId, productData) {
  return request(`/api/merchant-cs/products/${productId}`, {
    method: 'PUT',
    body: JSON.stringify(productData)
  });
}

export async function updateProductStatus(productId, status) {
  return request(`/api/merchant-cs/products/${productId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status })
  });
}
