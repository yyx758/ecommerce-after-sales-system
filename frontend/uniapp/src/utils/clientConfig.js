import { BASE_URL, request } from './request'

const DEFAULT_SANDBOX_USERS = [
  {
    openid: 'sandbox_wx_alice',
    code: 'sandbox_code_alice',
    nickname: '微信沙箱-Alice',
    avatarUrl: '',
    phone: '19900000001'
  },
  {
    openid: 'sandbox_wx_bob',
    code: 'sandbox_code_bob',
    nickname: '微信沙箱-Bob',
    avatarUrl: '',
    phone: '19900000002'
  },
  {
    openid: 'sandbox_wx_charlie',
    code: 'sandbox_code_charlie',
    nickname: '微信沙箱-Charlie',
    avatarUrl: '',
    phone: '19900000003'
  }
]

export async function fetchClientConfig() {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}/miniapp/public/client-config`,
      method: 'GET',
      success: (res) => {
        const body = res.data || {}
        if (body.code !== 200) {
          reject(new Error(body.message || '获取客户端配置失败'))
          return
        }
        resolve(body.data || {})
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '无法连接后端配置服务'))
      }
    })
  })
}

export async function loadWechatSandboxConfig() {
  try {
    const config = await fetchClientConfig()
    const sandbox = config && config.wechatSandbox
    if (sandbox && sandbox.enabled) {
      return {
        enabled: true,
        users: Array.isArray(sandbox.users) && sandbox.users.length ? sandbox.users : DEFAULT_SANDBOX_USERS
      }
    }
  } catch (error) {
    console.warn('读取微信沙箱配置失败，使用本地默认配置', error)
  }

  return {
    enabled: true,
    users: DEFAULT_SANDBOX_USERS
  }
}

function resolveSandboxUser(config, preferredUser) {
  if (preferredUser && preferredUser.openid) {
    return preferredUser
  }
  const users = Array.isArray(config?.users) ? config.users : []
  return users.find((item) => item && item.openid) || DEFAULT_SANDBOX_USERS[0]
}

export async function loginWithWechatSandbox(options = {}) {
  const payload = {}
  const sandboxConfig = await loadWechatSandboxConfig()
  const sandboxUser = resolveSandboxUser(sandboxConfig, options.sandboxUser)

  if (!sandboxUser || !sandboxUser.openid) {
    throw new Error('未找到可用的微信沙箱账号')
  }

  payload.openid = sandboxUser.openid
  payload.nickname = options.nickname || sandboxUser.nickname
  payload.avatarUrl = options.avatarUrl || sandboxUser.avatarUrl

  return {
    ...(await request({
      url: '/miniapp/auth/wechat/login',
      method: 'POST',
      data: payload
    })),
    sandboxMode: true
  }
}

export function persistLoginSession(data) {
  if (!data || !data.token) {
    throw new Error('登录结果无效')
  }
  uni.setStorageSync('token', data.token)
  uni.setStorageSync('userInfo', data)
  if (data.openid) {
    uni.setStorageSync('wechatOpenid', data.openid)
  }
}

export function getSandboxUserInitial(user = {}) {
  return (user.nickname || '微').slice(0, 1)
}
