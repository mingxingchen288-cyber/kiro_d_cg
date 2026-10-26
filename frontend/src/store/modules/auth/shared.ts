import { localStg, sessionStg } from '@/utils/storage';

const AUTH_IDLE_TIMEOUT_MS = 30 * 60 * 1000;
const ACTIVITY_UPDATE_THROTTLE_MS = 1000;
const USER_ACTIVITY_EVENTS: Array<keyof WindowEventMap> = ['click', 'keydown', 'mousedown', 'scroll', 'touchstart'];
export const AUTH_IDLE_TIMEOUT_EVENT = 'auth:idle-timeout';

let hasMigratedLegacyStorage = false;
let hasSetupActivityListener = false;
let lastActivityWriteAt = 0;
let inactivityCheckTimer: number | null = null;
let isAuthShutdown = false;

/** Mark that auth teardown has started so late protected request failures can be ignored. */
export function beginAuthShutdown() {
  isAuthShutdown = true;
}

/** Clear auth teardown state after a new session is established. */
export function endAuthShutdown() {
  isAuthShutdown = false;
}

/** Whether the app is tearing down the current authenticated session. */
export function isAuthShuttingDown() {
  return isAuthShutdown;
}

function migrateLegacyAuthStorage() {
  if (hasMigratedLegacyStorage) return;

  const legacyToken = localStg.get('token');
  const legacyRefreshToken = localStg.get('refreshToken');

  if (!sessionStg.get('token') && legacyToken) {
    sessionStg.set('token', legacyToken);
  }

  if (!sessionStg.get('refreshToken') && legacyRefreshToken) {
    sessionStg.set('refreshToken', legacyRefreshToken);
  }

  localStg.remove('token');
  localStg.remove('refreshToken');
  hasMigratedLegacyStorage = true;
}

function getRawToken() {
  migrateLegacyAuthStorage();
  return sessionStg.get('token') || '';
}

function getRawRefreshToken() {
  migrateLegacyAuthStorage();
  return sessionStg.get('refreshToken') || '';
}

/** Mark current auth session active */
export function markAuthActivity(force = false) {
  if (!getRawToken()) return;

  const now = Date.now();
  if (!force && now - lastActivityWriteAt < ACTIVITY_UPDATE_THROTTLE_MS) return;

  sessionStg.set('authLastActiveAt', now);
  lastActivityWriteAt = now;
}

/** Whether auth session is expired by inactivity */
export function isAuthSessionExpiredByInactivity() {
  const token = getRawToken();
  if (!token) return false;

  const lastActiveAt = sessionStg.get('authLastActiveAt');
  if (!lastActiveAt) {
    markAuthActivity(true);
    return false;
  }

  return Date.now() - lastActiveAt > AUTH_IDLE_TIMEOUT_MS;
}

function emitAuthIdleTimeout() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(AUTH_IDLE_TIMEOUT_EVENT));
}

/** Setup global user activity listeners for auth idle timeout */
export function setupAuthActivityTracking() {
  if (hasSetupActivityListener || typeof window === 'undefined') return;

  const touch = () => {
    markAuthActivity();
  };

  USER_ACTIVITY_EVENTS.forEach(event => {
    window.addEventListener(event, touch, { passive: true });
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      markAuthActivity();
    }
  });

  if (!inactivityCheckTimer) {
    inactivityCheckTimer = window.setInterval(() => {
      if (isAuthSessionExpiredByInactivity()) {
        clearAuthStorage();
        emitAuthIdleTimeout();
      }
    }, 30_000);
  }

  hasSetupActivityListener = true;
  markAuthActivity(true);
}

/** Set auth tokens */
export function setAuthTokens(token: string, refreshToken: string) {
  endAuthShutdown();
  sessionStg.set('token', token);
  sessionStg.set('refreshToken', refreshToken);
  markAuthActivity(true);
}

/** Get access token */
export function getToken() {
  const token = getRawToken();
  if (!token) return '';

  if (isAuthSessionExpiredByInactivity()) {
    clearAuthStorage();
    emitAuthIdleTimeout();
    return '';
  }

  return token;
}

/** Get refresh token */
export function getRefreshToken() {
  if (isAuthSessionExpiredByInactivity()) {
    clearAuthStorage();
    emitAuthIdleTimeout();
    return '';
  }
  return getRawRefreshToken();
}

/** Clear auth storage */
export function clearAuthStorage() {
  sessionStg.remove('token');
  sessionStg.remove('refreshToken');
  sessionStg.remove('authLastActiveAt');
  localStg.remove('token');
  localStg.remove('refreshToken');
}
