import { ButtonItem, DropdownItem, Focusable, PanelSection, PanelSectionRow, TextField } from "@decky/ui";
import { useRef, useState } from "react";
import { backend } from "./rpc";
import { formatUpdated, prepareImport, safeError } from "./state";
import { styles } from "./styles";
import type { ImportSource, Status, StatusAction } from "./types";

interface Props {
  readonly status: Status;
  readonly busy: boolean;
  readonly run: StatusAction;
}

export function ProfilePanel({ status, busy, run }: Props) {
  const [selectedId, setSelectedId] = useState("");
  const [source, setSource] = useState<ImportSource>("url");
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const selected = status.profiles.find((item) => item.id === selectedId)
    ?? status.profiles.find((item) => item.id === status.active_profile_id)
    ?? status.profiles[0];
  const active = selected?.id === status.active_profile_id;
  const summary = status.active_profile_summary;

  const importProfile = async (): Promise<void> => {
    setError(null);
    try {
      const input = prepareImport(name, source, value);
      const imported = await run("配置已导入", () => backend.importProfile(input.name, input.url, input.content));
      if (imported) { setName(""); setValue(""); }
    } catch (caught) { setError(safeError(caught)); }
  };

  return <PanelSection title="配置">
    {summary && <PanelSectionRow>
      <div style={styles.note}>
        {summary.source_rules
          ? `已保留原配置：${summary.rules} 条规则 · ${summary.groups} 个策略组 · ${summary.rule_providers} 个规则集`
          : `当前配置：${summary.rules} 条规则 · ${summary.groups} 个策略组 · ${summary.rule_providers} 个规则集`}
      </div>
      {summary.legacy && <div style={styles.note}>旧版配置只保存了节点。点击“更新此订阅”恢复原有规则和策略组；本地 YAML 请重新导入。</div>}
    </PanelSectionRow>}
    {status.profiles.length > 0 && <>
      <PanelSectionRow>
        <DropdownItem label="配置文件" disabled={busy} selectedOption={selected?.id}
          rgOptions={status.profiles.map((profile) => ({ data: profile.id, label: `${profile.name}${profile.id === status.active_profile_id ? "（使用中）" : ""}` }))}
          onChange={(option: { data: string }) => { setSelectedId(option.data); setConfirmDelete(false); }} />
        {selected && <div style={styles.note}>
          {selected.source_host ? `订阅来源 ${selected.source_host}` : "本地 YAML"}<br />更新于 {formatUpdated(selected.updated_at)}
        </div>}
      </PanelSectionRow>
      {selected && <>
        {!active && <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => { void run("配置已启用", () => backend.activateProfile(selected.id)); }}>使用此配置</ButtonItem>
        </PanelSectionRow>}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || !selected.source_host}
            description={selected.source_host ? "重新获取订阅；更新运行中的配置会重启内核。" : "YAML 配置请重新导入以更新。"}
            onClick={() => { void run("订阅已更新", () => backend.refreshProfile(selected.id)); }}>更新此订阅</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || (active && status.running)}
            description={active && status.running ? "停止代理后可删除当前配置。" : "删除保存在本机的此配置。"}
            onClick={() => { setConfirmDelete(!confirmDelete); }}>删除此配置</ButtonItem>
        </PanelSectionRow>
        {confirmDelete && <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy}
            onClick={() => { setConfirmDelete(false); void run("配置已删除", () => backend.deleteProfile(selected.id)); }}>确认删除“{selected.name}”</ButtonItem>
          <ButtonItem layout="below" disabled={busy} onClick={() => { setConfirmDelete(false); }}>取消删除</ButtonItem>
        </PanelSectionRow>}
      </>}
    </>}
    <PanelSectionRow>
      <div style={styles.note}>导入 Clash YAML 订阅或文本，保留原有规则、规则集和策略组。端口、DNS 与 TUN 由插件管理。</div>
      <TextField label="配置名称" value={name} disabled={busy} onChange={(event) => { setName(event.target.value); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <DropdownItem label="导入方式" selectedOption={source} disabled={busy}
        rgOptions={[{ data: "url", label: "HTTPS 订阅地址" }, { data: "yaml", label: "粘贴 YAML 文本" }]}
        onChange={(option: { data: ImportSource }) => { setSource(option.data); setValue(""); setError(null); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      {source === "url"
        ? <TextField label="订阅地址" value={value} disabled={busy} bIsPassword
          description="仅支持公网 HTTPS，地址可能含密钥。保存后不再显示完整地址。"
          onChange={(event) => { setValue(event.target.value); }} />
        : <>
          <div style={styles.note}>YAML 内容 · 按 A 编辑，Steam + X 打开键盘。建议在桌面模式粘贴长文本。</div>
          <Focusable onActivate={() => { textarea.current?.focus(); }}>
            <textarea ref={textarea} aria-label="YAML 内容" value={value} disabled={busy} style={styles.textarea}
              spellCheck={false} onChange={(event) => { setValue(event.target.value); }} />
          </Focusable>
        </>}
      {error && <div role="alert" style={styles.error}>{error}</div>}
    </PanelSectionRow>
    <PanelSectionRow>
      <ButtonItem layout="below" disabled={busy || !name.trim() || !value.trim()} onClick={() => { void importProfile(); }}>导入配置</ButtonItem>
    </PanelSectionRow>
  </PanelSection>;
}
