import { getApiBaseUrl, getRequestTimeout } from './apiConfig'

export function request(options) {
  const requestOptions = options || {}
  const baseUrl = getApiBaseUrl()

  return new Promise((resolve, reject) => {
    uni.request({
      url: `${baseUrl}${requestOptions.url}`,
      method: requestOptions.method || 'GET',
      data: requestOptions.data || {},
      timeout: getRequestTimeout(),
      header: {
        'content-type': 'application/json',
        ...(requestOptions.header || {})
      },
      success: (res) => {
        const body = res.data || {}
        if (body.code !== 200) {
          const error = new Error(body.message || '操作失败')
          error.code = body.code
          error.data = body.data
          reject(error)
          return
        }
        resolve(body.data)
      },
      fail: (error) => {
        reject(new Error(error?.errMsg || '后端服务未连接'))
      }
    })
  })
}
