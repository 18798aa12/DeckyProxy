import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, TextField } from "@decky/ui";
import { useState } from "react";
import { backend } from "./rpc";
import { safeError } from "./state";
import { styles } from "./styles";
import type { Group, RuleBehavior, RuleFormat, Status, StatusAction } from "./types";

interface Props {
  readonly status: Status;
  readonly groups: readonly Group[];
  readonly busy: boolean;
  readonly run: StatusAction;
}

function prepareRule(name: string, value: string, target: string): { name: string; url: string; target: string } {
  const trimmedName = name.trim();
  const policy = target.trim();
  if (!trimmedName || [...trimmedName].length > 64) throw new Error("请输入 1–64 个字符的规则集名称。");
  if (!policy || [...policy].length > 128) throw new Error("请输入有效的目标策略组名称。");
  let address: URL;
  try { address = new URL(value.trim()); }
  catch { throw new Error("请输入完整的 HTTPS 规则集地址。"); }
  if (address.protocol !== "https:") throw new Error("规则集地址必须使用 HTTPS。");
  if (address.username || address.password) throw new Error("规则集地址不能包含用户名或密码。");
  return { name: trimmedName, url: value.trim(), target: policy };
}

export function RulePanel({ status, groups, busy, run }: Props) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [behavior, setBehavior] = useState<RuleBehavior>("classical");
  const [format, setFormat] = useState<RuleFormat>("yaml");
  const [target, setTarget] = useState("节点选择");
  const [error, setError] = useState<string | null>(null);
  const policies = [...new Set([...groups.map((group) => group.name), "DIRECT", "REJECT"])];
  const selectedTarget = groups.length > 0 && !policies.includes(target) ? groups[0].name : target;

  const importRule = async (): Promise<void> => {
    setError(null);
    try {
      const input = prepareRule(name, url, selectedTarget);
      const imported = await run("规则集已导入", () => backend.importRuleProvider(input.name, input.url, behavior, format, input.target));
      if (imported) { setName(""); setUrl(""); }
    } catch (caught) { setError(safeError(caught)); }
  };

  return <PanelSection title="导入规则集">
    <PanelSectionRow>
      <div style={styles.note}>添加到当前配置，在最终 MATCH 规则之前匹配，保留已有规则的优先级。远程规则集随订阅更新。</div>
      {!status.active_profile_id && <div style={styles.note}>先导入并选择一个配置，再添加规则集。</div>}
      <TextField label="规则集名称" value={name} disabled={busy}
        onChange={(event) => { setName(event.target.value); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <TextField label="规则集地址" value={url} disabled={busy} bIsPassword
        description="公网 HTTPS 地址。可能含密钥，导入后不显示完整地址。"
        onChange={(event) => { setUrl(event.target.value); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <DropdownItem label="规则格式" selectedOption={format} disabled={busy}
        rgOptions={[{ data: "yaml", label: "YAML" }, { data: "text", label: "纯文本" }, { data: "mrs", label: "MRS" }]}
        onChange={(option: { data: RuleFormat }) => {
          setFormat(option.data);
          if (option.data === "mrs" && behavior === "classical") setBehavior("domain");
        }} />
    </PanelSectionRow>
    <PanelSectionRow>
      <DropdownItem label="规则行为" selectedOption={behavior} disabled={busy}
        description="与规则集提供方标注的 behavior 保持一致。MRS 支持 domain 与 ipcidr。"
        rgOptions={[
          ...(format === "mrs" ? [] : [{ data: "classical", label: "classical · 完整规则" }]),
          { data: "domain", label: "domain · 域名" }, { data: "ipcidr", label: "ipcidr · IP 网段" },
        ]}
        onChange={(option: { data: RuleBehavior }) => { setBehavior(option.data); }} />
    </PanelSectionRow>
    <PanelSectionRow>
      {groups.length > 0
        ? <DropdownItem label="目标策略组" selectedOption={selectedTarget} disabled={busy}
          rgOptions={policies.map((policy) => ({ data: policy, label: policy }))}
          onChange={(option: { data: string }) => { setTarget(option.data); }} />
        : <TextField label="目标策略组" value={target} disabled={busy}
          description="填写配置内已有的策略组名称，或 DIRECT / REJECT。启用代理后可从列表选择。"
          onChange={(event) => { setTarget(event.target.value); }} />}
      {error && <div role="alert" style={styles.error}>{error}</div>}
    </PanelSectionRow>
    <PanelSectionRow>
      <ButtonItem layout="below" disabled={busy || !status.active_profile_id || !name.trim() || !url.trim() || !selectedTarget.trim()}
        onClick={() => { void importRule(); }}>导入规则集</ButtonItem>
    </PanelSectionRow>
  </PanelSection>;
}
