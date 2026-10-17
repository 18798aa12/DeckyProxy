import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { backend } from "./rpc";
import { canStart, modeDescription, modeOptions, safeError } from "./state";
import { styles } from "./styles";
import type { ProxyMode, Status, StatusAction } from "./types";

interface Props {
  readonly status: Status;
  readonly busy: boolean;
  readonly run: StatusAction;
}

export function ConnectionPanel({ status, busy, run }: Props) {
  const profile = status.profiles.find((item) => item.id === status.active_profile_id);
  const startHint = !status.platform_supported ? "仅支持 SteamOS / Linux x86_64。"
    : !status.core_installed ? "先安装 Mihomo 内核。"
      : !status.active_profile_id ? "先导入并启用一个配置。" : undefined;

  return <PanelSection title="连接">
    <PanelSectionRow>
      <div style={{ ...styles.status, borderLeftColor: status.running ? "#67D9BF" : "#8399AD" }} aria-live="polite">
        <div style={styles.statusName}>{status.running ? "代理运行中" : "代理已停止"}</div>
        <div style={styles.detail}>{profile?.name ?? "尚未选择配置"}</div>
        <div style={styles.detail}>{status.core_installed ? `Mihomo ${status.core_version || "已安装"}` : "Mihomo 尚未安装"}</div>
      </div>
      {status.last_error && <div role="alert" style={styles.error}>{safeError(status.last_error)}</div>}
    </PanelSectionRow>
    <PanelSectionRow>
      <ToggleField label="启用代理" checked={status.running}
        disabled={busy || (!status.running && !canStart(status))}
        description={startHint ?? (status.tun_enabled ? "TUN 已开启，将接管系统网络流量。" : `本地代理端口 ${status.mixed_port}。系统流量需开启 TUN 或单独配置应用代理。`)}
        onChange={(enabled) => { void run(enabled ? "代理已启动" : "代理已停止", enabled ? backend.startProxy : backend.stopProxy); }} />
      {startHint && <div style={styles.note}>{startHint}</div>}
    </PanelSectionRow>
    <PanelSectionRow>
      <DropdownItem label="代理模式" disabled={busy} selectedOption={status.mode}
        rgOptions={[...modeOptions]} description={modeDescription[status.mode]}
        onChange={(option: { data: ProxyMode }) => { void run("代理模式已更新", () => backend.setMode(option.data)); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <ToggleField label="TUN 接管系统流量" checked={status.tun_enabled} disabled={busy || !status.platform_supported}
        description="游戏与 Steam 下载通常需要此选项。切换时会重启运行中的内核，网络可能短暂中断。"
        onChange={(enabled) => { void run("TUN 设置已更新", () => backend.setTun(enabled)); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <ToggleField label="随 Decky 自动启动" checked={status.auto_start} disabled={busy}
        description="默认关闭。启用后将在 Decky 加载插件时尝试恢复代理。"
        onChange={(enabled) => { void run("自动启动设置已更新", () => backend.setAutoStart(enabled)); }} />
    </PanelSectionRow>
    {!status.core_installed && <PanelSectionRow>
      <ButtonItem layout="below" disabled={busy || !status.platform_supported}
        description="从 Mihomo 官方发布下载并校验内核。需要先直连访问 GitHub。"
        onClick={() => { void run("Mihomo 内核已安装", backend.installCore); }}>安装 Mihomo 内核</ButtonItem>
    </PanelSectionRow>}
  </PanelSection>;
}
