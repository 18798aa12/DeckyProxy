import type { ImportSource, ProxyMode, Result, Status } from "./types";

export const modeOptions: ReadonlyArray<{ data: ProxyMode; label: string }> = [
  { data: "rule", label: "规则模式" },
  { data: "global", label: "全局代理" },
  { data: "direct", label: "全部直连" },
];

export const modeDescription: Record<ProxyMode, string> = {
  rule: "局域网直连，其余流量走所选代理。使用插件内置规则。",
  global: "经代理接管的流量统一走 GLOBAL 组所选节点。",
  direct: "经代理接管的流量直接连接。",
};

export function canStart(status: Status): boolean {
  return status.platform_supported && status.core_installed && status.active_profile_id !== null;
}

export function safeError(error: unknown): string {
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "操作失败，请刷新状态后重试。";
  return message.replace(/https?:\/\/[^\s<>"']+/gi, "[已隐藏地址]").slice(0, 500);
}

export function unwrap<T>(result: Result<T>): T {
  if (!result.ok) throw new Error(safeError(result.error));
  return result.data;
}

export function prepareImport(name: string, source: ImportSource, value: string): { name: string; url: string; content: string } {
  const trimmedName = name.trim();
  if (!trimmedName || [...trimmedName].length > 64) throw new Error("请输入 1–64 个字符的配置名称。");
  if (!value.trim()) throw new Error("请输入订阅地址或 YAML 内容。");
  if (source === "yaml") return { name: trimmedName, url: "", content: value };
  let address: URL;
  try { address = new URL(value.trim()); }
  catch { throw new Error("请输入完整的 HTTPS 订阅地址。"); }
  if (address.protocol !== "https:") throw new Error("订阅地址必须使用 HTTPS。");
  if (address.username || address.password) throw new Error("订阅地址不能包含用户名或密码。");
  return { name: trimmedName, url: value.trim(), content: "" };
}

export function formatDelay(delay: number | null): string {
  if (delay === null) return "未测试";
  return delay > 0 ? `${Math.round(delay)} ms` : "超时";
}

export function formatUpdated(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "未知" : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
