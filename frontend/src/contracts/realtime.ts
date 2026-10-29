/** C10 实时事件。后端同名类型在 types.py 的"C10 实时事件"一节。 */
import {
  type Infer,
  array,
  code,
  decimalText,
  int,
  literal,
  nullable,
  object,
  oneOf,
  str,
  tagged,
  uuid
} from './schema';

export const PagesAudience = object('PagesAudience', { pages: array(code) });
export const UsersAudience = object('UsersAudience', { users: array(decimalText) });
export const SessionsAudience = object('SessionsAudience', { sessions: array(str) });

export const ConfigChangedPayload = object('ConfigChangedPayload', { pages: array(code), version: int });
export type ConfigChangedPayload = Infer<typeof ConfigChangedPayload>;
export const NotificationPayload = object('NotificationPayload', {
  deliveryId: uuid,
  title: str,
  body: str,
  link: nullable(str)
});
export type NotificationPayload = Infer<typeof NotificationPayload>;
export const SessionRevokedPayload = object('SessionRevokedPayload', {
  reason: literal('accountDisabled', 'roleRevoked', 'loggedOut')
});
export type SessionRevokedPayload = Infer<typeof SessionRevokedPayload>;

// ---- 第 1 节 后端进程之间：Redis 频道

export const ConfigChangedEvent = object('ConfigChangedEvent', {
  eventId: uuid,
  topic: literal('config.changed'),
  audience: PagesAudience,
  payload: ConfigChangedPayload
});
export const NotificationEvent = object('NotificationEvent', {
  eventId: uuid,
  topic: literal('notification'),
  audience: UsersAudience,
  payload: NotificationPayload
});
export const SessionRevokedEvent = object('SessionRevokedEvent', {
  eventId: uuid,
  topic: literal('session.revoked'),
  audience: oneOf(UsersAudience, SessionsAudience),
  payload: SessionRevokedPayload
});
export const ChannelEvent = tagged('topic', {
  'config.changed': ConfigChangedEvent,
  notification: NotificationEvent,
  'session.revoked': SessionRevokedEvent
});
export type ChannelEvent = Infer<typeof ChannelEvent>;

// ---- 第 2 节 浏览器与后端：WebSocket /ws

export const SubscribeMessage = object('SubscribeMessage', { type: literal('subscribe'), pages: array(code) });
export const UnsubscribeMessage = object('UnsubscribeMessage', { type: literal('unsubscribe'), pages: array(code) });
export const PingMessage = object('PingMessage', { type: literal('ping') });
/** 浏览器发送的消息 */
export const ClientMessage = tagged('type', {
  subscribe: SubscribeMessage,
  unsubscribe: UnsubscribeMessage,
  ping: PingMessage
});
export type ClientMessage = Infer<typeof ClientMessage>;

export const PushConfigChanged = object('PushConfigChanged', {
  topic: literal('config.changed'),
  eventId: uuid,
  payload: ConfigChangedPayload
});
export const PushNotification = object('PushNotification', {
  topic: literal('notification'),
  eventId: uuid,
  payload: NotificationPayload
});
export const PushSessionRevoked = object('PushSessionRevoked', {
  topic: literal('session.revoked'),
  eventId: uuid,
  payload: SessionRevokedPayload
});
export const PongMessage = object('PongMessage', { type: literal('pong') });
/** 服务端推送的消息 */
export const ServerMessage = oneOf(PushConfigChanged, PushNotification, PushSessionRevoked, PongMessage);
export type ServerMessage = Infer<typeof ServerMessage>;

/** 推送事件的主题和对应的内容 */
export interface TopicPayloads {
  'config.changed': ConfigChangedPayload;
  notification: NotificationPayload;
  'session.revoked': SessionRevokedPayload;
}
export type Topic = keyof TopicPayloads;

/** C11 的 `ShellApi.realtime` */
export interface RealtimeClient {
  /** 订阅页面的 `config.changed`；同一页面可以多次订阅，取消同样次数后才真正退订 */
  subscribe(pages: string[]): void;
  unsubscribe(pages: string[]): void;
  /** 收到某主题的事件（已按 eventId 去重）时调用；返回取消监听的函数 */
  onEvent<T extends Topic>(topic: T, handler: (payload: TopicPayloads[T], eventId: string) => void): () => void;
}
