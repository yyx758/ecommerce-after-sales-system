<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue';
import EmptyState from '../components/EmptyState.vue';
import {
  createKnowledgeLibrary,
  getKnowledgeLibraries,
  syncKnowledgeLibrary,
  updateKnowledgeLibrary
} from '../api/adminConsole';

const shell = inject('adminShell', null);
const loading = ref(true);
const libraries = ref([]);
const integrationPlan = ref(null);
const selectedLibraryId = ref(null);
const activeFilter = ref('ALL');

const form = reactive({
  code: '',
  name: '',
  type: 'FAQ',
  status: 'PLANNING',
  retrievalMode: 'vector_hybrid_rerank_v1',
  interfaceStatus: 'PLACEHOLDER_ONLY',
  description: ''
});

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'BUILDING', label: '建设中' },
  { key: 'READY', label: '已就绪' }
];

const selectedLibrary = computed(() => {
  return libraries.value.find((item) => item.id === selectedLibraryId.value) || null;
});

const visibleLibraries = computed(() => {
  if (activeFilter.value === 'ALL') {
    return libraries.value;
  }
  return libraries.value.filter((item) => item.status === activeFilter.value);
});

const readyInterfaceCount = computed(() => {
  return libraries.value.filter((item) => item.interfaceStatus === 'READY_FOR_API').length;
});

const editorTitle = computed(() => {
  return selectedLibrary.value ? '编辑知识库目录' : '新建知识库目录';
});

async function loadPage() {
  loading.value = true;
  try {
    const data = await getKnowledgeLibraries();
    libraries.value = data.records || [];
    integrationPlan.value = data.integrationPlan;
    if (!selectedLibraryId.value && libraries.value.length) {
      selectLibrary(libraries.value[0]);
      return;
    }
    if (selectedLibraryId.value && !libraries.value.some((item) => item.id === selectedLibraryId.value)) {
      if (libraries.value.length) {
        selectLibrary(libraries.value[0]);
      } else {
        createLibraryDraft();
      }
    }
  } finally {
    loading.value = false;
  }
}

function selectLibrary(library) {
  selectedLibraryId.value = library.id;
  Object.assign(form, {
    code: library.code,
    name: library.name,
    type: library.type,
    status: library.status,
    retrievalMode: library.retrievalMode,
    interfaceStatus: library.interfaceStatus,
    description: library.description
  });
}

function createLibraryDraft() {
  selectedLibraryId.value = null;
  Object.assign(form, {
    code: '',
    name: '',
    type: 'FAQ',
    status: 'PLANNING',
    retrievalMode: 'vector_hybrid_rerank_v1',
    interfaceStatus: 'PLACEHOLDER_ONLY',
    description: ''
  });
}

async function saveLibrary() {
  if (!form.code || !form.name) {
    shell?.setAction?.('请先填写知识库编码和名称');
    return;
  }

  if (selectedLibraryId.value) {
    await updateKnowledgeLibrary(selectedLibraryId.value, { ...form });
    shell?.setAction?.('知识库目录已更新');
  } else {
    await createKnowledgeLibrary({ ...form });
    shell?.setAction?.('知识库目录已创建');
  }
  await loadPage();
}

async function triggerSync() {
  if (!selectedLibrary.value) {
    return;
  }
  const result = await syncKnowledgeLibrary(selectedLibrary.value.id);
  shell?.setAction?.(result.message || '知识库同步任务已触发');
}

function shortText(value, limit = 22) {
  const text = String(value || '').trim();
  if (!text) {
    return '暂无说明';
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

onMounted(loadPage);
</script>

<template>
  <section class="admin-console-page">
    <aside class="admin-console-list">
      <div class="template-panel-head">
        <h2>知识库列表</h2>
        <button type="button" class="template-icon-button" aria-label="新建目录" @click="createLibraryDraft">+</button>
      </div>

      <div class="template-filter-tabs" aria-label="知识库筛选">
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

      <div v-if="visibleLibraries.length" class="template-conversation-list">
        <button
          v-for="item in visibleLibraries"
          :key="item.id"
          type="button"
          :class="['template-conversation-card', { active: item.id === selectedLibraryId }]"
          @click="selectLibrary(item)"
        >
          <span class="template-user-avatar">知</span>
          <span class="template-conversation-copy">
            <strong>{{ item.name }}</strong>
            <em>{{ item.code }}</em>
            <small>{{ shortText(item.type, 18) }}</small>
          </span>
          <span class="template-conversation-side">
            <time>{{ item.status }}</time>
            <i v-if="item.interfaceStatus === 'READY_FOR_API'" aria-hidden="true"></i>
          </span>
        </button>
      </div>
      <div v-else class="template-list-empty">
        {{ loading ? '正在加载知识库列表...' : '当前筛选下没有知识库目录' }}
      </div>

      <div class="template-list-foot">共 {{ visibleLibraries.length }} 个目录 / 已留接口 {{ readyInterfaceCount }}</div>
    </aside>

    <article class="admin-console-main">
      <header class="template-chat-head admin-console-head">
        <span class="template-user-avatar large">知</span>
        <div>
          <h2>{{ editorTitle }}</h2>
          <p>
            {{ selectedLibrary ? `当前正在编辑：${selectedLibrary.name} / ${selectedLibrary.code}` : '当前正在创建新的知识库目录' }}
          </p>
        </div>
        <span v-if="selectedLibrary" class="session-status processing">{{ selectedLibrary.status }}</span>
      </header>

      <div class="admin-console-body">
        <section class="admin-console-hero">
          <div>
            <span class="eyebrow">Editor</span>
            <h3>右侧主区域负责编辑当前选中的知识库</h3>
            <p>目录信息、检索模式、接口状态和知识说明都集中在这里，不再额外放一个右边辅助栏。</p>
          </div>
          <div class="admin-editor-badges" v-if="selectedLibrary">
            <span class="tag">{{ selectedLibrary.type }}</span>
            <span class="tag">{{ selectedLibrary.interfaceStatus }}</span>
            <span class="tag">{{ selectedLibrary.updatedAt }}</span>
          </div>
        </section>

        <section class="admin-console-form-card">
          <div class="admin-form-grid">
            <label class="admin-field">
              <span>编码</span>
              <input v-model.trim="form.code" placeholder="例如 FAQ_CENTER" />
            </label>
            <label class="admin-field">
              <span>名称</span>
              <input v-model.trim="form.name" placeholder="请输入知识库名称" />
            </label>
            <label class="admin-field">
              <span>类型</span>
              <select v-model="form.type">
                <option value="FAQ">FAQ</option>
                <option value="POLICY">售后政策</option>
                <option value="PRODUCT">商品知识</option>
                <option value="SCENE_EVIDENCE">场景证据</option>
                <option value="REPLY_TEMPLATE">回复模板</option>
              </select>
            </label>
            <label class="admin-field">
              <span>状态</span>
              <select v-model="form.status">
                <option value="PLANNING">规划中</option>
                <option value="BUILDING">建设中</option>
                <option value="READY">已就绪</option>
              </select>
            </label>
            <label class="admin-field admin-field-full">
              <span>检索模式</span>
              <input v-model.trim="form.retrievalMode" placeholder="例如 vector_hybrid_rerank_v1" />
            </label>
            <label class="admin-field admin-field-full">
              <span>接口状态</span>
              <select v-model="form.interfaceStatus">
                <option value="PLACEHOLDER_ONLY">仅占位</option>
                <option value="READY_FOR_API">已预留接口</option>
                <option value="CONNECTED">已接后端</option>
              </select>
            </label>
            <label class="admin-field admin-field-full">
              <span>说明</span>
              <textarea
                v-model="form.description"
                rows="6"
                placeholder="描述知识库负责的内容范围、文档来源、接入计划和维护方式"
              ></textarea>
            </label>
          </div>
        </section>

        <section class="admin-console-actions">
          <button type="button" class="primary-action compact" @click="saveLibrary">保存目录</button>
          <button v-if="selectedLibrary" type="button" class="ghost-mini" @click="triggerSync">触发同步接口</button>
        </section>

        <section class="admin-console-form-card" v-if="integrationPlan">
          <div class="panel-head compact">
            <div>
              <span class="eyebrow">Integration</span>
              <h3>知识库接入预留</h3>
            </div>
          </div>
          <div class="data-list">
            <article
              v-for="endpoint in integrationPlan.endpoints || []"
              :key="endpoint"
              class="data-row admin-endpoint-row"
            >
              <div class="avatar small">API</div>
              <div class="row-copy">
                <strong>{{ endpoint }}</strong>
                <span>{{ integrationPlan.status }}</span>
              </div>
            </article>
          </div>
        </section>

        <EmptyState
          v-if="!libraries.length && !loading"
          title="知识库目录还没有建立"
          desc="先创建一个知识库目录，左侧列表就会承载后续的对象切换。"
          action="创建首个目录"
          @action="createLibraryDraft"
        />
      </div>
    </article>
  </section>
</template>
