<script setup lang="ts">
import { ref, watch } from 'vue';
import { useEventListener, useFullscreen } from '@vueuse/core';
import { GLOBAL_HEADER_MENU_ID } from '@/constants/app';
import { useAppStore } from '@/store/modules/app';
import { useThemeStore } from '@/store/modules/theme';
import GlobalLogo from '../global-logo/index.vue';
import ThemeButton from './components/theme-button.vue';
import UserAvatar from './components/user-avatar.vue';

defineOptions({
  name: 'GlobalHeader'
});

interface Props {
  /** Whether to show the logo */
  showLogo?: App.Global.HeaderProps['showLogo'];
  /** Whether to show the menu toggler */
  showMenuToggler?: App.Global.HeaderProps['showMenuToggler'];
  /** Whether to show the menu */
  showMenu?: App.Global.HeaderProps['showMenu'];
}

defineProps<Props>();
defineSlots<{
  default?: () => any;
}>();

const appStore = useAppStore();
const themeStore = useThemeStore();
const { isFullscreen, isSupported, enter, exit } = useFullscreen();
const fullscreenFallbackActive = ref(false);

async function toggleUltimateFullscreen() {
  if (isFullscreen.value || document.fullscreenElement) {
    fullscreenFallbackActive.value = false;
    appStore.setFullContent(false);
    if (document.fullscreenElement) {
      await exit();
    }
    return;
  }

  if (fullscreenFallbackActive.value && appStore.fullContent) {
    fullscreenFallbackActive.value = false;
    appStore.setFullContent(false);
    return;
  }

  appStore.setFullContent(true);

  if (!isSupported.value) {
    fullscreenFallbackActive.value = true;
    return;
  }

  try {
    await enter();
    fullscreenFallbackActive.value = false;
  } catch {
    fullscreenFallbackActive.value = true;
    // Keep content fullscreen as a mobile/browser fallback when Fullscreen API is denied.
  }
}

// 监听全屏状态变化，触发 resize 让 AG Grid 重新计算尺寸
watch(isFullscreen, () => {
  setTimeout(() => {
    window.dispatchEvent(new Event('resize'));
  }, 350);
});

useEventListener(document, 'fullscreenchange', () => {
  fullscreenFallbackActive.value = false;
  appStore.setFullContent(Boolean(document.fullscreenElement));
});
</script>

<template>
  <DarkModeContainer class="h-full flex-y-center px-12px shadow-header">
    <GlobalLogo v-if="showLogo" class="h-full" :style="{ width: themeStore.sider.width + 'px' }" />
    <MenuToggler v-if="showMenuToggler" :collapsed="appStore.siderCollapse" @click="appStore.toggleSiderCollapse" />
    <div class="h-full flex-y-center flex-1-hidden">
      <slot>
        <div v-if="showMenu" :id="GLOBAL_HEADER_MENU_ID" class="h-full flex-y-center flex-1-hidden"></div>
      </slot>
    </div>
    <div class="h-full flex-y-center justify-end">
      <FullScreen :full="isFullscreen || appStore.fullContent" @click="toggleUltimateFullscreen" />
      <ThemeButton />
      <UserAvatar />
    </div>
  </DarkModeContainer>
</template>

<style scoped></style>
