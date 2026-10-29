<script setup lang="ts">
/**
 * 顶栏的站内通知（FS-04）：铃铛上显示未读数，点击打开右侧抽屉"消息中心"（位置、铃铛、徽标、抽屉宽度沿用旧系统
 * approval-notification-center.vue）。旧抽屉里的"待审批""我的发起"属于审批，新系统由 frontend-approval 的"待办"提供，
 * 这里只列 `/api/inbox` 的通知；点击通知标为已读并按链接跳转。
 * 未读数在登录后读取一次，之后按 `notification` 事件更新，不轮询（modules/shell/inbox.ts）。
 */
import { computed, ref } from 'vue';
import { shellRuntime } from '@/modules/shell/app';
import type { InboxItem } from '@/modules/shell/inbox';

defineOptions({
  name: 'InboxBell'
});

const { inbox } = shellRuntime();

const drawerVisible = ref(false);
const showAll = ref(false);

const list = computed(() => (showAll.value ? (inbox.all.value ?? []) : inbox.items.value));

async function toggleScope() {
  showAll.value = !showAll.value;
  if (showAll.value) await run(() => inbox.loadAll());
}

async function openItem(item: InboxItem) {
  await run(async () => {
    await inbox.open(item);
    if (item.link) drawerVisible.value = false;
  });
}

async function run(action: () => Promise<void>) {
  try {
    await action();
  } catch (error) {
    window.$message?.error(error instanceof Error ? error.message : String(error));
  }
}

function formatTime(value: string) {
  return value.replace('T', ' ').slice(0, 19);
}
</script>

<template>
  <ButtonIcon tooltip-content="消息中心" @click="drawerVisible = true">
    <NBadge :value="inbox.unread.value" :show="inbox.unread.value > 0" type="error" :max="99">
      <SvgIcon icon="ph:bell" class="text-icon-large" />
    </NBadge>
  </ButtonIcon>
  <NDrawer v-model:show="drawerVisible" :width="520" placement="right">
    <NDrawerContent title="消息中心" closable>
      <div class="notice-toolbar">
        <span>{{ showAll ? '当前显示全部通知' : `当前只显示未读的通知（${inbox.unread.value} 条）` }}</span>
        <NButton size="tiny" secondary @click="toggleScope">
          {{ showAll ? '只看未读' : '查看全部' }}
        </NButton>
      </div>
      <NSpin :show="inbox.loading.value">
        <NScrollbar class="notice-scroll">
          <NEmpty v-if="list.length === 0" description="暂无消息" class="empty-state" />
          <div v-for="item in list" :key="item.deliveryId" class="notice-item">
            <div class="notice-item-head">
              <button class="notice-title" type="button" @click="openItem(item)">{{ item.title }}</button>
              <NTag size="small" :type="item.read ? 'default' : 'warning'" :bordered="false">
                {{ item.read ? '已读' : '未读' }}
              </NTag>
            </div>
            <div v-if="item.body" class="notice-item-body">{{ item.body }}</div>
            <div class="notice-item-foot">
              <span>时间：{{ formatTime(item.createdAt) }}</span>
              <NButton v-if="item.link" size="tiny" type="primary" secondary @click="openItem(item)">查看</NButton>
            </div>
          </div>
        </NScrollbar>
      </NSpin>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.notice-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
  color: #667085;
  font-size: 12px;
}

.notice-scroll {
  height: calc(100vh - 140px);
  padding-right: 4px;
}

.empty-state {
  padding-top: 80px;
}

.notice-item {
  padding: 12px 0;
  border-bottom: 1px solid #edf0f5;
}

.notice-item-head,
.notice-item-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.notice-title {
  min-width: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: #1f2937;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notice-title:hover {
  color: #3f55ff;
}

.notice-item-body {
  margin-top: 6px;
  color: #4b5565;
  font-size: 13px;
}

.notice-item-foot {
  margin-top: 10px;
  color: #667085;
  font-size: 12px;
}
</style>
