/** 投递记录的正向流程：列出、按状态筛选、已放弃的记录重新排队（FM-03） */
import { describe, expect, it } from 'vitest';
import { DeliveriesModel, canRequeue } from '../../src/modules/admin/deliveries';
import { openAdmin } from './support';

async function openDeliveries() {
  const ctx = openAdmin();
  const model = new DeliveriesModel(ctx.deps);
  await model.load();
  return { ...ctx, model };
}

describe('投递记录', () => {
  it('列出全部状态，按状态筛选', async () => {
    const { model, http } = await openDeliveries();
    expect(http.callsTo('GET', '/api/admin/deliveries')[0].options?.query).toEqual({
      status: undefined,
      startRow: 0,
      endRow: 50
    });
    expect(model.state.rows.map(r => r.status)).toEqual(['abandoned', 'sent']);
    expect(model.state.total).toBe(2);

    await model.setStatus('abandoned');
    expect(http.callsTo('GET', '/api/admin/deliveries').at(-1)?.options?.query?.status).toBe('abandoned');
    expect(model.state.rows.map(r => r.recipient)).toEqual(['343']);
  });

  it('FM-03：只有已放弃的记录能重新排队，重新排队后状态回到待发送', async () => {
    const { model, http, messages } = await openDeliveries();
    const [abandoned, sent] = model.state.rows;
    expect(canRequeue(abandoned)).toBe(true);
    expect(canRequeue(sent)).toBe(false);

    expect(await model.requeue(abandoned)).toBe(true);
    expect(http.callsTo('POST', '/api/admin/deliveries/:deliveryId/requeue').map(c => c.params.deliveryId)).toEqual([
      '3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c'
    ]);
    expect(messages).toContainEqual({ kind: 'success', text: '已重新排队' });
    expect(model.state.rows[0]).toMatchObject({ deliveryId: abandoned.deliveryId, status: 'pending' });
  });
});
