<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useAuthStore } from '@/store/modules/auth';
import { useRouterPush } from '@/hooks/common/router';
import { useFormRules, useNaiveForm } from '@/hooks/common/form';
import { $t } from '@/locales';

defineOptions({
  name: 'PwdLogin'
});

const REMEMBER_KEY = 'cost_remember_user';

const authStore = useAuthStore();
const { toggleLoginModule } = useRouterPush();
const { formRef, validate } = useNaiveForm();

interface FormModel {
  userName: string;
  password: string;
}

const rememberMe = ref(false);

const model: FormModel = reactive({
  userName: 'admin',
  password: ''
});

// 初始化时检查是否有记住的用户名
onMounted(() => {
  const remembered = localStorage.getItem(REMEMBER_KEY);
  if (remembered) {
    model.userName = remembered;
    rememberMe.value = true;
  }
});

const rules = computed<Record<keyof FormModel, App.Global.FormRule[]>>(() => {
  const { formRules } = useFormRules();

  return {
    userName: formRules.userName,
    password: formRules.pwd
  };
});

async function handleSubmit() {
  await validate();

  // 根据记住我选项保存或清除用户名
  if (rememberMe.value) {
    localStorage.setItem(REMEMBER_KEY, model.userName);
  } else {
    localStorage.removeItem(REMEMBER_KEY);
  }

  await authStore.login(model.userName, model.password);
}
</script>

<template>
  <NForm ref="formRef" :model="model" :rules="rules" size="large" :show-label="false" @keyup.enter="handleSubmit">
    <NFormItem path="userName">
      <NInput v-model:value="model.userName" :placeholder="$t('page.login.common.userNamePlaceholder')" />
    </NFormItem>
    <NFormItem path="password">
      <NInput
        v-model:value="model.password"
        type="password"
        show-password-on="click"
        :placeholder="$t('page.login.common.passwordPlaceholder')"
      />
    </NFormItem>
    <NSpace vertical :size="24">
      <div class="flex-y-center justify-between">
        <NCheckbox v-model:checked="rememberMe">{{ $t('page.login.pwdLogin.rememberMe') }}</NCheckbox>
        <NButton quaternary @click="toggleLoginModule('reset-pwd')">
          {{ $t('page.login.pwdLogin.forgetPassword') }}
        </NButton>
      </div>
      <NButton type="primary" size="large" round block :loading="authStore.loginLoading" @click="handleSubmit">
        {{ $t('common.confirm') }}
      </NButton>
      <NButton class="w-full" block @click="toggleLoginModule('register')">
        {{ $t('page.login.register.title') }}
      </NButton>
    </NSpace>
  </NForm>
</template>

<style scoped></style>
