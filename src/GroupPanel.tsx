import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { formatDelay } from "./state";
import { styles } from "./styles";
import type { Group } from "./types";

interface Props {
  readonly groups: readonly Group[];
  readonly busy: boolean;
  readonly running: boolean;
  readonly onSelect: (group: string, proxy: string) => void;
  readonly onTest: (name: string) => void;
}

export function GroupPanel({ groups, busy, running, onSelect, onTest }: Props) {
  return <PanelSection title="节点与策略组">
    {!running && <PanelSectionRow><div style={styles.note}>启用代理后可选择节点和测试延迟。</div></PanelSectionRow>}
    {running && groups.length === 0 && <PanelSectionRow><div style={styles.note}>暂无可选策略组，点击刷新状态重试。</div></PanelSectionRow>}
    {running && groups.map((group) => <PanelSectionRow key={group.name}>
      <DropdownItem label={group.name} selectedOption={group.now}
        description={group.type === "select" || group.type === "Selector" ? "选择此策略组使用的线路。" : "此策略组由内核自动选择线路。"}
        disabled={busy || !["select", "Selector"].includes(group.type)}
        rgOptions={group.options.map((option) => ({ data: option.name, label: `${option.name} · ${formatDelay(option.delay_ms)}` }))}
        onChange={(option: { data: string }) => { onSelect(group.name, option.data); }} />
      <ButtonItem layout="below" disabled={busy || !group.now || ["DIRECT", "REJECT"].includes(group.now)}
        onClick={() => { onTest(group.now); }}>测试“{group.now}”延迟</ButtonItem>
    </PanelSectionRow>)}
    {running && <PanelSectionRow><div style={styles.note}>延迟为测试站点的往返时间，无法代表游戏服务器延迟。</div></PanelSectionRow>}
  </PanelSection>;
}
