/**
 * AG Grid 模块注册
 * 在应用启动时全局注册，企业版功能通过 try/catch 动态加载
 * 企业版授权从环境变量 VITE_AG_GRID_LICENSE_KEY 读取，不写进代码
 */
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';

export async function setupAgGrid() {
  // 默认注册社区版模块
  ModuleRegistry.registerModules([AllCommunityModule]);

  try {
    // 动态导入企业版模块
    const { AllEnterpriseModule, LicenseManager } = await import('ag-grid-enterprise');

    // 设置授权；未配置时不调用
    const licenseKey = import.meta.env.VITE_AG_GRID_LICENSE_KEY;
    if (licenseKey) {
      LicenseManager.setLicenseKey(licenseKey);
    }

    // 注册企业版模块（会覆盖社区版）
    ModuleRegistry.registerModules([AllEnterpriseModule]);
  } catch {
    console.warn('⚠️ AG Grid 企业版未安装，使用社区版功能');
  }
}
