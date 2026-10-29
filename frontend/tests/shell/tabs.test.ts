/**
 * 页签的未保存确认（FS-03，C11 `tabs.setDirty`）：通用页面有未保存修改时把页签标为 dirty，关闭前先确认。
 * 页签按路径区分，例如成本核算页 `/page/COST_PINGGU`、物料清单及成本页 `/page/GOODS_PRICE_MANAGE`。
 */
import { describe, expect, it } from 'vitest';
import { DirtyTabs, closeConfirmText } from '../../src/modules/shell/tabs';

const cost = { id: '/page/COST_PINGGU', label: '成本核算' };
const goods = { id: '/page/GOODS_PRICE_MANAGE', label: '物料清单及成本' };

function confirmer(answer: boolean) {
  const asked: string[][] = [];
  const confirm = (labels: string[]) => {
    asked.push(labels);
    return Promise.resolve(answer);
  };
  return { asked, confirm };
}

describe('关闭有未保存修改的页签（FS-03）', () => {
  it('成本核算页改了没保存：关闭前确认；选"取消"时不关闭，修改标记还在', async () => {
    const tabs = new DirtyTabs();
    tabs.set(cost.id, true);
    const { asked, confirm } = confirmer(false);

    expect(await tabs.confirmClose([cost], confirm)).toBe(false);
    expect(asked).toEqual([['成本核算']]);
    expect(tabs.isDirty(cost.id)).toBe(true);
  });

  it('选"确定关闭"时关闭，标记清掉', async () => {
    const tabs = new DirtyTabs();
    tabs.set(cost.id, true);
    const { confirm } = confirmer(true);

    expect(await tabs.confirmClose([cost], confirm)).toBe(true);
    expect(tabs.isDirty(cost.id)).toBe(false);
  });

  it('保存后页面把标记去掉：关闭时不再确认', async () => {
    const tabs = new DirtyTabs();
    tabs.set(cost.id, true);
    tabs.set(cost.id, false);
    const { asked, confirm } = confirmer(false);

    expect(await tabs.confirmClose([cost], confirm)).toBe(true);
    expect(asked).toEqual([]);
  });

  it('"关闭其他"一次关两个页签，只有成本核算有修改：只确认一次，只列出成本核算', async () => {
    const tabs = new DirtyTabs();
    tabs.set(cost.id, true);
    const { asked, confirm } = confirmer(true);

    expect(await tabs.confirmClose([goods, cost], confirm)).toBe(true);
    expect(asked).toEqual([['成本核算']]);
    expect(closeConfirmText(asked[0])).toBe('页签"成本核算"有未保存的修改，关闭后这些修改会丢失。确定关闭吗？');
  });
});
