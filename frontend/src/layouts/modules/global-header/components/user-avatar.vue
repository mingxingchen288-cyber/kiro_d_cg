<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import type { VNode } from 'vue';
import { useFormRules, useNaiveForm } from '@/hooks/common/form';
import { useAuthStore } from '@/store/modules/auth';
import { useRouterPush } from '@/hooks/common/router';
import { useSvgIcon } from '@/hooks/common/icon';
import { fetchChangePassword } from '@/service/api';
import { $t } from '@/locales';

defineOptions({
  name: 'UserAvatar'
});

const authStore = useAuthStore();
const { routerPushByKey, toLogin } = useRouterPush();
const { SvgIconVNode } = useSvgIcon();
const { formRef, validate, restoreValidation } = useNaiveForm();

const showChangePasswordModal = ref(false);
const submitLoading = ref(false);

interface ChangePasswordModel {
  password: string;
  confirmPassword: string;
}

const changePasswordModel: ChangePasswordModel = reactive({
  password: '',
  confirmPassword: ''
});

const changePasswordRules = computed<Partial<Record<keyof ChangePasswordModel, App.Global.FormRule[]>>>(() => {
  const { formRules, createConfirmPwdRule } = useFormRules();

  return {
    password: formRules.pwd,
    confirmPassword: createConfirmPwdRule(changePasswordModel.password)
  };
});

function loginOrRegister() {
  toLogin();
}

type DropdownKey = 'changePassword' | 'logout';

type DropdownOption =
  | {
      key: DropdownKey;
      label: string;
      icon?: () => VNode;
    }
  | {
      type: 'divider';
      key: string;
    };

const options = computed(() => {
  const opts: DropdownOption[] = [
    {
      label: $t('common.changePassword'),
      key: 'changePassword',
      icon: SvgIconVNode({ icon: 'ph:key', fontSize: 18 })
    },
    {
      type: 'divider',
      key: 'divider-change-password'
    },
    {
      label: $t('common.logout'),
      key: 'logout',
      icon: SvgIconVNode({ icon: 'ph:sign-out', fontSize: 18 })
    }
  ];

  return opts;
});

function logout() {
  window.$dialog?.info({
    title: $t('common.tip'),
    content: $t('common.logoutConfirm'),
    positiveText: $t('common.confirm'),
    negativeText: $t('common.cancel'),
    onPositiveClick: () => {
      authStore.resetStore({ preserveRedirect: false });
    }
  });
}

function resetChangePasswordForm() {
  changePasswordModel.password = '';
  changePasswordModel.confirmPassword = '';
  restoreValidation();
}

function openChangePasswordModal() {
  resetChangePasswordForm();
  showChangePasswordModal.value = true;
}

function closeChangePasswordModal() {
  showChangePasswordModal.value = false;
  resetChangePasswordForm();
}

async function submitChangePassword() {
  await validate();
  submitLoading.value = true;

  const { error } = await fetchChangePassword(changePasswordModel.password);

  submitLoading.value = false;

  if (!error) {
    window.$message?.success($t('common.modifySuccess'));
    closeChangePasswordModal();
  }
}

function handleDropdown(key: DropdownKey) {
  if (key === 'changePassword') {
    openChangePasswordModal();
  } else if (key === 'logout') {
    logout();
  } else {
    // If your other options are jumps from other routes, they will be directly supported here
    routerPushByKey(key);
  }
}
</script>

<template>
  <NButton v-if="!authStore.isLogin" quaternary @click="loginOrRegister">
    {{ $t('page.login.common.loginOrRegister') }}
  </NButton>
  <NDropdown v-else placement="bottom" trigger="click" :options="options" @select="handleDropdown">
    <div>
      <ButtonIcon>
        <SvgIcon icon="ph:user-circle" class="text-icon-large" />
        <span class="text-16px font-medium">{{ authStore.userInfo.userName }}</span>
      </ButtonIcon>
    </div>
  </NDropdown>
  <NModal v-model:show="showChangePasswordModal" preset="card" :title="$t('common.changePassword')" class="w-420px">
    <NForm
      ref="formRef"
      :model="changePasswordModel"
      :rules="changePasswordRules"
      size="large"
      :show-label="false"
      @keyup.enter="submitChangePassword"
    >
      <NFormItem path="password">
        <NInput
          v-model:value="changePasswordModel.password"
          type="password"
          show-password-on="click"
          :placeholder="$t('page.login.common.passwordPlaceholder')"
        />
      </NFormItem>
      <NFormItem path="confirmPassword">
        <NInput
          v-model:value="changePasswordModel.confirmPassword"
          type="password"
          show-password-on="click"
          :placeholder="$t('page.login.common.confirmPasswordPlaceholder')"
        />
      </NFormItem>
      <NSpace justify="end">
        <NButton @click="closeChangePasswordModal">
          {{ $t('common.cancel') }}
        </NButton>
        <NButton type="primary" :loading="submitLoading" @click="submitChangePassword">
          {{ $t('common.confirm') }}
        </NButton>
      </NSpace>
    </NForm>
  </NModal>
</template>

<style scoped></style>
