import { addCollection } from '@iconify/vue';

// 导入本地图标集
import materialSymbols from '@iconify-json/material-symbols/icons.json';
import heroicons from '@iconify-json/heroicons/icons.json';
import lineMd from '@iconify-json/line-md/icons.json';
import majesticons from '@iconify-json/majesticons/icons.json';
import ph from '@iconify-json/ph/icons.json';
import mdi from '@iconify-json/mdi/icons.json';
import antDesign from '@iconify-json/ant-design/icons.json';
import carbon from '@iconify-json/carbon/icons.json';

/** Setup the iconify offline */
export function setupIconifyOffline() {
  // 加载本地图标集
  addCollection(materialSymbols);
  addCollection(heroicons);
  addCollection(lineMd);
  addCollection(majesticons);
  addCollection(ph);
  addCollection(mdi);
  addCollection(antDesign);
  addCollection(carbon);
}
