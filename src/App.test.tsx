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
  quickAccessVisible: vi.fn(),
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
