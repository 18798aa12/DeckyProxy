import { ButtonItem, DropdownItem, Focusable, PanelSection, PanelSectionRow, TextField } from "@decky/ui";
import { FileSelectionType, openFilePicker, useQuickAccessVisible } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { backend } from "./rpc";
import { clearProfileDraft, readProfileDraft, writeProfileDraft, type ProfileDraft } from "./profileDraft";
import { formatUpdated, prepareImport, safeError } from "./state";
import { styles } from "./styles";
import type { ImportSource, Status, StatusAction } from "./types";

interface Props {
  readonly status: Status;
  readonly busy: boolean;
  readonly run: StatusAction;
}

interface FileFeedback {
  readonly kind: "success" | "error";
  readonly message: string;
}

export function ProfilePanel({ status, busy: requestBusy, run }: Props) {
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState(readProfileDraft);
  const { source, name, value } = draft;
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [filePhase, setFilePhase] = useState<"selecting" | "importing" | null>(null);
  const [fileFeedback, setFileFeedback] = useState<FileFeedback | null>(null);
  const pickerLocked = useRef(false);
  const mounted = useRef(true);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileControl = useRef<HTMLDivElement>(null);
  const restoreFileFocus = useRef(false);
  const profileBoundary = useRef<HTMLDivElement>(null);
  const visible = useQuickAccessVisible();
  const busy = requestBusy || filePhase !== null;
  const selected = status.profiles.find((item) => item.id === selectedId)
    ?? status.profiles.find((item) => item.id === status.active_profile_id)
    ?? status.profiles[0];
  const active = selected?.id === status.active_profile_id;
  const summary = status.active_profile_summary;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!visible || !confirmDelete) return;
    const element = profileBoundary.current;
    const cancel = (event: Event): void => {
      event.preventDefault();
      event.stopPropagation();
      setConfirmDelete(false);
    };
    element?.addEventListener("vgp_oncancel", cancel);
    return () => { element?.removeEventListener("vgp_oncancel", cancel); };
  }, [confirmDelete, visible]);

  useEffect(() => {
    if (visible && filePhase === null && restoreFileFocus.current) {
      restoreFileFocus.current = false;
      fileControl.current?.focus();
    }
  }, [filePhase, visible]);

  const changeDraft = (change: Partial<ProfileDraft>): void => {
    const next = { ...draft, ...change };
    writeProfileDraft(next);
    setDraft(next);
  };

  const clearDraft = (): void => {
    clearProfileDraft();
    setDraft({ source, name: "", value: "" });
  };

  const importProfile = async (): Promise<void> => {
    setError(null);
    try {
      const input = prepareImport(name, source, value);
      const imported = await run("配置已导入", () => backend.importProfile(input.name, input.url, input.content));
      if (imported) clearDraft();
    } catch (caught) { setError(safeError(caught)); }
  };

  const importFile = async (): Promise<void> => {
    if (busy || pickerLocked.current) return;
    pickerLocked.current = true;
    setFilePhase("selecting");
    setFileFeedback(null);
    setError(null);
    try {
      if ([...name.trim()].length > 64) throw new Error("请输入 1–64 个字符的配置名称。");
      const directory = await backend.getImportDirectory();
      if (!mounted.current) return;
      const file = await openFilePicker(FileSelectionType.FILE, directory || "/home/deck/Downloads",
        true, true, undefined, ["yaml", "yml"], false, false);
      if (!mounted.current) return;
      if (!file || typeof file.path !== "string" || !file.path.trim()) {
        throw new Error("文件选择器未返回有效路径，请重新选择 YAML 文件。");
      }
      if (!/\.ya?ml$/i.test(file.path)) {
        throw new Error("请选择具体的 YAML 文件，不要选择文件夹。");
      }
      const filename = file.path.split("/").pop()?.replace(/\.ya?ml$/i, "") || "Clash 配置";
      const importedName = name.trim() || [...filename].slice(0, 64).join("");
      changeDraft({ name: importedName });
      setFilePhase("importing");
      let failure: string | null = null;
      const imported = await run("配置已保存", async () => {
        const next = await backend.importProfileFile(importedName, file.path);
        if (mounted.current) {
          const existingIds = new Set(status.profiles.map((profile) => profile.id));
          const created = next.profiles.find((profile) => !existingIds.has(profile.id));
          if (created) setSelectedId(created.id);
        }
        return next;
      }, (message) => { failure = message; });
      if (!mounted.current) return;
      if (imported) {
        clearDraft();
        setFileFeedback({ kind: "success", message: "YAML 文件已导入" });
      } else {
        setFileFeedback({ kind: "error", message: failure ?? "当前有其他操作，请稍后重新导入 YAML。" });
      }
    } catch (caught) {
      if (mounted.current && caught !== "User canceled") {
        setFileFeedback({ kind: "error", message: safeError(caught) });
      }
    } finally {
      pickerLocked.current = false;
      if (mounted.current) {
        restoreFileFocus.current = true;
        setFilePhase(null);
      }
    }
  };

  return <Focusable ref={profileBoundary}><PanelSection title="配置">
    {summary && <PanelSectionRow>
      <div style={styles.note}>
        {summary.source_rules
          ? `已保留原配置：${summary.rules} 条规则 · ${summary.groups} 个策略组 · ${summary.rule_providers} 个规则集`
          : `当前配置：${summary.rules} 条规则 · ${summary.groups} 个策略组 · ${summary.rule_providers} 个规则集`}
      </div>
      {(summary.normalized_rule_providers ?? 0) > 0 && <div style={styles.note}>
        已按实际内容修正 {summary.normalized_rule_providers} 个规则集格式
      </div>}
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
      <div style={styles.note}>导入 Clash YAML 文件、订阅或文本，保留原有规则、规则集和策略组。端口、DNS 与 TUN 由插件管理。</div>
      <TextField label="配置名称" value={name} disabled={busy} description="选择文件时可留空，自动使用文件名。"
        onChange={(event) => { changeDraft({ name: event.target.value }); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <Focusable ref={fileControl} tabIndex={-1} role="group" aria-label="YAML 文件导入">
        <ButtonItem layout="below" disabled={busy}
          description="先在火狐下载 YAML，再从下载、文档或桌面目录选择 .yaml / .yml。"
          onClick={() => { void importFile(); }}>选择 YAML 文件并导入</ButtonItem>
        {filePhase && <div role="status" style={styles.note}>
          {filePhase === "selecting" ? "正在选择 YAML 文件…" : "正在导入 YAML…"}
        </div>}
        {fileFeedback && <div role={fileFeedback.kind === "error" ? "alert" : "status"}
          style={fileFeedback.kind === "error" ? styles.error : styles.notice}>{fileFeedback.message}</div>}
        {fileFeedback?.kind === "success" && <div style={styles.note}>
          {active ? "配置已就绪，可开启代理。" : "点击“使用此配置”启用刚导入的配置。"}
        </div>}
      </Focusable>
    </PanelSectionRow>
    <PanelSectionRow>
      <DropdownItem label="导入方式" selectedOption={source} disabled={busy}
        rgOptions={[{ data: "url", label: "HTTPS 订阅地址" }, { data: "yaml", label: "粘贴 YAML 文本" }]}
        onChange={(option: { data: ImportSource }) => { changeDraft({ source: option.data, value: "" }); setError(null); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      {source === "url"
        ? <TextField label="订阅地址" value={value} disabled={busy} bIsPassword
          description="仅支持公网 HTTPS，地址可能含密钥。保存后不再显示完整地址。"
          onChange={(event) => { changeDraft({ value: event.target.value }); }} />
        : <>
          <div style={styles.note}>YAML 内容 · 按 A 编辑，Steam + X 打开键盘，按 B 结束编辑。建议在桌面模式粘贴长文本。</div>
          <Focusable tabIndex={0} data-text-editor onActivate={() => { textarea.current?.focus(); }}>
            <textarea ref={textarea} aria-label="YAML 内容" value={value} disabled={busy} style={styles.textarea}
              spellCheck={false} onChange={(event) => { changeDraft({ value: event.target.value }); }} />
          </Focusable>
        </>}
      {error && <div role="alert" style={styles.error}>{error}</div>}
    </PanelSectionRow>
    <PanelSectionRow>
      <ButtonItem layout="below" disabled={busy || !name.trim() || !value.trim()} onClick={() => { void importProfile(); }}>导入配置</ButtonItem>
    </PanelSectionRow>
  </PanelSection></Focusable>;
}
