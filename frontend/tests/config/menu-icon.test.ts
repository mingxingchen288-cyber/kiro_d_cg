/**
 * 菜单图标（FC-16，C06 v26 菜单项的 `icon`）：配置页"目录信息"和页面"基本信息"里选图标，保存到 `menu` 配置项。
 * 选项同旧系统 SectionBasicInfo.vue 第 33–54 行的 20 个常用图标，可以输入别的；旧菜单资源的图标（cmx `T_COST_RESOURCE.ICON`，
 * 例如物料成本核算表 mdi:calculator-variant、基础信息 mdi:currency-usd）原样能用。
 */
import { describe, expect, it } from 'vitest';
import type { MenuNode } from '../../src/modules/config/core/types';
import {
  ICON_OPTIONS,
  iconOfNode,
  iconOptions,
  menuItemOfPage,
  setNodeIcon
} from '../../src/modules/config/views/menu-tree';

/** d_cg 的 menu.main（版本 3，`.reports/batch8-20261031/g4-admin-shell/02-d_cg菜单.out.txt`） */
function mainMenu(): MenuNode[] {
  return [
    {
      key: 'cost',
      title: '成本',
      kind: 'group',
      children: [{ key: 'COST_PINGGU', title: '成本核算', kind: 'page', pageCode: 'COST_PINGGU' }]
    },
    {
      key: 'basic',
      title: '基础信息',
      kind: 'group',
      children: [{ key: 'GOODS_PRICE_MANAGE', title: '物料清单及成本', kind: 'page', pageCode: 'GOODS_PRICE_MANAGE' }]
    },
    { key: 'config', title: '配置', kind: 'config' },
    { key: 'admin', title: '系统管理', kind: 'admin' }
  ];
}

describe('菜单图标', () => {
  it('常用图标是旧系统的 20 个；输入的图标也在选项里', () => {
    expect(ICON_OPTIONS).toHaveLength(20);
    expect(ICON_OPTIONS.map(o => o.value)).toContain('mdi:calculator-variant');
    expect(iconOptions('mdi:calculator-variant')).toBe(ICON_OPTIONS);
    expect(iconOptions('mdi:domain').at(-1)).toEqual({ label: 'mdi:domain', value: 'mdi:domain' });
  });

  it('分组"基础信息"选 mdi:currency-usd、清空后去掉 icon；其他项不变', () => {
    const items = mainMenu();
    expect(setNodeIcon(items, 'basic', 'mdi:currency-usd')).toBe(true);
    expect(iconOfNode(items, 'basic')).toBe('mdi:currency-usd');
    expect(items[0]).toEqual(mainMenu()[0]);

    setNodeIcon(items, 'basic', null);
    expect(items[1]).toEqual(mainMenu()[1]);
    expect('icon' in items[1]).toBe(false);
    expect(setNodeIcon(items, 'NO_SUCH', 'mdi:folder')).toBe(false);
  });

  it('页面"成本核算"的图标改在它所在的菜单项 COST_PINGGU 上', () => {
    const menus = [{ key: 'main', content: { items: mainMenu() } }];
    const place = menuItemOfPage(menus, 'COST_PINGGU');
    expect(place).toEqual({ menuKey: 'main', nodeKey: 'COST_PINGGU' });
    setNodeIcon(menus[0].content.items, place!.nodeKey, 'mdi:calculator-variant');
    expect(menus[0].content.items[0].children![0]).toEqual({
      key: 'COST_PINGGU',
      title: '成本核算',
      kind: 'page',
      pageCode: 'COST_PINGGU',
      icon: 'mdi:calculator-variant'
    });
    expect(menuItemOfPage(menus, 'GOODS_MANAGE')).toBeNull();
  });
});
