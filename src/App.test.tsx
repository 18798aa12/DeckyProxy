import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import type { Status } from "./types";

const { mocks } = vi.hoisted(() => ({ mocks: {
  getStatus: vi.fn(), getGroups: vi.fn(), startProxy: vi.fn(), stopProxy: vi.fn(),
  setMode: vi.fn(), setTun: vi.fn(), setAutoStart: vi.fn(), importProfile: vi.fn(),
  refreshProfile: vi.fn(), activateProfile: vi.fn(), deleteProfile: vi.fn(),
  selectProxy: vi.fn(), testDelay: vi.fn(), installCore: vi.fn(), getDiagnostics: vi.fn(),
  quickAccessVisible: vi.fn(), setSubscriptionInterval: vi.fn(), setUpdatePreferences: vi.fn(),
  checkForUpdates: vi.fn(), installUpdate: vi.fn(), importRuleProvider: vi.fn(),
} }));

vi.mock("./rpc", () => ({ backend: mocks }));
vi.mock("@decky/api", () => ({ useQuickAccessVisible: mocks.quickAccessVisible }));
vi.mock("@decky/ui", () => ({
  PanelSection: ({ title, children }: { title: string; children: ReactNode }) => <section aria-label={title}>{children}</section>,
  PanelSectionRow: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Focusable: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Field: ({ label, description, children }: { label: string; description: string; children: ReactNode }) => <div>{label}{description}{children}</div>,
  ButtonItem: ({ children, disabled, onClick }: { children: ReactNode; disabled: boolean; onClick: () => void }) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  ToggleField: ({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (checked: boolean) => void }) => <label>{label}<input aria-label={label} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /></label>,
  DropdownItem: ({ label, selectedOption, disabled, rgOptions, onChange }: { label: string; selectedOption: string; disabled: boolean; rgOptions: Array<{ data: string; label: string }>; onChange: (option: { data: string }) => void }) => <label>{label}<select aria-label={label} value={selectedOption} disabled={disabled} onChange={(event) => onChange({ data: event.target.value })}>{rgOptions.map((option) => <option value={option.data} key={option.data}>{option.label}</option>)}</select></label>,
  TextField: ({ label, value, disabled, onChange }: { label: string; value: string; disabled: boolean; onChange: (event: { target: { value: string } }) => void }) => <label>{label}<input aria-label={label} disabled={disabled} value={value} onChange={onChange} /></label>,
}));

import { App } from "./App";

const status: Status = {
  running: false, core_installed: true, core_version: "v1.19.0", platform_supported: true,
  tun_enabled: false, mode: "rule", active_profile_id: "test", auto_start: false,
  profiles: [{ id: "test", name: "我的线路", updated_at: "2026-10-17T00:00:00Z", source_host: "provider.example" }],
  mixed_port: 7890, last_error: null,
};

beforeEach(() => { mocks.quickAccessVisible.mockReturnValue(true); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });

describe("QAM proxy controls", () => {
  it("loads with proxy off, then applies the start action result", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.startProxy.mockResolvedValue({ ...status, running: true });
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    const control = await screen.findByLabelText("启用代理");
    expect((control as HTMLInputElement).checked).toBe(false);
    fireEvent.click(control);
    await waitFor(() => expect(mocks.startProxy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect((control as HTMLInputElement).checked).toBe(true));
  });

  it("keeps the previous state and shows an error when starting fails", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.startProxy.mockRejectedValue(new Error("内核启动失败"));
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    const control = await screen.findByLabelText("启用代理");
    fireEvent.click(control);
    expect(await screen.findByText("内核启动失败")).toBeTruthy();
    expect((control as HTMLInputElement).checked).toBe(false);
  });

  it("disables start until a profile is imported", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, active_profile_id: null, profiles: [] });
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    const control = await screen.findByLabelText("启用代理");
    expect((control as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("先导入并启用一个配置。")) .toBeTruthy();
  });

  it("passes the selected routing mode to the backend", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.setMode.mockResolvedValue({ ...status, mode: "global" });
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    const control = await screen.findByLabelText("代理模式");
    fireEvent.change(control, { target: { value: "global" } });
    await waitFor(() => expect(mocks.setMode).toHaveBeenCalledWith("global"));
  });

  it("imports a subscription once and clears its sensitive input after success", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.importProfile.mockResolvedValue(status);
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    await screen.findByLabelText("配置名称");
    fireEvent.change(screen.getByLabelText("配置名称"), { target: { value: "工作线路" } });
    fireEvent.change(screen.getByLabelText("订阅地址"), { target: { value: "https://provider.example/sub?token=secret" } });
    fireEvent.click(screen.getByText("导入配置"));
    await waitFor(() => expect(mocks.importProfile).toHaveBeenCalledWith("工作线路", "https://provider.example/sub?token=secret", ""));
    await waitFor(() => expect((screen.getByLabelText("订阅地址") as HTMLInputElement).value).toBe(""));
  });

  it("preserves YAML line breaks through the import action", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.importProfile.mockResolvedValue(status);
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    await screen.findByLabelText("配置名称");
    fireEvent.change(screen.getByLabelText("配置名称"), { target: { value: "本地线路" } });
    fireEvent.change(screen.getByLabelText("导入方式"), { target: { value: "yaml" } });
    const content = "proxies:\n  - name: 节点 A\n    type: ss";
    fireEvent.change(screen.getByLabelText("YAML 内容"), { target: { value: content } });
    fireEvent.click(screen.getByText("导入配置"));
    await waitFor(() => expect(mocks.importProfile).toHaveBeenCalledWith("本地线路", "", content));
  });

  it("disables controls while a start request is still pending", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.startProxy.mockImplementation(() => new Promise<Status>(() => undefined));
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    const control = await screen.findByLabelText("启用代理");
    fireEvent.click(control);
    expect((control as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("代理模式") as HTMLSelectElement).disabled).toBe(true);
    fireEvent.click(control);
    expect(mocks.startProxy).toHaveBeenCalledTimes(1);
  });

  it("changes the selected node and displays the measured site latency", async () => {
    const group = { name: "节点选择", type: "select", now: "东京", options: [
      { name: "东京", delay_ms: null }, { name: "香港", delay_ms: null },
    ] };
    mocks.getStatus.mockResolvedValue({ ...status, running: true });
    mocks.getGroups.mockResolvedValue([group]);
    mocks.selectProxy.mockResolvedValue([{ ...group, now: "香港" }]);
    mocks.testDelay.mockResolvedValue({ delay_ms: 72 });
    render(<App />);
    const control = await screen.findByLabelText("节点选择");
    fireEvent.change(control, { target: { value: "香港" } });
    await waitFor(() => expect(mocks.selectProxy).toHaveBeenCalledWith("节点选择", "香港"));
    const testButton = await screen.findByText("测试“香港”延迟");
    fireEvent.click(testButton);
    await waitFor(() => expect(mocks.testDelay).toHaveBeenCalledWith("香港"));
    expect(await screen.findByText("香港：72 ms")).toBeTruthy();
    expect(screen.getByText("延迟为测试站点的往返时间，无法代表游戏服务器延迟。")).toBeTruthy();
  });
});

describe("visible panel status refresh", () => {
  const flush = async (): Promise<void> => { await act(async () => undefined); };

  it("detects a core exit after three seconds and removes obsolete groups", async () => {
    vi.useFakeTimers();
    mocks.getStatus.mockResolvedValueOnce({ ...status, running: true }).mockResolvedValue(status);
    mocks.getGroups.mockResolvedValue([{ name: "节点选择", type: "select", now: "东京", options: [] }]);
    render(<App />);
    await flush();
    expect(screen.getByLabelText("节点选择")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(2);
    expect((screen.getByLabelText("启用代理") as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByLabelText("节点选择")).toBeNull();
    expect(mocks.getGroups).toHaveBeenCalledTimes(1);
  });

  it("waits for a refresh to settle before scheduling another refresh", async () => {
    vi.useFakeTimers();
    let resolveRefresh: (next: Status) => void = () => undefined;
    mocks.getStatus.mockResolvedValueOnce(status).mockImplementationOnce(() => new Promise<Status>((resolve) => { resolveRefresh = resolve; })).mockResolvedValue(status);
    render(<App />);
    await flush();
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(2);
    await act(async () => { resolveRefresh(status); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2999); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(3);
  });

  it("does not poll while a proxy action holds the operation lock", async () => {
    vi.useFakeTimers();
    let resolveStart: (next: Status) => void = () => undefined;
    mocks.getStatus.mockResolvedValue(status);
    mocks.getGroups.mockResolvedValue([]);
    mocks.startProxy.mockImplementation(() => new Promise<Status>((resolve) => { resolveStart = resolve; }));
    render(<App />);
    await flush();
    fireEvent.click(screen.getByLabelText("启用代理"));
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(1);
    await act(async () => { resolveStart({ ...status, running: true }); });
    expect((screen.getByLabelText("启用代理") as HTMLInputElement).checked).toBe(true);
  });

  it("queues a user action behind an in-flight background refresh", async () => {
    vi.useFakeTimers();
    let resolveRefresh: (next: Status) => void = () => undefined;
    mocks.getStatus.mockResolvedValueOnce(status).mockImplementationOnce(() => new Promise<Status>((resolve) => { resolveRefresh = resolve; }));
    mocks.getGroups.mockResolvedValue([]);
    mocks.startProxy.mockResolvedValue({ ...status, running: true });
    render(<App />);
    await flush();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    fireEvent.click(screen.getByLabelText("启用代理"));
    expect(mocks.startProxy).not.toHaveBeenCalled();
    await act(async () => { resolveRefresh(status); });
    expect(mocks.startProxy).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("启用代理") as HTMLInputElement).checked).toBe(true);
  });

  it("pauses when the quick access menu closes and refreshes when reopened", async () => {
    vi.useFakeTimers();
    mocks.getStatus.mockResolvedValue(status);
    const { rerender } = render(<App />);
    await flush();
    mocks.quickAccessVisible.mockReturnValue(false);
    rerender(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(1);
    mocks.quickAccessVisible.mockReturnValue(true);
    rerender(<App />);
    await flush();
    expect(mocks.getStatus).toHaveBeenCalledTimes(2);
  });

  it("clears timers and ignores a late running response after unmount", async () => {
    vi.useFakeTimers();
    let resolveRefresh: (next: Status) => void = () => undefined;
    mocks.getStatus.mockResolvedValueOnce(status).mockImplementationOnce(() => new Promise<Status>((resolve) => { resolveRefresh = resolve; }));
    const { unmount } = render(<App />);
    await flush();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    unmount();
    await act(async () => { resolveRefresh({ ...status, running: true }); });
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(2);
    expect(mocks.getGroups).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not let a previous effect generation overwrite a newer status", async () => {
    vi.useFakeTimers();
    let resolveOld: (next: Status) => void = () => undefined;
    mocks.getStatus.mockImplementationOnce(() => new Promise<Status>((resolve) => { resolveOld = resolve; })).mockResolvedValue(status);
    render(<StrictMode><App /></StrictMode>);
    await flush();
    expect(mocks.getStatus).toHaveBeenCalledTimes(2);
    await act(async () => { resolveOld({ ...status, running: true }); });
    expect((screen.getByLabelText("启用代理") as HTMLInputElement).checked).toBe(false);
    expect(mocks.getGroups).not.toHaveBeenCalled();
  });
});


describe("v0.2 rules and maintenance", () => {
  const availableUpdate = {
    available: true, version: "0.3.0", checked_at: "2026-10-18T00:00:00Z", error: null,
    state: "available" as const, supported: true,
  };

  it("shows imported rules and policy groups rather than describing fixed rules", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, active_profile_summary: {
      source_rules: true, rules: 26, groups: 4, rule_providers: 2, legacy: false,
    } });
    render(<App />);
    expect(await screen.findByText("已保留原配置：26 条规则 · 4 个策略组 · 2 个规则集")).toBeTruthy();
    expect(screen.queryByText(/只使用节点/)).toBeNull();
  });

  it("explains how a legacy profile can recover its subscription rules", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, active_profile_summary: {
      source_rules: false, rules: 5, groups: 2, rule_providers: 0, legacy: true,
    } });
    render(<App />);
    expect(await screen.findByText(/旧版配置只保存了节点/)).toBeTruthy();
  });

  it("saves a subscription interval as hours", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, subscription_interval_hours: 0 });
    mocks.setSubscriptionInterval.mockResolvedValue({ ...status, subscription_interval_hours: 12 });
    render(<App />);
    const control = await screen.findByLabelText("订阅自动更新");
    fireEvent.change(control, { target: { value: "12" } });
    await waitFor(() => expect(mocks.setSubscriptionInterval).toHaveBeenCalledWith(12));
    await waitFor(() => expect((control as HTMLSelectElement).value).toBe("12"));
  });

  it("checks for versions and enables installation only after a signed update is available", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, version: "0.2.0", update: { ...availableUpdate, available: false, version: null, state: "idle" } });
    mocks.checkForUpdates.mockResolvedValue({ ...status, version: "0.2.0", update: availableUpdate });
    mocks.installUpdate.mockResolvedValue({ ...status, update: { ...availableUpdate, state: "installing" } });
    render(<App />);
    const install = await screen.findByText("安装新版");
    expect((install as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByText("检查插件更新"));
    await waitFor(() => expect(mocks.checkForUpdates).toHaveBeenCalledTimes(1));
    await waitFor(() => expect((install as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(install);
    await waitFor(() => expect(mocks.installUpdate).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/正在安装更新/)).toBeTruthy();
  });

  it("defaults to checking only and saves idle auto-install separately", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.setUpdatePreferences.mockResolvedValue({ ...status, auto_check_updates: true, auto_install_updates: true });
    render(<App />);
    const checking = await screen.findByLabelText("自动检查插件更新");
    const installing = screen.getByLabelText("停止代理后自动安装");
    expect((checking as HTMLInputElement).checked).toBe(true);
    expect((installing as HTMLInputElement).checked).toBe(false);
    fireEvent.click(installing);
    await waitFor(() => expect(mocks.setUpdatePreferences).toHaveBeenCalledWith(true, true));
  });

  it("prevents update installation while the proxy is running", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, running: true, update: availableUpdate });
    mocks.getGroups.mockResolvedValue([]);
    render(<App />);
    expect((await screen.findByText("安装新版") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("先停止代理，再安装插件更新。")).toBeTruthy();
  });

  it("imports a rule set for a selected policy and clears the private address", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, running: true });
    mocks.getGroups.mockResolvedValue([{ name: "游戏线路", type: "Selector", now: "东京", options: [] }]);
    mocks.importRuleProvider.mockResolvedValue({ ...status, running: true });
    render(<App />);
    await screen.findByLabelText("规则集名称");
    await screen.findByLabelText("目标策略组");
    fireEvent.change(screen.getByLabelText("规则集名称"), { target: { value: "游戏规则" } });
    fireEvent.change(screen.getByLabelText("规则集地址"), { target: { value: "https://rules.example/games.yaml?token=secret" } });
    fireEvent.change(screen.getByLabelText("规则行为"), { target: { value: "domain" } });
    fireEvent.change(screen.getByLabelText("目标策略组"), { target: { value: "游戏线路" } });
    fireEvent.click(screen.getByText("导入规则集"));
    await waitFor(() => expect(mocks.importRuleProvider).toHaveBeenCalledWith("游戏规则", "https://rules.example/games.yaml?token=secret", "domain", "yaml", "游戏线路"));
    await waitFor(() => expect((screen.getByLabelText("规则集地址") as HTMLInputElement).value).toBe(""));
  });

  it("rejects non-HTTPS rule addresses without calling the backend", async () => {
    mocks.getStatus.mockResolvedValue(status);
    render(<App />);
    await screen.findByLabelText("规则集名称");
    fireEvent.change(screen.getByLabelText("规则集名称"), { target: { value: "游戏规则" } });
    fireEvent.change(screen.getByLabelText("规则集地址"), { target: { value: "http://rules.example/games.yaml" } });
    fireEvent.click(screen.getByText("导入规则集"));
    expect(await screen.findByText("规则集地址必须使用 HTTPS。")).toBeTruthy();
    expect(mocks.importRuleProvider).not.toHaveBeenCalled();
  });

  it("offers a valid MRS behavior and disables import without a profile", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, active_profile_id: null, profiles: [] });
    render(<App />);
    const format = await screen.findByLabelText("规则格式");
    fireEvent.change(format, { target: { value: "mrs" } });
    expect((screen.getByLabelText("规则行为") as HTMLSelectElement).value).toBe("domain");
    expect((screen.getByText("导入规则集") as HTMLButtonElement).disabled).toBe(true);
  });
});
