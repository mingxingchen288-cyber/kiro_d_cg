import { request } from '../request';

export function fetchUserGridConfig(pageCode: string, gridKey: string) {
  return request<any>({
    url: `/api/grid-config/${pageCode}/${gridKey}`
  });
}

export function saveUserGridConfig(pageCode: string, gridKey: string, configData: any) {
  return request<void>({
    url: `/api/grid-config/${pageCode}/${gridKey}`,
    method: 'POST',
    data: { configData }
  });
}
