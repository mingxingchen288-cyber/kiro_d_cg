<script setup lang="ts">
/**
 * 选角色（C09 `POST /api/auth/role`，FS-02）：账号有多个角色时，登录后在登录卡片里选一个角色再进入；
 * 只有一个角色的账号登录时已自动选定，不出现这一步。旧系统没有选角色，卡片样式沿用密码登录。
 * "返回登录"注销这次登录（`POST /api/auth/logout`），回到密码登录。
 */
import { ref, watch } from 'vue';
import { useAuthStore } from '@/store/modules/auth';
import { $t } from '@/locales';

defineOptions({
  name: 'RoleSelect'
});

const authStore = useAuthStore();

const selected = ref<string | null>(authStore.roles[0]?.code ?? null);

watch(
  () => authStore.roles,
  roles => {
    if (!roles.some(role => role.code === selected.value)) selected.value = roles[0]?.code ?? null;
  }
);

async function handleSubmit() {
  if (!selected.value) {
    window.$message?.warning('请选择角色');
    return;
  }
  await authStore.selectRole(selected.value);
}
</script>

<template>
  <div>
    <p class="pb-12px text-14px text-#666">
      {{ authStore.userInfo.realName || authStore.userInfo.userName }}，你的账号有多个角色，请选择这次使用的角色：
    </p>
    <NRadioGroup v-model:value="selected" class="w-full">
      <NSpace vertical :size="12">
        <NRadio v-for="role in authStore.roles" :key="role.code" :value="role.code" :label="role.name" />
      </NSpace>
    </NRadioGroup>
    <NSpace vertical :size="12" class="pt-24px">
      <NButton type="primary" size="large" round block :loading="authStore.loginLoading" @click="handleSubmit">
        {{ $t('common.confirm') }}
      </NButton>
      <NButton text block @click="authStore.logout">返回登录</NButton>
    </NSpace>
  </div>
</template>

<style scoped></style>
