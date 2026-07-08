<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getSession,
  getSessionAiAssist,
  getSessionMessages,
  getSessions,
  resolveAssetUrl,
  sendSessionMessage
} from '../api/merchantCs';

const route = useRoute();
const router = useRouter();
const shell = inject('merchantCsShell', null);

const sessions = ref([]);
const session = ref(null);
const messages = ref([]);
const aiAssist = ref(null);
const loading = ref(false);
const errorMessage = ref('');
const draft = ref('');
const sending = ref(false);
const activeFilter = ref('ACTIVE');

let ws = null;
let wsReconnectTimer = null;
const MAX_EMOTION_TREND_ITEMS = 6;

const terminalStatuses = ['RESOLVED', 'CLOSED'];
const filterOptions = [
  { key: 'ACTIVE', label: '活跃' },
  { key: 'WAITING', label: '进行中' },
  { key: 'AWAITING_EVALUATION', label: '待评价' },
  { key: 'READY_TO_CLOSE', label: '待关闭' },
  { key: 'COMPLETED', label: '已完成' }
];

const fallbackFaqCatalog = {
  quality_issue: [
    {
      question: '平台审核要多久？',
      answer: '质量问题通常需要先核对故障描述和图片、视频，材料齐全后会尽快进入审核。'
    },
    {
      question: '还需要补什么？',
      answer: '如果故障表现还不够清楚，建议补充异常描述、图片或视频，方便更快判断方案。'
    }
  ],
  wrong_or_missing_items: [
    {
      question: '少发错发怎么处理？',
      answer: '通常先核对订单与收到的商品，确认后可优先安排补发。'
    },
    {
      question: '需要什么凭证？',
      answer: '建议补充包裹照片、商品照片，以及缺少的是哪一件或哪个配件。'
    }
  ],
  logistics_issue: [
    {
      question: '物流异常怎么处理？',
      answer: '先核对物流节点和签收状态，如有异常会继续协助跟进。'
    },
    {
      question: '多久能有结果？',
      answer: '物流问题一般会结合承运信息同步进展，异常件可能需要进一步核查。'
    }
  ],
  general: [
    {
      question: '平台审核要多久？',
      answer: '售后处理时效会根据资料完整度和问题类型略有不同，材料齐全时会更快。'
    },
    {
      question: '还需要补什么？',
      answer: '如果后续需要补充材料，客服会根据当前场景继续提示。'
    }
  ]
};

const currentSessionId = computed(() => normalizeId(route.params.sessionId));

const visibleSessions = computed(() => {
  return sessions.value
    .filter((item) => String(item?.status || '').toUpperCase() !== 'CLOSED')
    .filter((item) => {
      if (activeFilter.value === 'ACTIVE') {
        return !terminalStatuses.includes(String(item?.status || '').toUpperCase());
      }
      if (activeFilter.value === 'COMPLETED') {
        return terminalStatuses.includes(String(item?.status || '').toUpperCase());
      }
      if (activeFilter.value === 'WAITING') {
        const status = String(item?.status || '').toUpperCase();
        return status === 'WAITING' || status === 'PROCESSING';
      }
      return String(item?.status || '').toUpperCase() === activeFilter.value;
    });
});

const currentSession = computed(() => {
  if (session.value) {
    return session.value;
  }
  return sessions.value.find((item) => sameId(item?.id, currentSessionId.value)) || null;
});

const sortedMessages = computed(() => {
  return [...messages.value].sort((left, right) => {
    const leftTime = parseTime(left?.createdAt);
    const rightTime = parseTime(right?.createdAt);
    return leftTime - rightTime;
  });
});

const latestUserMessage = computed(() => {
  return [...sortedMessages.value].reverse().find((item) => isUserMessage(item) && !isImageMessage(item)) || null;
});

const userEmotionMessages = computed(() => {
  return sortedMessages.value.filter((item) => isUserMessage(item) && !isImageMessage(item) && item?.emotionLabel);
});

const latestUserEmotionMessage = computed(() => {
  return [...userEmotionMessages.value].reverse()[0] || null;
});

const recentEmotionMessages = computed(() => {
  return userEmotionMessages.value.slice(-MAX_EMOTION_TREND_ITEMS);
});

const currentEmotionSnapshot = computed(() => {
  const source = latestUserEmotionMessage.value || latestUserMessage.value || currentSession.value || {};
  const rawLabel = String(source.emotionLabel || 'CALM').toUpperCase();
  return {
    label: emotionLabelText(rawLabel),
    rawLabel,
    score: normalizePercent(source.emotionScore),
    confidence: normalizePercent(source.emotionConfidence),
    tone: emotionTone(rawLabel),
    summary: emotionSummary(rawLabel)
  };
});

const emotionTrend = computed(() => {
  return recentEmotionMessages.value.map((item, index) => ({
    id: item.id || `${item.createdAt || 'message'}-${index}`,
    step: index + 1,
    label: emotionLabelText(item.emotionLabel),
    rawLabel: String(item.emotionLabel || '').toUpperCase(),
    score: normalizePercent(item.emotionScore),
    confidence: normalizePercent(item.emotionConfidence),
    createdAt: item.createdAt || '--',
    preview: shortText(item.content, 36)
  }));
});

const emotionEscalationText = computed(() => {
  if (emotionTrend.value.length < 2) {
    return '当前样本还不多，先结合最近一轮用户表达判断。';
  }
  const firstRank = emotionRank(emotionTrend.value[0].rawLabel);
  const lastRank = emotionRank(emotionTrend.value[emotionTrend.value.length - 1].rawLabel);
  if (lastRank > firstRank) {
    return '用户情绪有升级趋势，建议优先回应最新诉求并缩短等待感。';
  }
  if (lastRank < firstRank) {
    return '用户情绪较前面已有缓和，可以继续按当前流程推进。';
  }
  return '用户情绪整体比较平稳，重点关注最近一轮表达变化。';
});

const conversationScene = computed(() => {
  const raw = aiAssist.value?.sceneCode || inferSceneCode(`${currentSession.value?.topic || ''} ${latestUserMessage.value?.content || ''}`);
  return normalizeSceneCode(raw);
});

const emotionTrendHint = computed(() => {
  const total = userEmotionMessages.value.length;
  if (total <= MAX_EMOTION_TREND_ITEMS) {
    return `已根据最近 ${total} 条用户消息绘制情绪变化趋势。`;
  }
  return `当前仅展示最近 ${MAX_EMOTION_TREND_ITEMS} 条用户消息，便于快速查看最新变化。`;
});

const oneClickReplyAssist = computed(() => {
  const recommendation = aiAssist.value?.recommendation;
  const recommendationText = String(recommendation?.text || '').trim();
  if (!recommendationText) {
    return null;
  }
  return {
    text: recommendationText
  };
});

const currentProduct = computed(() => {
  return currentSession.value?.product || currentSession.value?.productName || '售后商品';
});

const conversationDigestItems = computed(() => {
  const digest = aiAssist.value?.conversationDigest;
  if (digest && typeof digest === 'object') {
    const items = [
      { key: 'userNeed', label: '用户需求', value: String(digest.userNeed || '').trim() },
      { key: 'reason', label: '原因', value: String(digest.reason || '').trim() }
    ].filter((item) => item.value);
    if (items.length) {
      return items;
    }
  }

  const userTexts = sortedMessages.value
    .filter((item) => isUserMessage(item) && !isImageMessage(item))
    .map((item) => String(item.content || '').trim())
    .filter(Boolean);
  if (!userTexts.length) {
    return [];
  }
  const userNeed = userTexts[userTexts.length - 1];
  const reason = userTexts.length >= 2 ? userTexts.slice(0, -1).join('；') : '';
  return [
    { key: 'userNeed', label: '用户需求', value: userNeed },
    { key: 'reason', label: '原因', value: reason }
  ].filter((item) => item.value);
});

const faqItems = computed(() => {
  const knowledgeHits = Array.isArray(aiAssist.value?.knowledgeHits) ? aiAssist.value.knowledgeHits : [];
  if (knowledgeHits.length) {
    return knowledgeHits.slice(0, 3).map((item, index) => ({
      id: item.id || item.code || `knowledge-${index}`,
      question: item.title || item.policyName || item.label || `知识点 ${index + 1}`,
      answer: item.summary || item.content || item.snippet || '当前命中知识已返回，前端可按需要继续扩展展示。'
    }));
  }

  const sceneFaq = fallbackFaqCatalog[conversationScene.value] || fallbackFaqCatalog.general;
  return sceneFaq.map((item, index) => ({
    id: `${conversationScene.value}-${index}`,
    ...item
  }));
});

const currentOrderNo = computed(() => fieldValue(currentSession.value?.orderNo, '--'));
const currentStatusLabel = computed(() => statusLabel(currentSession.value?.status));
const currentStatusTone = computed(() => statusTone(currentSession.value?.status));
const activeSessionCount = computed(() => visibleSessions.value.length);

async function loadPage() {
  if (!currentSessionId.value) {
    return;
  }

  loading.value = true;
  errorMessage.value = '';

  try {
    const [pageResult, detailResult, messagesResult, assistResult] = await Promise.allSettled([
      getSessions(),
      getSession(currentSessionId.value),
      getSessionMessages(currentSessionId.value),
      getSessionAiAssist(currentSessionId.value)
    ]);

    sessions.value = pageResult.status === 'fulfilled' ? pageResult.value?.records || [] : [];
    session.value = detailResult.status === 'fulfilled'
      ? detailResult.value
      : sessions.value.find((item) => sameId(item?.id, currentSessionId.value)) || null;
    messages.value = messagesResult.status === 'fulfilled' ? messagesResult.value || [] : [];
    aiAssist.value = assistResult.status === 'fulfilled' ? assistResult.value : null;

    if (detailResult.status === 'rejected' && !session.value) {
      errorMessage.value = detailResult.reason?.message || '会话详情加载失败';
    } else if (messagesResult.status === 'rejected') {
      errorMessage.value = messagesResult.reason?.message || '消息加载失败';
    } else {
      errorMessage.value = '';
    }

    connectWebSocket(currentSessionId.value);
  } finally {
    loading.value = false;
  }
}

async function reloadAssistAndMessages() {
  if (!currentSessionId.value) {
    return;
  }
  try {
    const [messagesResult, assistResult] = await Promise.allSettled([
      getSessionMessages(currentSessionId.value),
      getSessionAiAssist(currentSessionId.value)
    ]);
    if (messagesResult.status === 'fulfilled') {
      messages.value = messagesResult.value || [];
    }
    if (assistResult.status === 'fulfilled') {
      aiAssist.value = assistResult.value;
    }
  } catch {
    // Keep current UI state when refresh fails.
  }
}

function connectWebSocket(sessionId) {
  if (!sessionId) {
    return;
  }

  if (ws) {
    ws.close();
    ws = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }

  try {
    ws = new WebSocket('ws://127.0.0.1:8080/api/ws/chat');
    ws.onopen = () => {
      ws.send(JSON.stringify({ action: 'subscribe', sessionId }));
    };
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.action !== 'message' || !sameId(payload.sessionId, sessionId)) {
          return;
        }
        const incoming = {
          id: payload.id || `${payload.createdAt || Date.now()}`,
          sessionId: payload.sessionId,
          senderRole: payload.role === 'USER' ? 'USER' : 'SERVICE',
          messageType: payload.messageType || 'TEXT',
          content: payload.content,
          createdAt: payload.createdAt,
          emotionLabel: payload.emotionLabel,
          emotionScore: payload.emotionScore,
          emotionConfidence: payload.emotionConfidence
        };
        if (!messages.value.some((item) => sameId(item.id, incoming.id))) {
          messages.value = [...messages.value, incoming];
        }
        if (incoming.senderRole === 'USER') {
          reloadAssistAndMessages();
        }
      } catch {
        // Ignore malformed websocket payloads.
      }
    };
    ws.onclose = () => {
      wsReconnectTimer = window.setTimeout(() => {
        if (currentSessionId.value) {
          connectWebSocket(currentSessionId.value);
        }
      }, 3000);
    };
  } catch {
    // Ignore websocket startup failures and keep HTTP mode.
  }
}

async function handleSend() {
  await sendReply(draft.value);
}

async function sendReply(content, options = {}) {
  const normalized = String(content || '').trim();
  if (!normalized || sending.value || !currentSessionId.value) {
    return;
  }

  sending.value = true;
  try {
    const message = await sendSessionMessage(currentSessionId.value, normalized);
    messages.value = [...messages.value, message];
    if (!options.keepDraft) {
      draft.value = '';
    }
    shell?.setAction?.('消息已发送');
    await loadPage();
  } catch (error) {
    shell?.setAction?.(error.message || '发送失败');
  } finally {
    sending.value = false;
  }
}

function handleInputKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    handleSend();
  }
}

function goSession(sessionId) {
  router.push(`/sessions/${sessionId}`);
}

function openOrder() {
  const orderId = currentSession.value?.orderId || currentSession.value?.orderNo;
  if (!orderId) {
    return;
  }
  router.push(`/orders/${orderId}`);
}

function fillDraft(text) {
  draft.value = text || '';
  shell?.setAction?.('已写入输入框，可直接发送');
}

function useRecommendedReply() {
  if (!oneClickReplyAssist.value?.text) {
    return;
  }
  fillDraft(oneClickReplyAssist.value.text);
}

function isUserMessage(message) {
  return String(message?.senderRole || '').toUpperCase() === 'USER';
}

function isImageMessage(message) {
  return String(message?.messageType || '').toUpperCase() === 'IMAGE';
}

function imageSrc(message) {
  return resolveAssetUrl(message?.content);
}

function displayName(item) {
  return fieldValue(item?.user || item?.userName || item?.nickname, '未知用户');
}

function fieldValue(value, fallback = '--') {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  return value;
}

function shortText(value, limit = 28) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) {
    return '暂无内容';
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function parseTime(value) {
  if (!value) {
    return 0;
  }
  const numeric = new Date(String(value).replace(' ', 'T')).getTime();
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatMessageTime(value) {
  if (!value) {
    return '--';
  }
  const date = new Date(String(value).replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function normalizeId(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value);
}

function sameId(left, right) {
  return normalizeId(left) === normalizeId(right);
}

function normalizePercent(value) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  if (numeric <= 1) {
    return Math.round(Math.max(0, numeric) * 100);
  }
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function statusLabel(status) {
  const map = {
    WAITING: '待处理',
    PROCESSING: '处理中',
    AWAITING_EVALUATION: '待评价',
    READY_TO_CLOSE: '待关闭',
    RESOLVED: '已完成',
    CLOSED: '已关闭'
  };
  return map[String(status || '').toUpperCase()] || '处理中';
}

function statusTone(status) {
  const normalized = String(status || '').toUpperCase();
  if (normalized === 'RESOLVED' || normalized === 'CLOSED') {
    return 'closed';
  }
  if (normalized === 'READY_TO_CLOSE' || normalized === 'AWAITING_EVALUATION') {
    return 'ready';
  }
  if (normalized === 'WAITING') {
    return 'waiting';
  }
  return 'processing';
}

function emotionLabelText(label) {
  const map = {
    SATISFIED: '满意',
    CALM: '平静',
    NEUTRAL: '平静',
    NORMAL: '平静',
    ANXIOUS: '焦虑',
    DISSATISFIED: '不满',
    ANGRY: '愤怒'
  };
  return map[String(label || '').toUpperCase()] || '未识别';
}

function emotionRank(label) {
  const map = {
    SATISFIED: 0,
    CALM: 1,
    NEUTRAL: 1,
    NORMAL: 1,
    ANXIOUS: 2,
    DISSATISFIED: 3,
    ANGRY: 4
  };
  return map[String(label || '').toUpperCase()] ?? 1;
}

function emotionTone(label) {
  const map = {
    SATISFIED: 'calm',
    CALM: 'calm',
    NEUTRAL: 'calm',
    NORMAL: 'calm',
    ANXIOUS: 'anxious',
    DISSATISFIED: 'dissatisfied',
    ANGRY: 'angry'
  };
  return map[String(label || '').toUpperCase()] || 'calm';
}

function emotionSummary(label) {
  const map = {
    SATISFIED: '当前用户情绪较稳定，可以按正常节奏推进。',
    CALM: '当前表达比较平稳，没有明显升级风险。',
    NEUTRAL: '当前表达比较平稳，没有明显升级风险。',
    NORMAL: '当前表达比较平稳，没有明显升级风险。',
    ANXIOUS: '用户更关注处理速度和结果，需要及时反馈进展。',
    DISSATISFIED: '用户已出现明显负面感受，建议加强解释与安抚。',
    ANGRY: '用户情绪风险较高，建议优先处理并评估是否转人工升级。'
  };
  return map[String(label || '').toUpperCase()] || '暂未获取到明确的情绪判断。';
}

function normalizeSceneCode(sceneCode) {
  const normalized = String(sceneCode || '').toLowerCase();
  if (normalized.includes('quality')) {
    return 'quality_issue';
  }
  if (normalized.includes('missing') || normalized.includes('wrong')) {
    return 'wrong_or_missing_items';
  }
  if (normalized.includes('logistics')) {
    return 'logistics_issue';
  }
  return 'general';
}

function inferSceneCode(text) {
  const content = String(text || '').toLowerCase();
  if (/(少发|漏发|缺件|补发)/.test(content)) {
    return 'wrong_or_missing_items';
  }
  if (/(物流|快递|没收到|签收)/.test(content)) {
    return 'logistics_issue';
  }
  if (/(没声音|故障|坏了|异常|质量|损坏|不能用|充电无反应)/.test(content)) {
    return 'quality_issue';
  }
  return 'general';
}

watch(() => route.params.sessionId, loadPage);

onMounted(loadPage);

onUnmounted(() => {
  if (ws) {
    ws.close();
    ws = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
});
</script>

<template>
  <section class="session-template-page">
    <aside class="session-template-list">
      <div class="template-panel-head">
        <h2>会话列表</h2>
        <button type="button" class="template-icon-button" aria-label="会话筛选">筛</button>
      </div>

      <div class="template-filter-tabs" aria-label="会话筛选">
        <button
          v-for="option in filterOptions"
          :key="option.key"
          type="button"
          :class="{ active: activeFilter === option.key }"
          @click="activeFilter = option.key"
        >
          {{ option.label }}
        </button>
      </div>

      <div v-if="visibleSessions.length" class="template-conversation-list">
        <button
          v-for="item in visibleSessions"
          :key="item.id"
          type="button"
          :class="['template-conversation-card', { active: sameId(item.id, currentSessionId) }]"
          @click="goSession(item.id)"
        >
          <span class="template-user-avatar">{{ displayName(item).slice(0, 1) }}</span>
          <span class="template-conversation-copy">
            <strong>{{ displayName(item) }}</strong>
            <em>{{ shortText(item.topic || item.lastMessageContent, 22) }}</em>
            <small>{{ shortText(item.orderNo, 18) }}</small>
          </span>
          <span class="template-conversation-side">
            <time>{{ formatMessageTime(item.lastMessageTime) }}</time>
            <i v-if="!terminalStatuses.includes(String(item.status || '').toUpperCase())" aria-hidden="true"></i>
          </span>
        </button>
      </div>
      <div v-else class="template-list-empty">当前筛选下没有会话</div>

      <div class="template-list-foot">共 {{ activeSessionCount }} 条会话</div>
    </aside>

    <article class="session-template-chat">
      <header class="template-chat-head">
        <span class="template-user-avatar large">{{ displayName(currentSession).slice(0, 1) }}</span>
        <div>
          <h2>{{ displayName(currentSession) }}</h2>
          <p>订单号：{{ currentOrderNo }}</p>
        </div>
        <span :class="['session-status', currentStatusTone]">{{ currentStatusLabel }}</span>
        <button type="button" class="template-order-button" @click="openOrder">查看订单</button>
      </header>

      <div class="template-message-stream">
        <div v-if="errorMessage" class="message-stream-empty">
          <strong>会话内容暂时不可用</strong>
          <p>{{ errorMessage }}</p>
        </div>

        <template v-else-if="sortedMessages.length">
          <div
            v-for="message in sortedMessages"
            :key="message.id"
            :class="['template-message-row', isUserMessage(message) ? 'user' : 'service']"
          >
            <span class="template-user-avatar mini">{{ isUserMessage(message) ? displayName(currentSession).slice(0, 1) : '服' }}</span>
            <div :class="['template-message-content', { image: isImageMessage(message) }]">
              <img
                v-if="isImageMessage(message)"
                class="template-message-image"
                :src="imageSrc(message)"
                alt="会话图片"
              />
              <p v-else>{{ message.content }}</p>
              <time>{{ formatMessageTime(message.createdAt) }}</time>
            </div>
          </div>
        </template>

        <div v-else class="message-stream-empty">
          <strong>{{ loading ? '正在加载会话消息…' : '还没有会话消息' }}</strong>
          <p>用户发送的文本、图片和客服回复会显示在这里。</p>
        </div>

        <section class="template-product-card">
          <img
            v-if="currentSession?.productImage"
            class="product-thumb image"
            :src="resolveAssetUrl(currentSession.productImage)"
            alt="鍞悗鍟嗗搧"
          />
          <div v-else class="product-thumb">{{ currentProduct.slice(0, 1) }}</div>
          <div class="product-card-main">
            <strong>{{ currentProduct }}</strong>
            <span>订单号：{{ currentOrderNo }}</span>
            <em :class="['session-status', currentStatusTone]">{{ currentStatusLabel }}</em>
          </div>
          <button type="button" @click="openOrder">查看订单</button>
        </section>
      </div>

      <section v-if="oneClickReplyAssist" class="reply-assist-panel">
        <p class="reply-assist-text" :title="oneClickReplyAssist.text">{{ oneClickReplyAssist.text }}</p>
        <div class="reply-card-actions">
          <button type="button" class="reply-fill-button" @click="fillDraft(oneClickReplyAssist.text)">
            填入
          </button>
          <button type="button" class="reply-send-button" :disabled="sending" @click="sendReply(oneClickReplyAssist.text)">
            {{ sending ? '发送中' : '发送' }}
          </button>
        </div>
      </section>

      <form class="template-reply-composer" @submit.prevent="handleSend">
        <textarea
          v-model="draft"
          rows="3"
          placeholder="请输入消息，Enter 发送，Shift + Enter 换行"
          @keydown="handleInputKeydown"
        ></textarea>
        <div class="template-composer-actions">
          <span class="template-tool-row" aria-label="消息工具">
            <button type="button" aria-label="表情">表</button>
            <button type="button" aria-label="图片">图</button>
            <button type="button" aria-label="快捷短语" @click="useRecommendedReply">语</button>
            <button type="button" aria-label="附件">附</button>
          </span>
          <button type="submit" class="template-send-button" :disabled="sending || !draft.trim()">
            {{ sending ? '发送中' : '发送' }}
          </button>
        </div>
      </form>
    </article>

    <aside class="session-template-assist">
      <section class="template-assist-card handoff-summary-card">
        <div class="template-card-title">
          <h2>AI 提炼对话</h2>
        </div>
        <div v-if="conversationDigestItems.length" class="digest-list">
          <p
            v-for="item in conversationDigestItems"
            :key="item.key"
            class="digest-item"
          >
            <strong>{{ item.label }}：</strong>
            <span>{{ item.value }}</span>
          </p>
        </div>
        <p v-else class="digest-empty">暂无足够对话上下文，AI 暂无法提炼用户需求。</p>
      </section>

      <section class="template-assist-card faq-card">
        <div class="template-card-title">
          <h2>FAQ</h2>
          <span>{{ conversationScene === 'general' ? '当前会话' : '场景命中' }}</span>
        </div>

        <div class="faq-list">
          <article
            v-for="item in faqItems"
            :key="item.id"
            class="faq-item"
            role="button"
            tabindex="0"
            @click="fillDraft(item.answer)"
            @keydown.enter="fillDraft(item.answer)"
          >
            <strong>{{ item.question }}</strong>
            <p>{{ item.answer }}</p>
          </article>
        </div>
      </section>

      <section class="template-assist-card emotion-monitor-card">
        <div class="template-card-title">
          <h2>情绪变化监控</h2>
        </div>

        <div class="emotion-overview">
          <div class="emotion-head">
            <strong>{{ currentEmotionSnapshot.label }}</strong>
            <p>{{ currentEmotionSnapshot.summary }}</p>
          </div>
          <div class="emotion-meters">
            <div class="emotion-meter">
              <span>情绪分数</span>
              <strong>{{ currentEmotionSnapshot.score }}</strong>
            </div>
            <div class="emotion-meter">
              <span>置信度</span>
              <strong>{{ currentEmotionSnapshot.confidence }}</strong>
            </div>
          </div>
        </div>

        <div class="emotion-trend-copy">
          <strong>趋势判断</strong>
          <p>{{ emotionEscalationText }}</p>
          <small class="emotion-trend-hint">{{ emotionTrendHint }}</small>
        </div>

        <div v-if="emotionTrend.length" class="emotion-trend-list">
          <article v-for="item in emotionTrend" :key="item.id" class="emotion-trend-item">
            <div class="emotion-trend-head">
              <span class="emotion-step">第 {{ item.step }} 轮</span>
              <span :class="['emotion-pill', emotionTone(item.rawLabel)]">{{ item.label }}</span>
            </div>
            <p class="emotion-preview">{{ item.preview }}</p>
            <div class="emotion-track-row">
              <span>分数 {{ item.score }}</span>
              <div class="emotion-track">
                <i :style="{ width: `${item.score}%` }"></i>
              </div>
              <span>置信 {{ item.confidence }}</span>
            </div>
            <small>{{ item.createdAt }}</small>
          </article>
        </div>
        <div v-else class="emotion-empty">当前还没有足够的用户消息来绘制情绪变化轨迹。</div>
      </section>
    </aside>
  </section>
</template>

<style scoped>
.message-stream-empty {
  min-height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  text-align: center;
  color: #64748b;
}

.message-stream-empty strong {
  color: #0f172a;
  font-size: 16px;
}

.faq-list {
  display: grid;
  gap: 10px;
}

.handoff-summary-card {
  gap: 12px;
}

.digest-empty {
  margin: 0;
  padding: 14px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.9);
  color: #64748b;
  line-height: 1.7;
  font-size: 13px;
}

.digest-list {
  display: grid;
  gap: 10px;
}

.digest-item {
  margin: 0;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.9);
  color: #334155;
  line-height: 1.7;
  font-size: 13px;
}

.digest-item strong {
  color: #0f172a;
}

.handoff-summary-card p {
  margin: 0;
  padding: 14px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.9);
  color: #334155;
  line-height: 1.7;
}

.reply-assist-panel {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 8px;
  padding: 6px 10px;
  min-height: 36px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.5);
  opacity: 0.5;
}

.reply-assist-text {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.45;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.reply-card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.reply-fill-button,
.reply-send-button {
  border: none;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  line-height: 1.2;
  cursor: pointer;
  transition: transform 0.16s ease, background 0.16s ease;
}

.reply-fill-button {
  color: #0f172a;
  background: rgba(255, 255, 255, 0.82);
}

.reply-send-button {
  color: #fff;
  background: #f97316;
  box-shadow: none;
}

.reply-fill-button:hover,
.reply-send-button:hover {
  transform: translateY(-1px);
}

.reply-send-button:disabled,
.template-send-button:disabled {
  cursor: not-allowed;
  opacity: 0.68;
  transform: none;
}

@media (max-width: 900px) {
  .reply-card-actions {
    justify-content: flex-end;
  }
}

.faq-item {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid #edf0f4;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.96);
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.faq-item:hover {
  transform: translateY(-1px);
  border-color: #dbeaff;
  box-shadow: 0 12px 24px rgba(43, 55, 77, 0.08);
}

.faq-item strong {
  color: #0f172a;
  font-size: 15px;
}

.faq-item p {
  margin: 0;
  color: #64748b;
  line-height: 1.7;
  font-size: 13px;
}

.emotion-monitor-card {
  gap: 16px;
}

.emotion-overview {
  display: grid;
  gap: 14px;
  padding: 14px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(15, 118, 110, 0.08), rgba(249, 115, 22, 0.08));
}

.emotion-head strong {
  display: block;
  font-size: 20px;
  color: #0f172a;
}

.emotion-head p,
.emotion-trend-copy p,
.emotion-preview,
.emotion-empty {
  margin: 6px 0 0;
  color: #475569;
  line-height: 1.6;
}

.emotion-meters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.emotion-meter {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.emotion-meter span,
.emotion-trend-copy strong,
.emotion-trend-hint,
.emotion-step,
.emotion-track-row span,
.emotion-trend-item small {
  color: #64748b;
  font-size: 12px;
}

.emotion-meter strong {
  display: block;
  margin-top: 4px;
  font-size: 22px;
  color: #0f172a;
}

.emotion-trend-list {
  display: grid;
  gap: 12px;
}

.emotion-trend-item {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: #fff;
}

.emotion-trend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.emotion-track-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  margin-top: 10px;
}

.emotion-track {
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.emotion-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0ea5e9, #f97316, #ef4444);
}

.emotion-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.emotion-pill.calm {
  background: rgba(14, 165, 233, 0.12);
  color: #0369a1;
}

.emotion-pill.anxious {
  background: rgba(249, 115, 22, 0.14);
  color: #c2410c;
}

.emotion-pill.dissatisfied,
.emotion-pill.angry {
  background: rgba(239, 68, 68, 0.14);
  color: #b91c1c;
}

.emotion-empty {
  padding: 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.9);
}
</style>

