import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { backend } from "./rpc";
import { formatUpdated, safeError } from "./state";
import { styles } from "./styles";
import type { Status, StatusAction } from "./types";

interface Props {
  readonly status: Status;
  readonly busy: boolean;
  readonly run: StatusAction;
}

export function AutomationPanel({ status, busy, run }: Props) {
  const update = status.update;
  const updating = update?.state === "preparing" || update?.state === "installing";
  const checking = update?.state === "checking";
  const autoCheck = status.auto_check_updates ?? true;
  const autoInstall = status.auto_install_updates ?? false;
  const unsupported = update?.supported === false || !status.platform_supported;
  const disabled = busy || updating;

  return <>
    <PanelSection title="订阅更新">
      <PanelSectionRow>
        <DropdownItem label="订阅自动更新" selectedOption={status.subscription_interval_hours ?? 0}
          disabled={disabled}
          description="定时更新所有 URL 订阅及其规则集。运行中的配置更新会短暂重启内核；失败时保留原配置。"
          rgOptions={[
            { data: 0, label: "关闭" }, { data: 6, label: "每 6 小时" },
            { data: 12, label: "每 12 小时" }, { data: 24, label: "每天" },
          ]}
          onChange={(option: { data: number }) => { void run("订阅更新周期已保存", () => backend.setSubscriptionInterval(Number(option.data))); }} />
        {status.subscription_last_check && <div style={styles.note}>上次订阅检查：{formatUpdated(status.subscription_last_check)}</div>}
        {status.subscription_error && <div role="alert" style={styles.error}>{safeError(status.subscription_error)}</div>}
      </PanelSectionRow>
    </PanelSection>
    <PanelSection title="插件更新">
      <PanelSectionRow>
        <div style={styles.note}>
          {`DeckyProxy ${status.version ?? "当前版本"}`}
          {update?.available && update.version ? ` · 可更新至 ${update.version}` : ""}
          {update?.checked_at && <><br />上次检查：{formatUpdated(update.checked_at)}</>}
        </div>
        {unsupported && <div style={styles.note}>当前环境无法自动安装插件更新，请使用安装包手动安装。</div>}
        {status.running && <div style={styles.note}>先停止代理，再安装插件更新。</div>}
        {updating && <div role="status" style={styles.notice}>正在安装更新，Decky 会短暂重启。请稍候重新打开插件。</div>}
        {update?.error && <div role="alert" style={styles.error}>{safeError(update.error)}</div>}
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="自动检查插件更新" checked={autoCheck} disabled={disabled}
          description="默认只检查新版，不会自动安装或重启 Decky。"
          onChange={(enabled) => { void run("更新设置已保存", () => backend.setUpdatePreferences(enabled, enabled && autoInstall)); }} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="停止代理后自动安装" checked={autoInstall}
          disabled={disabled || unsupported || !autoCheck}
          description="发现新版后等待代理停止，再安装并短暂重启 Decky。个人配置会保留，安装失败会尝试恢复旧版。"
          onChange={(enabled) => { void run("更新设置已保存", () => backend.setUpdatePreferences(autoCheck, enabled)); }} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={disabled || checking}
          onClick={() => { void run("插件版本已检查", backend.checkForUpdates); }}>
          {checking ? "正在检查更新…" : "检查插件更新"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={disabled || checking || unsupported || status.running || !update?.available}
          description="安装会短暂重启 Decky；请先停止代理。"
          onClick={() => { void run("已开始安装更新，请等待 Decky 重新加载", backend.installUpdate); }}>安装新版</ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  </>;
}
