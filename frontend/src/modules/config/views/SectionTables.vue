<script setup lang="ts">
/** 表与列，同旧系统 SectionTables.vue：主表和每张明细各一个折叠项"主表: 实体 (标题)""从表: …" */
import { onMounted, ref } from 'vue';
import { NCollapse, NCollapseItem } from 'naive-ui';
import type { PageCatalog } from '../core/catalog';
import { useConfigContext } from '../core/context';
import type { ItemEditor } from '../core/item-editor';
import TableFieldsCard from './TableFieldsCard.vue';

const props = defineProps<{ page: ItemEditor<'page'>; catalog: PageCatalog }>();
const emit = defineEmits<{ reload: [] }>();
const { store } = useConfigContext();
const dicts = ref<Array<{ label: string; value: string }>>([]);
const lookups = ref<Array<{ label: string; value: string }>>([]);
const content = () => props.page.state.current!.content;
const areaOf = (index: number) => (index === 0 ? content().master : content().details![index - 1]);

onMounted(async () => {
  const [d, l] = await Promise.all([store.list('dict'), store.list('lookup')]);
  dicts.value = d.map(x => ({ label: `${x.name} · ${x.key}`, value: x.key }));
  lookups.value = l.map(x => ({ label: `${x.name} · ${x.key}`, value: x.key }));
});
</script>

<template>
  <div class="section-tables">
    <NCollapse :default-expanded-names="[catalog.tables[0]?.entity]">
      <NCollapseItem v-for="(table, index) in catalog.tables" :key="table.entity" :title="`${table.isMaster ? '主表' : '从表'}: ${table.entity} (${table.title})`" :name="table.entity">
        <template #header-extra><span class="col-count">{{ table.fields.length }} 列 · {{ table.table }}</span></template>
        <TableFieldsCard :page="page" :table="table" :area="areaOf(index)" :dicts="dicts" :lookups="lookups" @reload="emit('reload')" />
      </NCollapseItem>
    </NCollapse>
  </div>
</template>

<style scoped>
.section-tables { padding: 8px 0; }
.col-count { font-size: 12px; color: #999; }
</style>
