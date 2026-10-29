/**
 * 管理功能被切回来时（系统管理的页签、外壳的页签都只是隐藏、不卸载）调用 `refresh`，第一次显示不调用（打开时已读取）。
 * 用来重新读取别处会新建的选项：部门管理新建的部门、配置的角色权限里新建的角色。
 */
import { type Ref, watch } from 'vue';
import { useElementVisibility } from '@vueuse/core';

export function onShownAgain(target: Ref<HTMLElement | null>, refresh: () => void) {
  const visible = useElementVisibility(target);
  let shownBefore = false;
  watch(visible, shown => {
    if (!shown) return;
    if (shownBefore) refresh();
    shownBefore = true;
  });
}
