<template>
  <view class="auth-page">
    <!-- 全屏渐变背景 -->
    <view class="bg-layer">
      <view class="bg-gradient" />
      <view class="bg-wave wave-1" />
      <view class="bg-wave wave-2" />
      <view class="bg-wave wave-3" />
      <view class="bg-glow glow-1" />
      <view class="bg-glow glow-2" />
      <view class="bg-glow glow-3" />
    </view>

    <!-- 主内容区（可滚动，避免微信登录被裁切） -->
    <scroll-view scroll-y class="content-scroll" :show-scrollbar="false">
      <view class="content">
      <!-- 状态栏占位 -->
      <view class="status-bar" :style="{ height: statusBarHeight + 'px' }" />
      <!-- 顶部品牌区 -->
      <view class="brand">
        <text class="brand-name">E-Commerce</text>
        <text class="brand-slogan">{{ modeTips }}</text>
      </view>

      <!-- 标签切换 -->
      <view class="tabs">
        <view
          v-for="item in modes"
          :key="item.value"
          class="tab"
          :class="{ active: mode === item.value }"
          @tap="switchMode(item.value)"
        >
          {{ item.label }}
        </view>
      </view>

      <!-- 输入区域 - 毛玻璃卡片 -->
      <view class="glass-card">
        <!-- 手机号 -->
        <view class="field-group">
          <input
            v-model="form.phone"
            class="field-input"
            type="number"
            maxlength="11"
            placeholder="请输入手机号"
            placeholder-style="color: rgba(255,255,255,0.4)"
          />
        </view>

        <view class="divider" />

        <!-- 验证码（注册/找回密码） -->
        <view v-if="mode !== 'login'" class="field-group">
          <input
            v-model="form.code"
            class="field-input code-field"
            type="number"
            maxlength="6"
            placeholder="请输入验证码"
            placeholder-style="color: rgba(255,255,255,0.4)"
          />
          <button
            class="code-btn"
            :disabled="codeCountdown > 0 || sendingCode"
            @tap="sendCode"
          >
            {{ codeCountdown > 0 ? `${codeCountdown}s` : '获取验证码' }}
          </button>
        </view>

        <view v-if="mode !== 'login'" class="divider" />

        <!-- 密码 -->
        <view class="field-group">
          <input
            v-model="form.password"
            class="field-input"
            password
            placeholder="请输入6到32位密码"
            placeholder-style="color: rgba(255,255,255,0.4)"
          />
        </view>

        <view class="divider" />

        <!-- 确认密码（找回密码） -->
        <view v-if="mode === 'reset'" class="field-group">
          <input
            v-model="form.confirmPassword"
            class="field-input"
            password
            placeholder="请再次输入密码"
            placeholder-style="color: rgba(255,255,255,0.4)"
          />
        </view>

        <view v-if="mode === 'reset'" class="divider" />

        <!-- 昵称（注册） -->
        <view v-if="mode === 'register'" class="field-group">
          <input
            v-model="form.nickname"
            class="field-input"
            placeholder="请输入昵称（选填）"
            placeholder-style="color: rgba(255,255,255,0.4)"
          />
        </view>

        <view v-if="mode === 'register'" class="divider" />
      </view>

      <!-- 登录按钮 -->
      <button class="submit-btn" :loading="submitting" @tap="submit">
        <text class="btn-text">{{ submitText }}</text>
      </button>

      <!-- 微信登录：紧跟登录按钮下方 -->
      <view v-if="mode === 'login'" class="wechat-section">
        <view class="divider-row">
          <view class="divider-line" />
          <text class="divider-text">或</text>
          <view class="divider-line" />
        </view>

        <view class="wechat-actions">
          <button class="wechat-btn" :loading="wechatSubmitting" @tap="handleWechatLogin">
            <view class="wechat-logo">
              <text class="wechat-logo-text">微信</text>
            </view>
            <text class="wechat-text">微信一键登录</text>
          </button>
          <button class="scan-btn" @tap="openScanModal">
            <text class="scan-btn-icon">⌁</text>
            <text class="scan-btn-text">模拟扫码</text>
          </button>
        </view>
      </view>

      <!-- 底部提示 -->
      <text class="footer-tip">登录后可查看订单、售后工单、咨询记录和系统通知</text>
      </view>
    </scroll-view>

    <!-- 模拟扫码授权弹窗 -->
    <view v-if="showScanModal" class="scan-mask" @tap="closeScanModal">
      <view class="scan-modal" @tap.stop>
        <text class="scan-title">模拟微信扫码授权</text>
        <view class="scan-qrcode">
          <view v-for="n in 49" :key="n" class="scan-cell" :class="{ dark: n % 3 === 0 }" />
        </view>
        <text class="scan-tip">开发沙盒环境，无需真实扫码</text>
        <button class="scan-confirm-btn" :loading="wechatSubmitting" @tap="confirmScanLogin">确认授权并登录</button>
        <button class="scan-cancel-btn" @tap="closeScanModal">取消</button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, reactive, ref, onMounted, onUnmounted } from 'vue'
import { request } from '../../utils/request'
import {
  loginWithWechatSandbox,
  persistLoginSession
} from '../../utils/clientConfig'

const statusBarHeight = ref(0)
const mode = ref('login')
const submitting = ref(false)
const wechatSubmitting = ref(false)
const sendingCode = ref(false)
const codeCountdown = ref(0)
const showScanModal = ref(false)
let countdownTimer = null

const modes = [
  { label: '登录', value: 'login' },
  { label: '注册', value: 'register' },
  { label: '找回密码', value: 'reset' }
]

const form = reactive({
  phone: '',
  code: '',
  password: '',
  confirmPassword: '',
  nickname: ''
})

const submitText = computed(() => {
  const textMap = { login: '登  录', register: '创建账号', reset: '重置密码' }
  return textMap[mode.value]
})

const modeTips = computed(() => {
  const tips = {
    login: '欢迎回来',
    register: '绑定手机号即可开始',
    reset: '验证身份后设置新密码'
  }
  return tips[mode.value]
})

onMounted(() => {
  const sysInfo = uni.getSystemInfoSync()
  statusBarHeight.value = sysInfo.statusBarHeight || 20
})

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

function switchMode(value) {
  mode.value = value
  form.code = ''
  form.password = ''
  form.confirmPassword = ''
}

async function sendCode() {
  if (codeCountdown.value > 0 || sendingCode.value) return
  if (!validatePhone()) return
  sendingCode.value = true
  try {
    const scene = mode.value === 'register' ? 'REGISTER' : 'RESET_PASSWORD'
    const data = await request({
      url: '/miniapp/auth/code',
      method: 'POST',
      data: { phone: form.phone, scene }
    })
    const code = data && data.code
    uni.showToast({ title: code ? `验证码 ${code}` : '验证码已发送', icon: 'none' })
    startCountdown()
  } catch (error) {
    uni.showToast({ title: error.message, icon: 'none' })
  } finally {
    sendingCode.value = false
  }
}

async function submit() {
  if (!validatePhone() || !validatePassword()) return
  if (mode.value !== 'login' && !form.code) {
    uni.showToast({ title: '请输入验证码', icon: 'none' })
    return
  }
  if (mode.value === 'reset' && form.password !== form.confirmPassword) {
    uni.showToast({ title: '两次输入密码不同', icon: 'none' })
    return
  }

  submitting.value = true
  try {
    const data = await request(buildRequest())
    if (mode.value === 'login') {
      persistLoginSession(data)
      uni.redirectTo({ url: '/pages/home/home' })
      return
    }
    uni.showToast({ title: mode.value === 'register' ? '注册成功' : '密码重置成功', icon: 'success' })
    switchMode('login')
  } catch (error) {
    uni.showToast({ title: error.message, icon: 'none' })
  } finally {
    submitting.value = false
  }
}

async function handleWechatLogin() {
  if (wechatSubmitting.value) return
  wechatSubmitting.value = true
  try {
    const data = await loginWithWechatSandbox()
    finishWechatLogin(data)
  } catch (error) {
    uni.showToast({ title: error.message || '微信登录失败', icon: 'none' })
  } finally {
    wechatSubmitting.value = false
  }
}

function openScanModal() {
  showScanModal.value = true
}

function closeScanModal() {
  if (wechatSubmitting.value) return
  showScanModal.value = false
}

async function confirmScanLogin() {
  if (wechatSubmitting.value) return
  wechatSubmitting.value = true
  try {
    const data = await loginWithWechatSandbox({ mockScan: true })
    showScanModal.value = false
    finishWechatLogin(data)
  } catch (error) {
    uni.showToast({ title: error.message || '模拟扫码登录失败', icon: 'none' })
  } finally {
    wechatSubmitting.value = false
  }
}

function finishWechatLogin(data) {
  persistLoginSession(data)
  const tip = data.newUser ? '微信账号已创建' : '微信登录成功'
  uni.showToast({ title: tip, icon: 'success' })
  setTimeout(() => {
    uni.redirectTo({ url: '/pages/home/home' })
  }, 300)
}

function buildRequest() {
  if (mode.value === 'register') {
    return {
      url: '/miniapp/auth/register',
      method: 'POST',
      data: { phone: form.phone, password: form.password, code: form.code, nickname: form.nickname }
    }
  }
  if (mode.value === 'reset') {
    return {
      url: '/miniapp/auth/password/reset',
      method: 'POST',
      data: { phone: form.phone, code: form.code, newPassword: form.password, confirmPassword: form.confirmPassword }
    }
  }
  return { url: '/miniapp/auth/login', method: 'POST', data: { phone: form.phone, password: form.password } }
}

function startCountdown() {
  codeCountdown.value = 60
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = setInterval(() => {
    codeCountdown.value -= 1
    if (codeCountdown.value <= 0) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }, 1000)
}

function validatePhone() {
  if (!/^1[3-9]\d{9}$/.test(form.phone)) {
    uni.showToast({ title: '请输入正确手机号', icon: 'none' })
    return false
  }
  return true
}

function validatePassword() {
  if (!form.password || form.password.length < 6 || form.password.length > 32) {
    uni.showToast({ title: '密码长度应为6到32位', icon: 'none' })
    return false
  }
  return true
}
</script>

<style scoped>
.auth-page {
  position: relative;
  min-height: 100vh;
}

.content-scroll {
  position: relative;
  z-index: 1;
  height: 100vh;
}

/* ===== 渐变背景层 ===== */
.bg-layer {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 0;
}

/* 主渐变 */
.bg-gradient {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background:
    radial-gradient(ellipse at 0% 0%, #f7b74a 0%, #f08a42 20%, transparent 50%),
    radial-gradient(ellipse at 0% 25%, #d4748a 0%, #9a6cbf 30%, transparent 55%),
    linear-gradient(160deg, #8b5cf6 0%, #5b3aae 25%, #2d1b69 55%, #1a0e40 100%);
}

/* 波浪装饰 */
.bg-wave {
  position: absolute;
  width: 200%;
  height: 200%;
  border-radius: 45%;
  opacity: 0.5;
}

.wave-1 {
  top: -140%;
  left: -50%;
  background: radial-gradient(ellipse at 30% 50%, rgba(247, 183, 74, 0.3) 0%, transparent 55%);
  animation: waveRotate1 12s linear infinite;
}

.wave-2 {
  top: -130%;
  left: -40%;
  background: radial-gradient(ellipse at 25% 50%, rgba(154, 108, 191, 0.25) 0%, transparent 50%);
  animation: waveRotate2 16s linear infinite;
}

.wave-3 {
  top: -150%;
  left: -60%;
  background: radial-gradient(ellipse at 35% 50%, rgba(139, 92, 246, 0.2) 0%, transparent 45%);
  animation: waveRotate3 20s linear infinite;
}

/* 光晕装饰 */
.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(60rpx);
}

.glow-1 {
  top: 5%;
  left: 5%;
  width: 500rpx;
  height: 500rpx;
  background: radial-gradient(circle, rgba(247, 183, 74, 0.2) 0%, transparent 70%);
  animation: glowFloat1 8s ease-in-out infinite;
}

.glow-2 {
  top: 40%;
  right: -10%;
  width: 600rpx;
  height: 600rpx;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.15) 0%, transparent 70%);
  animation: glowFloat2 10s ease-in-out infinite;
}

.glow-3 {
  bottom: 10%;
  left: -5%;
  width: 450rpx;
  height: 450rpx;
  background: radial-gradient(circle, rgba(212, 116, 138, 0.15) 0%, transparent 70%);
  animation: glowFloat3 12s ease-in-out infinite;
}

@keyframes waveRotate1 {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes waveRotate2 {
  from { transform: rotate(0deg); }
  to { transform: rotate(-360deg); }
}

@keyframes waveRotate3 {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes glowFloat1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(40rpx, 60rpx) scale(1.15); }
}

@keyframes glowFloat2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-50rpx, 40rpx) scale(1.1); }
}

@keyframes glowFloat3 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(30rpx, -50rpx) scale(1.2); }
}

/* ===== 内容区 ===== */
.content {
  position: relative;
  z-index: 1;
  padding: 0 48rpx 80rpx;
  padding-top: 40rpx;
  box-sizing: border-box;
}

.status-bar {
  width: 100%;
}

/* ===== 品牌区 ===== */
.brand {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  margin-bottom: 48rpx;
  margin-top: 48rpx;
}

.brand-name {
  color: #ffffff;
  font-size: 44rpx;
  font-weight: 700;
  letter-spacing: 2rpx;
}

.brand-slogan {
  color: rgba(255, 255, 255, 0.6);
  font-size: 26rpx;
  margin-top: 12rpx;
}

/* ===== 标签切换 ===== */
.tabs {
  display: flex;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 16rpx;
  padding: 6rpx;
  margin-bottom: 48rpx;
  backdrop-filter: blur(10px);
}

.tab {
  flex: 1;
  height: 76rpx;
  line-height: 76rpx;
  text-align: center;
  border-radius: 12rpx;
  color: rgba(255, 255, 255, 0.5);
  font-size: 28rpx;
  font-weight: 500;
  transition: all 0.3s;
}

.tab.active {
  background: rgba(255, 255, 255, 0.9);
  color: #2d1b69;
  font-weight: 600;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.1);
}

/* ===== 毛玻璃卡片 ===== */
.glass-card {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 24rpx;
  padding: 8rpx 32rpx;
  border: 1rpx solid rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(20px);
}

/* ===== 输入字段 ===== */
.field-group {
  display: flex;
  align-items: center;
  height: 100rpx;
}

.field-input {
  flex: 1;
  height: 100rpx;
  color: #ffffff;
  font-size: 28rpx;
  background: transparent;
}

.code-field {
  flex: 1;
}

.code-btn {
  flex-shrink: 0;
  height: 64rpx;
  line-height: 64rpx;
  padding: 0 24rpx;
  border-radius: 12rpx;
  background: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.8);
  font-size: 24rpx;
  font-weight: 600;
  border: none;
}

.code-btn[disabled] {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.3);
}

.divider {
  height: 1rpx;
  background: rgba(255, 255, 255, 0.08);
  margin: 0;
}

/* ===== 提交按钮 ===== */
.submit-btn {
  width: 100%;
  height: 100rpx;
  margin-top: 40rpx;
  border-radius: 50rpx;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8rpx 32rpx rgba(0, 0, 0, 0.15);
  border: none;
}

.btn-text {
  color: #2d1b69;
  font-size: 32rpx;
  font-weight: 600;
  letter-spacing: 8rpx;
}

/* ===== 底部提示 ===== */
.footer-tip {
  display: block;
  margin-top: 40rpx;
  text-align: center;
  color: rgba(255, 255, 255, 0.3);
  font-size: 22rpx;
  line-height: 1.6;
}

/* ===== 微信登录沙盒 ===== */
.wechat-section {
  margin-top: 28rpx;
}

.wechat-actions {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.divider-row {
  display: flex;
  align-items: center;
  margin-bottom: 24rpx;
}

.divider-line {
  flex: 1;
  height: 1rpx;
  background: rgba(255, 255, 255, 0.15);
}

.divider-text {
  margin: 0 24rpx;
  color: rgba(255, 255, 255, 0.45);
  font-size: 24rpx;
}

.wechat-btn {
  width: 100%;
  height: 96rpx;
  border-radius: 48rpx;
  background: #07c160;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  box-shadow: 0 8rpx 24rpx rgba(7, 193, 96, 0.35);
}

.wechat-logo {
  width: 48rpx;
  height: 48rpx;
  margin-right: 16rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  display: flex;
  align-items: center;
  justify-content: center;
}

.wechat-logo-text {
  color: #07c160;
  font-size: 18rpx;
  font-weight: 800;
  line-height: 1;
}

.wechat-text {
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 600;
}

.scan-btn {
  width: 100%;
  height: 88rpx;
  border-radius: 44rpx;
  background: rgba(255, 255, 255, 0.12);
  border: 1rpx solid rgba(255, 255, 255, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
}

.scan-btn-icon {
  color: rgba(255, 255, 255, 0.85);
  font-size: 32rpx;
  line-height: 1;
}

.scan-btn-text {
  color: rgba(255, 255, 255, 0.9);
  font-size: 28rpx;
  font-weight: 600;
}

.scan-mask {
  position: fixed;
  inset: 0;
  z-index: 99;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48rpx;
}

.scan-modal {
  width: 100%;
  max-width: 620rpx;
  padding: 40rpx 32rpx 32rpx;
  border-radius: 28rpx;
  background: #ffffff;
  box-sizing: border-box;
}

.scan-title {
  display: block;
  text-align: center;
  color: #111827;
  font-size: 32rpx;
  font-weight: 700;
}

.scan-qrcode {
  width: 320rpx;
  height: 320rpx;
  margin: 32rpx auto;
  padding: 16rpx;
  border: 1rpx solid #e5e7eb;
  border-radius: 16rpx;
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6rpx;
  box-sizing: border-box;
}

.scan-cell {
  background: #f3f4f6;
  border-radius: 4rpx;
}

.scan-cell.dark {
  background: #111827;
}

.scan-tip {
  display: block;
  text-align: center;
  color: #6b7280;
  font-size: 24rpx;
  margin-bottom: 28rpx;
}

.scan-confirm-btn {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 44rpx;
  background: #07c160;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 600;
  border: none;
  margin-bottom: 16rpx;
}

.scan-cancel-btn {
  width: 100%;
  height: 80rpx;
  line-height: 80rpx;
  border-radius: 40rpx;
  background: #f3f4f6;
  color: #374151;
  font-size: 28rpx;
  border: none;
}
</style>
