<script setup lang="ts">
/**
 * 表单布局拖动编辑（FC-03）：24 列网格，拖动字段块移动，拖右下角缩放；按整列、整行取整，不超出 24 列（规则在 form-layout.ts）。
 * 模块说明指定 grid-layout-plus，项目没有安装（见 contract-gaps），这里用指针事件实现同样的交互。
 */
import { onBeforeUnmount, ref } from 'vue';
import { GRID_COLUMNS, type FormLayoutModel, toGrid } from './form-layout';

const props = defineProps<{ model: FormLayoutModel; labels: Record<string, string> }>();
const ROW_HEIGHT = 44;
const canvas = ref<HTMLDivElement>();
let drag: { field: string; mode: 'move' | 'resize'; x0: number; y0: number; cx: number; cy: number; cw: number; ch: number; lastX: number; lastY: number } | null = null;

const colWidth = () => (canvas.value?.clientWidth ?? 960) / GRID_COLUMNS;

function start(event: PointerEvent, field: string, mode: 'move' | 'resize') {
  if (!props.model.state.editing) return;
  const cell = props.model.state.cells.find(c => c.field === field);
  if (!cell) return;
  event.preventDefault();
  event.stopPropagation();
  drag = { field, mode, x0: event.clientX, y0: event.clientY, cx: cell.x, cy: cell.y, cw: cell.w, ch: cell.h, lastX: 0, lastY: 0 };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', end);
}

function move(event: PointerEvent) {
  if (!drag) return;
  const dx = toGrid(event.clientX - drag.x0, colWidth());
  const dy = toGrid(event.clientY - drag.y0, ROW_HEIGHT);
  if (dx === drag.lastX && dy === drag.lastY) return;
  drag.lastX = dx;
  drag.lastY = dy;
  if (drag.mode === 'move') props.model.move(drag.field, drag.cx + dx, drag.cy + dy);
  else props.model.resize(drag.field, drag.cw + dx, drag.ch + dy);
}

function end() {
  drag = null;
  window.removeEventListener('pointermove', move);
  window.removeEventListener('pointerup', end);
}

onBeforeUnmount(end);

const rows = () => Math.max(3, ...props.model.state.cells.map(c => c.y + c.h)) + (props.model.state.editing ? 1 : 0);
</script>

<template>
  <div ref="canvas" class="layout-canvas" :class="{ editing: model.state.editing }" :style="{ height: `${rows() * ROW_HEIGHT}px` }">
    <template v-if="model.state.editing">
      <div v-for="i in GRID_COLUMNS" :key="i" class="grid-col" :style="{ left: `${((i - 1) / GRID_COLUMNS) * 100}%`, width: `${100 / GRID_COLUMNS}%` }" />
    </template>
    <div
      v-for="cell in model.state.cells"
      :key="cell.field"
      class="layout-item"
      :style="{ left: `${(cell.x / GRID_COLUMNS) * 100}%`, width: `${(cell.w / GRID_COLUMNS) * 100}%`, top: `${cell.y * ROW_HEIGHT}px`, height: `${cell.h * ROW_HEIGHT - 6}px` }"
      @pointerdown="e => start(e, cell.field, 'move')"
    >
      <span class="item-label">{{ labels[cell.field] ?? cell.field }}</span>
      <span class="item-meta">x{{ cell.x }} · w{{ cell.w }}<template v-if="cell.h > 1"> · h{{ cell.h }}</template></span>
      <button v-if="model.state.editing" class="item-remove" title="移出表单" @pointerdown.stop @click="model.remove(cell.field)">×</button>
      <span v-if="model.state.editing" class="resize-handle" @pointerdown="e => start(e, cell.field, 'resize')" />
    </div>
  </div>
</template>

<style scoped>
.layout-canvas { position: relative; width: 100%; border: 1px solid #dce2e9; background: #fff; user-select: none; }
.layout-canvas.editing { background: #fafcff; }
.grid-col { position: absolute; top: 0; bottom: 0; border-left: 1px dashed #edf0f5; }
.layout-item { position: absolute; margin-top: 3px; box-sizing: border-box; padding: 4px 8px; border: 1px solid #c8d4e3; border-radius: 4px; background: #f5f7fa; display: flex; align-items: center; gap: 8px; overflow: hidden; }
.editing .layout-item { cursor: move; border-color: #2080f0; background: #e8f2ff; }
.item-label { font-size: 13px; color: #333; white-space: nowrap; }
.item-meta { font-size: 11px; color: #999; white-space: nowrap; }
.item-remove { margin-left: auto; border: none; background: transparent; color: #d03050; cursor: pointer; font-size: 14px; }
.resize-handle { position: absolute; right: 0; bottom: 0; width: 10px; height: 10px; cursor: se-resize; background: linear-gradient(135deg, transparent 50%, #2080f0 50%); }
</style>
