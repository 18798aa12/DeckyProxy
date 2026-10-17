import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConnectionPanel } from "./ConnectionPanel";
import { GroupPanel } from "./GroupPanel";
import { ProfilePanel } from "./ProfilePanel";
import { backend } from "./rpc";
import { formatDelay, safeError } from "./state";
import { styles } from "./styles";
import type { Group, Status, StatusAction } from "./types";

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [groups, setGroups] = useState<readonly Group[]>([]);
  const [busy, setBusy] = useState<string | null>("正在读取状态…");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<string | null>(null);
  const mounted = useRef(true);
  const locked = useRef(false);
  const requestId = useRef(0);
  const pendingRefresh = useRef<Promise<void> | null>(null);
  const panelVisible = useQuickAccessVisible();

  const isCurrent = useCallback((id: number): boolean => mounted.current && requestId.current === id, []);

  const updateStatus = useCallback(async (next: Status, id: number): Promise<void> => {
    if (!isCurrent(id)) return;
    setStatus(next);
    if (next.running) {
      const nextGroups = await backend.getGroups();
      if (isCurrent(id)) setGroups(nextGroups);
    } else setGroups([]);
  }, [isCurrent]);

  const run: StatusAction = useCallback(async (label, operation) => {
    const queuedId = requestId.current;
    if (pendingRefresh.current) await pendingRefresh.current;
    if (!mounted.current || locked.current || queuedId !== requestId.current) return false;
    locked.current = true;
    const id = ++requestId.current;
    setBusy("正在处理，请稍候…");
    setError(null);
    setNotice(null);
    try {
      await updateStatus(await operation(), id);
      if (isCurrent(id)) setNotice(label);
      return isCurrent(id);
    } catch (caught) {
      if (isCurrent(id)) setError(safeError(caught));
      return false;
    } finally {
      if (isCurrent(id)) { locked.current = false; setBusy(null); }
    }
  }, [isCurrent, updateStatus]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestId.current += 1;
      locked.current = false;
      pendingRefresh.current = null;
    };
  }, []);

  const refreshStatus = useCallback(async (): Promise<void> => {
    if (!mounted.current || locked.current) return;
    locked.current = true;
    const id = ++requestId.current;
    try {
      await updateStatus(await backend.getStatus(), id);
      if (isCurrent(id)) setError(null);
    } catch (caught) {
      if (isCurrent(id)) setError(safeError(caught));
    } finally {
      if (isCurrent(id)) { locked.current = false; setBusy(null); }
    }
  }, [isCurrent, updateStatus]);

  useEffect(() => {
    if (!panelVisible) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async (): Promise<void> => {
      if (cancelled) return;
      if (!locked.current) {
        const task = refreshStatus();
        pendingRefresh.current = task;
        await task;
        if (pendingRefresh.current === task) pendingRefresh.current = null;
      }
      if (!cancelled) timer = setTimeout(() => { void tick(); }, 3000);
    };
    void tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [panelVisible, refreshStatus]);

  const runGroupAction = async (operation: () => Promise<readonly Group[]>, label: string): Promise<void> => {
    const queuedId = requestId.current;
    if (pendingRefresh.current) await pendingRefresh.current;
    if (!mounted.current || locked.current || queuedId !== requestId.current) return;
    locked.current = true;
    const id = ++requestId.current;
    setBusy("正在处理，请稍候…");
    setError(null);
    setNotice(null);
    try {
      const nextGroups = await operation();
      if (isCurrent(id)) { setGroups(nextGroups); setNotice(label); }
    } catch (caught) {
      if (isCurrent(id)) setError(safeError(caught));
    } finally {
      if (isCurrent(id)) { locked.current = false; setBusy(null); }
    }
  };

  const testDelay = async (name: string): Promise<void> => {
    const queuedId = requestId.current;
    if (pendingRefresh.current) await pendingRefresh.current;
    if (!mounted.current || locked.current || queuedId !== requestId.current) return;
    locked.current = true;
    const id = ++requestId.current;
    setBusy("正在测试延迟…");
    setError(null);
    setNotice(null);
    try {
      const result = await backend.testDelay(name);
      if (isCurrent(id)) {
        setNotice(`${name}：${formatDelay(result.delay_ms)}`);
        setGroups((previous) => previous.map((group) => ({ ...group,
          options: group.options.map((option) => option.name === name ? { ...option, delay_ms: result.delay_ms } : option),
        })));
      }
    } catch (caught) {
      if (isCurrent(id)) setError(safeError(caught));
    } finally {
      if (isCurrent(id)) { locked.current = false; setBusy(null); }
    }
  };

  const readDiagnostics = async (): Promise<void> => {
    const queuedId = requestId.current;
    if (pendingRefresh.current) await pendingRefresh.current;
    if (!mounted.current || locked.current || queuedId !== requestId.current) return;
    locked.current = true;
    const id = ++requestId.current;
    setBusy("正在读取诊断…");
    setError(null);
    try {
      const summary = await backend.getDiagnostics();
      if (isCurrent(id)) setDiagnostics(summary);
    } catch (caught) {
      if (isCurrent(id)) setError(safeError(caught));
    } finally {
      if (isCurrent(id)) { locked.current = false; setBusy(null); }
    }
  };

  return <>
    <div aria-live="polite">
      {busy && <div style={styles.note}>{busy}</div>}
      {notice && <div role="status" style={styles.notice}>{notice}</div>}
    </div>
    {error && <div role="alert" style={styles.error}>{error}</div>}
    {status && <>
      <ConnectionPanel status={status} busy={busy !== null} run={run} />
      <GroupPanel groups={groups} busy={busy !== null} running={status.running}
        onSelect={(group, proxy) => { void runGroupAction(() => backend.selectProxy(group, proxy), "节点已切换"); }}
        onTest={(name) => { void testDelay(name); }} />
      <ProfilePanel status={status} busy={busy !== null} run={run} />
    </>}
    <PanelSection title="维护">
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== null} onClick={() => { void run("状态已刷新", backend.getStatus); }}>刷新状态</ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== null}
          description="查看运行状态与安全诊断摘要。"
          onClick={() => { void readDiagnostics(); }}>查看诊断</ButtonItem>
        {diagnostics && <pre style={styles.diagnostics}>{diagnostics}</pre>}
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={styles.note}>首次使用：安装内核 → 导入配置 → 使用配置 → 根据需要开启 TUN → 启用代理。</div>
      </PanelSectionRow>
    </PanelSection>
  </>;
}
