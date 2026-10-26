<script setup lang="ts">
import { useThemeStore } from '@/store/modules/theme';
import { $t } from '@/locales';
import SettingItem from '../../../components/setting-item.vue';

defineOptions({
  name: 'DetailViewModeSettings'
});

const themeStore = useThemeStore();

const options = [
  { label: () => $t('theme.layout.detailViewMode.tab'), value: 'tab' },
  { label: () => $t('theme.layout.detailViewMode.stack'), value: 'stack' }
];
</script>

<template>
  <NDivider>{{ $t('theme.layout.detailViewMode.title') }}</NDivider>
  <div class="flex-col-stretch gap-12px">
    <SettingItem :label="$t('theme.layout.detailViewMode.title')">
      <NSelect
        :value="themeStore.detailViewMode"
        :options="options"
        size="small"
        class="w-120px"
        @update:value="themeStore.setDetailViewMode"
      />
    </SettingItem>
  </div>
</template>

<style scoped></style>
