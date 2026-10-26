<script setup lang="ts">
import { useThemeStore } from '@/store/modules/theme';
import { $t } from '@/locales';
import SettingItem from '../../../components/setting-item.vue';

defineOptions({
  name: 'MasterDetailModeSettings'
});

const themeStore = useThemeStore();

const options = [
  { label: () => $t('theme.layout.masterDetailMode.masterDetail'), value: 'master-detail' },
  { label: () => $t('theme.layout.masterDetailMode.split'), value: 'split' }
];
</script>

<template>
  <NDivider>{{ $t('theme.layout.masterDetailMode.title') }}</NDivider>
  <div class="flex-col-stretch gap-12px">
    <SettingItem :label="$t('theme.layout.masterDetailMode.title')">
      <NSelect
        :value="themeStore.masterDetailMode"
        :options="options"
        size="small"
        class="w-120px"
        @update:value="themeStore.setMasterDetailMode"
      />
    </SettingItem>
  </div>
</template>

<style scoped></style>
