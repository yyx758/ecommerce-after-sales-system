<script setup>
import { inject, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getDashboardPerformance, getDashboardTodos, getNotices, markNoticeRead } from '../api/merchantCs';

const router = useRouter();
const shell = inject('merchantCsShell', null);
const todos = ref([]);
const notices = ref([]);
const performance = ref({ metrics: [] });

async function loadPage() {
  const [todoData, performanceData, noticeData] = await Promise.all([
    getDashboardTodos(),
    getDashboardPerformance(),
    getNotices({ page: 1, size: 20 })
  ]);
  todos.value = Array.isArray(todoData) ? todoData : [];
  performance.value = performanceData || { metrics: [] };
  notices.value = Array.isArray(noticeData) ? noticeData : [];
}

async function openNotice(notice) {
  if (!notice?.id) {
    return;
  }
  try {
    if (notice.readStatus !== 'READ') {
      await markNoticeRead(notice.id);
      notice.readStatus = 'READ';
    }
  } catch (error) {
    console.warn('Failed to mark notice as read', error);
  }
  router.push(notice.target || '/notices');
}

onMounted(loadPage);
</script>

<template>
  <section class="work-page two-column notice-workbench">
    <article class="wide-panel notice-list-panel">
      <div class="panel-head">
        <div>
          <span class="eyebrow">消息通知</span>
          <h2>待办与预警</h2>
        </div>
      </div>

      <div class="data-list">
        <button
          v-for="notice in notices"
          :key="notice.id"
          type="button"
          class="data-row notice-row"
          @click="openNotice(notice)"
        >
          <span class="notice-level">{{ notice.level }}</span>
          <span class="row-copy">
            <strong>{{ notice.title }}</strong>
            <span>{{ notice.content }}</span>
          </span>
          <span class="muted">{{ notice.readStatus === 'READ' ? '已读' : '查看' }}</span>
        </button>

        <RouterLink v-for="item in todos" :key="item.id" :to="item.target" class="data-row notice-row">
          <span class="todo-dot"></span>
          <span class="row-copy">
            <strong>{{ item.title }}</strong>
            <span>{{ item.tag }} / {{ item.amount }}</span>
          </span>
          <span class="muted">处理</span>
        </RouterLink>

        <div v-if="!notices.length && !todos.length" class="data-row notice-row empty-row">
          <span class="row-copy">
            <strong>暂无通知</strong>
            <span>当前没有需要处理的通知或待办。</span>
          </span>
        </div>
      </div>
    </article>

    <aside class="side-panel notice-performance-panel">
      <span class="eyebrow">服务表现</span>
      <div v-for="item in performance.metrics" :key="item.label" class="performance-row">
        <strong>{{ item.value }}</strong>
        <span>{{ item.label }} / {{ item.desc }}</span>
      </div>
      <button type="button" class="ghost-action" @click="shell?.setAction('通知筛选和已读接口后续接入')">
        标记全部已读
      </button>
    </aside>
  </section>
</template>
