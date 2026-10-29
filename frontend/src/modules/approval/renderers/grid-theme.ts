/**
 * 审批表格的 AG Grid 主题：沿用旧系统 `ApprovalDetailDialog.vue` 的 `.approval-simple-grid` 和
 * `ApprovalPresentationGrid.vue` 的 `.approval-presentation-grid`（12px 字号、表头底色 #f2f4f7、边框 #e4e7ed、外框直角、
 * 行高和表头高 32）。旧系统用 legacy 主题加 CSS 变量，这里用 AG Grid 35 的 Theming API 写同样的参数。
 */
import { themeQuartz } from 'ag-grid-community';

const common = {
  fontFamily: 'inherit',
  fontSize: 12,
  headerBackgroundColor: '#f2f4f7',
  borderColor: '#e4e7ed',
  wrapperBorderRadius: 0,
  rowHeight: 32,
  headerHeight: 32
} as const;

/** 审批进度、待办列表 */
export const simpleTheme = themeQuartz.withParams(common);

/** 修改内容、受影响单据：格子左右留 10px，悬停不变色 */
export const presentationTheme = themeQuartz.withParams({
  ...common,
  cellHorizontalPadding: 10,
  rowHoverColor: 'transparent'
});

export const ROW_HEIGHT = 32;
export const HEADER_HEIGHT = 32;

/** 行数少时随内容撑开，多时固定高度并按行虚拟滚动（同旧系统 simpleGridLayout） */
export function gridLayout(rowCount: number, maxHeight: number) {
  const auto = rowCount > 0 && rowCount * ROW_HEIGHT + HEADER_HEIGHT + 2 <= maxHeight;
  return {
    domLayout: auto ? ('autoHeight' as const) : ('normal' as const),
    style: auto ? undefined : { height: `${rowCount ? maxHeight : ROW_HEIGHT * 2 + 2}px` }
  };
}
