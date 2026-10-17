import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { StrictMode, forwardRef, useEffect, useImperativeHandle, useRef, type ReactNode } from "react";
import type { Status } from "./types";
import type { DefinePluginFn } from "@decky/api";

const { mocks } = vi.hoisted(() => ({ mocks: {
  getStatus: vi.fn(), getGroups: vi.fn(), startProxy: vi.fn(), stopProxy: vi.fn(),
  setMode: vi.fn(), setTun: vi.fn(), setAutoStart: vi.fn(), importProfile: vi.fn(),
  refreshProfile: vi.fn(), activateProfile: vi.fn(), deleteProfile: vi.fn(),
  selectProxy: vi.fn(), testDelay: vi.fn(), installCore: vi.fn(), getDiagnostics: vi.fn(),
  quickAccessVisible: vi.fn(), setSubscriptionInterval: vi.fn(), setUpdatePreferences: vi.fn(),
  checkForUpdates: vi.fn(), installUpdate: vi.fn(), importRuleProvider: vi.fn(),
  getImportDirectory: vi.fn(), importProfileFile: vi.fn(), openFilePicker: vi.fn(),
} }));

vi.mock("./rpc", () => ({ backend: mocks }));
vi.mock("@decky/api", () => ({
  useQuickAccessVisible: mocks.quickAccessVisible,
  openFilePicker: mocks.openFilePicker,
  FileSelectionType: { FILE: 0 },
  definePlugin: (factory: DefinePluginFn): DefinePluginFn => factory,
}));
vi.mock("@decky/ui", () => ({
  staticClasses: { Title: "decky-title" },
  GamepadButton: { CANCEL: 2 },
  PanelSection: ({ title, children }: { title: string; children: ReactNode }) => <section aria-label={title}>{children}</section>,
  PanelSectionRow: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Focusable: forwardRef<HTMLDivElement, { children: ReactNode; onCancelButton?: (event: CustomEvent) => void; onButtonDown?: (event: CustomEvent<{ button: number }>) => void; onGamepadDirection?: () => void; onActivate?: () => void; tabIndex?: number; onKeyDown?: React.KeyboardEventHandler<HTMLDivElement> }>(function MockFocusable({ children, onCancelButton, onButtonDown, onGamepadDirection: _onGamepadDirection, onActivate: _onActivate, ...props }, ref) {
    const local = useRef<HTMLDivElement>(null);
    useImperativeHandle(ref, () => local.current as HTMLDivElement);
    useEffect(() => {
      const element = local.current;
      const listener = (event: Event): void => { onCancelButton?.(event as CustomEvent); };
      const buttonListener = (event: Event): void => { onButtonDown?.(event as CustomEvent<{ button: number }>); };
      element?.addEventListener("decky-test-cancel", listener);
      element?.addEventListener("decky-test-button", buttonListener);
      return () => {
        element?.removeEventListener("decky-test-cancel", listener);
        element?.removeEventListener("decky-test-button", buttonListener);
      };
    }, [onCancelButton, onButtonDown]);
    return <div ref={local} {...props}>{children}</div>;
  }),
  Field: ({ label, description, children }: { label: string; description: string; children: ReactNode }) => <div>{label}{description}{children}</div>,
  ButtonItem: ({ children, disabled, onClick }: { children: ReactNode; disabled: boolean; onClick: () => void }) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  ToggleField: ({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (checked: boolean) => void }) => <label>{label}<input aria-label={label} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /></label>,
  DropdownItem: ({ label, selectedOption, disabled, rgOptions, onChange }: { label: string; selectedOption: string; disabled: boolean; rgOptions: Array<{ data: string; label: string }>; onChange: (option: { data: string }) => void }) => <label>{label}<select aria-label={label} value={selectedOption} disabled={disabled} onChange={(event) => onChange({ data: event.target.value })}>{rgOptions.map((option) => <option value={option.data} key={option.data}>{option.label}</option>)}</select></label>,
  TextField: ({ label, value, disabled, onChange }: { label: string; value: string; disabled: boolean; onChange: (event: { target: { value: string } }) => void }) => <label>{label}<input aria-label={label} disabled={disabled} value={value} onChange={onChange} /></label>,
}));

import { App } from "./App";
import { clearProfileDraft } from "./profileDraft";
import createPlugin from "./index";

const status: Status = {
  running: false, core_installed: true, core_version: "v1.19.0", platform_supported: true,
  tun_enabled: false, mode: "rule", active_profile_id: "test", auto_start: false,
  profiles: [{ id: "test", name: "我的线路", updated_at: "2026-10-17T00:00:00Z", source_host: "provider.example" }],
  mixed_port: 7890, last_error: null,
};

beforeEach(() => { mocks.quickAccessVisible.mockReturnValue(true); });
afterEach(() => { cleanup(); clearProfileDraft(); vi.useRealTimers(); vi.resetAllMocks(); });

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

describe("local YAML files and back navigation", () => {
  const cancel = (element: HTMLElement): CustomEvent => {
    const event = new CustomEvent("decky-test-cancel", { bubbles: true, cancelable: true });
    fireEvent(element, event);
    return event;
  };

  it("opens the native YAML picker in the discovered download directory and imports once", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/下载");
    mocks.openFilePicker.mockResolvedValue({ path: "/home/deck/下载/my-clash.yaml", realpath: "/home/deck/下载/my-clash.yaml" });
    mocks.importProfileFile.mockResolvedValue(status);
    render(<App />);
    fireEvent.click(await screen.findByText("选择 YAML 文件并导入"));
    await waitFor(() => expect(mocks.openFilePicker).toHaveBeenCalledWith(0, "/home/deck/下载", true, true, undefined, ["yaml", "yml"], false, false));
    await waitFor(() => expect(mocks.importProfileFile).toHaveBeenCalledWith("my-clash", "/home/deck/下载/my-clash.yaml"));
    expect(mocks.importProfileFile).toHaveBeenCalledTimes(1);
    expect(mocks.importProfile).not.toHaveBeenCalled();
  });

  it("keeps a supplied profile name for a selected local file", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    mocks.openFilePicker.mockResolvedValue({ path: "/home/deck/Downloads/clash.yml", realpath: "/home/deck/Downloads/clash.yml" });
    mocks.importProfileFile.mockResolvedValue(status);
    render(<App />);
    fireEvent.change(await screen.findByLabelText("配置名称"), { target: { value: "我的游戏线路" } });
    fireEvent.click(screen.getByText("选择 YAML 文件并导入"));
    await waitFor(() => expect(mocks.importProfileFile).toHaveBeenCalledWith("我的游戏线路", "/home/deck/Downloads/clash.yml"));
  });

  it("finishes importing when Decky hides the QAM for the native file dialog", async () => {
    const imported = { ...status, profiles: [...status.profiles, {
      id: "local-yaml", name: "游戏线路", updated_at: "2026-10-18T00:00:00Z", source_host: "",
    }] };
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    mocks.importProfileFile.mockResolvedValue(imported);
    let choose: (file: { path: string; realpath: string }) => void = () => undefined;
    mocks.openFilePicker.mockImplementation(() => new Promise((resolve) => { choose = resolve; }));
    const plugin = createPlugin();
    function DeckyHost({ visible }: { readonly visible: boolean }) {
      return <>{(visible || plugin.alwaysRender) && <div hidden={!visible}>{plugin.content}</div>}</>;
    }
    const view = render(<DeckyHost visible />);
    fireEvent.click(await screen.findByText("选择 YAML 文件并导入"));
    await waitFor(() => expect(mocks.openFilePicker).toHaveBeenCalledTimes(1));
    mocks.quickAccessVisible.mockReturnValue(false);
    view.rerender(<DeckyHost visible={false} />);
    await act(async () => { choose({ path: "/home/deck/Downloads/游戏线路.yaml", realpath: "/home/deck/Downloads/游戏线路.yaml" }); });
    await waitFor(() => expect(mocks.importProfileFile).toHaveBeenCalledWith("游戏线路", "/home/deck/Downloads/游戏线路.yaml"));
    mocks.getStatus.mockResolvedValue(imported);
    mocks.quickAccessVisible.mockReturnValue(true);
    view.rerender(<DeckyHost visible />);
    await waitFor(() => expect((screen.getByLabelText("配置文件") as HTMLSelectElement).value).toBe("local-yaml"));
    const fileRow = screen.getByText("选择 YAML 文件并导入").parentElement as HTMLElement;
    expect(within(fileRow).getByText(/YAML 文件已导入/)).toBeTruthy();
    expect(screen.getByText("使用此配置")).toBeTruthy();
    expect(mocks.importProfileFile).toHaveBeenCalledTimes(1);
    expect(mocks.activateProfile).not.toHaveBeenCalled();
  });

  it("shows distinct selecting and importing progress beside the YAML file button", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    let choose: (file: { path: string; realpath: string }) => void = () => undefined;
    let finishImport: (next: Status) => void = () => undefined;
    mocks.openFilePicker.mockImplementation(() => new Promise((resolve) => { choose = resolve; }));
    mocks.importProfileFile.mockImplementation(() => new Promise<Status>((resolve) => { finishImport = resolve; }));
    render(<App />);
    const button = await screen.findByText("选择 YAML 文件并导入");
    const fileRow = button.parentElement as HTMLElement;
    fireEvent.click(button);
    await waitFor(() => expect(mocks.openFilePicker).toHaveBeenCalledTimes(1));
    expect(within(fileRow).getByText("正在选择 YAML 文件…")).toBeTruthy();
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { choose({ path: "/home/deck/Downloads/clash.yaml", realpath: "/home/deck/Downloads/clash.yaml" }); });
    expect(within(fileRow).queryByText("正在选择 YAML 文件…")).toBeNull();
    expect(within(fileRow).getByText("正在导入 YAML…")).toBeTruthy();
    fireEvent.click(button);
    expect(mocks.importProfileFile).toHaveBeenCalledTimes(1);
    await act(async () => { finishImport(status); });
    expect(within(fileRow).queryByText("正在导入 YAML…")).toBeNull();
    expect(within(fileRow).getByText(/YAML 文件已导入/)).toBeTruthy();
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps an import failure beside the file button after background polling and allows retry", async () => {
    vi.useFakeTimers();
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    mocks.openFilePicker.mockResolvedValue({ path: "/home/deck/Downloads/clash.yaml", realpath: "/home/deck/Downloads/clash.yaml" });
    mocks.importProfileFile.mockRejectedValueOnce(new Error("YAML 规则集下载失败")).mockResolvedValueOnce(status);
    render(<App />);
    await act(async () => undefined);
    const button = screen.getByText("选择 YAML 文件并导入");
    const fileRow = button.parentElement as HTMLElement;
    await act(async () => { fireEvent.click(button); });
    expect(within(fileRow).getByRole("alert").textContent).toBe("YAML 规则集下载失败");
    const statusReads = mocks.getStatus.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(3001); });
    expect(mocks.getStatus).toHaveBeenCalledTimes(statusReads + 1);
    expect(within(fileRow).getByRole("alert").textContent).toBe("YAML 规则集下载失败");
    await act(async () => { fireEvent.click(button); });
    expect(mocks.importProfileFile).toHaveBeenCalledTimes(2);
    expect(within(fileRow).queryByRole("alert")).toBeNull();
    expect(within(fileRow).getByText(/YAML 文件已导入/)).toBeTruthy();
  });

  it.each([
    [{ path: "/home/deck/Downloads", realpath: "/home/deck/Downloads" }, "请选择具体的 YAML 文件，不要选择文件夹。"],
    [{}, "文件选择器未返回有效路径，请重新选择 YAML 文件。"],
  ])("shows invalid picker results beside the file button before any import RPC", async (selected, message) => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    mocks.openFilePicker.mockResolvedValue(selected);
    render(<App />);
    const button = await screen.findByText("选择 YAML 文件并导入");
    const fileRow = button.parentElement as HTMLElement;
    fireEvent.click(button);
    await waitFor(() => expect(within(fileRow).getByRole("alert").textContent).toBe(message));
    expect(mocks.importProfileFile).not.toHaveBeenCalled();
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("silently cancels the picker, prevents duplicate opening, and retains drafts after reopening", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    let rejectPicker: (reason: unknown) => void = () => undefined;
    mocks.openFilePicker.mockImplementation(() => new Promise((_, reject) => { rejectPicker = reject; }));
    const view = render(<App />);
    fireEvent.change(await screen.findByLabelText("配置名称"), { target: { value: "暂存线路" } });
    fireEvent.change(screen.getByLabelText("订阅地址"), { target: { value: "https://provider.example/sub?token=secret" } });
    const button = screen.getByText("选择 YAML 文件并导入");
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(mocks.openFilePicker).toHaveBeenCalledTimes(1));
    await act(async () => { rejectPicker("User canceled"); });
    expect(mocks.importProfileFile).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.activeElement?.contains(button)).toBe(true);
    view.unmount();
    render(<App />);
    expect((await screen.findByLabelText("配置名称") as HTMLInputElement).value).toBe("暂存线路");
    expect((screen.getByLabelText("订阅地址") as HTMLInputElement).value).toBe("https://provider.example/sub?token=secret");
  });

  it("shows picker errors and keeps the draft for retry", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    mocks.openFilePicker.mockRejectedValue(new Error("文件选择失败"));
    render(<App />);
    fireEvent.click(await screen.findByText("选择 YAML 文件并导入"));
    expect(await screen.findByText("文件选择失败")).toBeTruthy();
    expect(mocks.importProfileFile).not.toHaveBeenCalled();
  });

  it("does not import a late picker result after the page unmounts", async () => {
    mocks.getStatus.mockResolvedValue(status);
    mocks.getImportDirectory.mockResolvedValue("/home/deck/Downloads");
    let choose: (file: { path: string; realpath: string }) => void = () => undefined;
    mocks.openFilePicker.mockImplementation(() => new Promise((resolve) => { choose = resolve; }));
    const view = render(<App />);
    fireEvent.click(await screen.findByText("选择 YAML 文件并导入"));
    await waitFor(() => expect(mocks.openFilePicker).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => { choose({ path: "/home/deck/Downloads/clash.yaml", realpath: "/home/deck/Downloads/clash.yaml" }); });
    expect(mocks.importProfileFile).not.toHaveBeenCalled();
  });

  it("uses B to finish text editing, then requires two root B presses to leave", async () => {
    mocks.getStatus.mockResolvedValue(status);
    const view = render(<App />);
    fireEvent.change(await screen.findByLabelText("导入方式"), { target: { value: "yaml" } });
    const editor = screen.getByLabelText("YAML 内容");
    fireEvent.change(editor, { target: { value: "proxies: []\n" } });
    editor.focus();
    const outerBack = vi.fn();
    view.container.addEventListener("decky-test-cancel", outerBack);
    const first = cancel(editor);
    expect(first.defaultPrevented).toBe(true);
    expect(document.activeElement).not.toBe(editor);
    expect((editor as HTMLTextAreaElement).value).toBe("proxies: []\n");
    expect(outerBack).not.toHaveBeenCalled();
    expect(screen.queryByText("再次按 B 返回 Decky")).toBeNull();
    const second = cancel(document.activeElement as HTMLElement);
    expect(second.defaultPrevented).toBe(true);
    expect(screen.getByText("再次按 B 返回 Decky")).toBeTruthy();
    expect(outerBack).not.toHaveBeenCalled();
    const third = cancel(document.activeElement as HTMLElement);
    expect(third.defaultPrevented).toBe(false);
    expect(outerBack).toHaveBeenCalledTimes(1);
  });

  it("keeps the plugin open after the first root B and lets a second B return to Decky", async () => {
    mocks.getStatus.mockResolvedValue(status);
    const view = render(<App />);
    const control = await screen.findByText("刷新状态");
    const outerBack = vi.fn();
    view.container.addEventListener("decky-test-cancel", outerBack);
    expect(cancel(control).defaultPrevented).toBe(true);
    expect(screen.getByText("再次按 B 返回 Decky")).toBeTruthy();
    expect(outerBack).not.toHaveBeenCalled();
    expect(cancel(control).defaultPrevented).toBe(false);
    expect(outerBack).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("再次按 B 返回 Decky")).toBeNull();
  });

  it("expires the root B confirmation after two seconds", async () => {
    mocks.getStatus.mockResolvedValue(status);
    render(<App />);
    const control = await screen.findByText("刷新状态");
    vi.useFakeTimers();
    expect(cancel(control).defaultPrevented).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(2001); });
    expect(screen.queryByText("再次按 B 返回 Decky")).toBeNull();
    expect(cancel(control).defaultPrevented).toBe(true);
  });

  it("does not treat a held B repeat as a second press", async () => {
    mocks.getStatus.mockResolvedValue(status);
    render(<App />);
    const control = await screen.findByText("刷新状态");
    cancel(control);
    const repeated = new CustomEvent("decky-test-cancel", { bubbles: true, cancelable: true, detail: { is_repeat: true } });
    fireEvent(control, repeated);
    expect(repeated.defaultPrevented).toBe(true);
    expect(screen.getByText("再次按 B 返回 Decky")).toBeTruthy();
    expect(cancel(control).defaultPrevented).toBe(false);
  });

  it("disarms root B after another button or click and after reopening the page", async () => {
    mocks.getStatus.mockResolvedValue(status);
    const view = render(<App />);
    const control = await screen.findByText("刷新状态");
    cancel(control);
    fireEvent(control, new CustomEvent("decky-test-button", { bubbles: true, detail: { button: 1 } }));
    expect(screen.queryByText("再次按 B 返回 Decky")).toBeNull();
    expect(cancel(control).defaultPrevented).toBe(true);
    fireEvent.click(screen.getByLabelText("配置"));
    expect(screen.queryByText("再次按 B 返回 Decky")).toBeNull();
    expect(cancel(control).defaultPrevented).toBe(true);
    view.unmount();
    render(<App />);
    const reopened = await screen.findByText("刷新状态");
    expect(screen.queryByText("再次按 B 返回 Decky")).toBeNull();
    expect(cancel(reopened).defaultPrevented).toBe(true);
  });

  it("allows Escape to finish editing an address without clearing it", async () => {
    mocks.getStatus.mockResolvedValue(status);
    render(<App />);
    const field = await screen.findByLabelText("订阅地址");
    fireEvent.change(field, { target: { value: "https://provider.example/sub" } });
    field.focus();
    fireEvent.keyDown(field, { key: "Escape" });
    expect(document.activeElement).not.toBe(field);
    expect((field as HTMLInputElement).value).toBe("https://provider.example/sub");
  });

  it("uses B to dismiss deletion confirmation without leaving the plugin", async () => {
    mocks.getStatus.mockResolvedValue(status);
    render(<App />);
    fireEvent.click(await screen.findByText("删除此配置"));
    const confirmation = screen.getByText("确认删除“我的线路”");
    expect(cancel(confirmation).defaultPrevented).toBe(true);
    expect(screen.queryByText("确认删除“我的线路”")).toBeNull();
    expect(mocks.deleteProfile).not.toHaveBeenCalled();
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

  it("reports ruleset format corrections without exposing their URLs", async () => {
    mocks.getStatus.mockResolvedValue({ ...status, active_profile_summary: {
      source_rules: true, rules: 26, groups: 4, rule_providers: 2, legacy: false,
      normalized_rule_providers: 1,
    } });
    render(<App />);
    expect(await screen.findByText("已按实际内容修正 1 个规则集格式")).toBeTruthy();
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
