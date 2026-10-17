import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { GroupPanel } from "./GroupPanel";
import type { Group } from "./types";

vi.mock("@decky/ui", () => ({
  PanelSection: ({ title, children }: { title: string; children: ReactNode }) => <section aria-label={title}>{children}</section>,
  PanelSectionRow: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ButtonItem: ({ children, description, disabled, onClick }: { children: ReactNode; description?: ReactNode; disabled?: boolean; onClick: () => void }) => <div><button disabled={disabled} onClick={onClick}>{children}</button>{description}</div>,
  DropdownItem: ({ label, selectedOption, disabled, rgOptions, onChange }: { label: string; selectedOption: string; disabled: boolean; rgOptions: readonly { data: string; label: string }[]; onChange: (option: { data: string }) => void }) => <label>{label}<select aria-label={label} value={selectedOption} disabled={disabled} onChange={(event) => onChange({ data: event.target.value })}>{rgOptions.map((option) => <option value={option.data} key={option.data}>{option.label}</option>)}</select></label>,
}));

const selected: Group = {
  name: "游戏线路", type: "Selector", now: "东京", options: [
    { name: "东京", delay_ms: null }, { name: "香港", delay_ms: 68 },
  ],
};
const automatic: Group = { ...selected, name: "自动选择", type: "URLTest" };
const latencyNote = "延迟为测试站点的往返时间，无法代表游戏服务器延迟。";

const openList = (count: number): void => {
  fireEvent.click(screen.getByRole("button", { name: `展开策略组与节点（${count} 组）` }));
};
const toggleGroup = (name: string, open = true): void => {
  fireEvent.click(screen.getByRole("button", { name: `${open ? "展开" : "收起"}“${name}”` }));
};

afterEach(cleanup);

describe("collapsible groups and nodes", () => {
  it("shows only one disclosure for a large list until it is opened", () => {
    const groups = Array.from({ length: 216 }, (_, index) => ({ ...selected, name: `策略组 ${index}` }));
    const onSelect = vi.fn();
    const onTest = vi.fn();
    render(<GroupPanel groups={groups} running busy={false} onSelect={onSelect} onTest={onTest} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "展开策略组与节点（216 组）" })).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText(latencyNote)).toBeNull();
    expect(screen.queryByText(/东京/)).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
    expect(onTest).not.toHaveBeenCalled();
  });

  it("opens summaries first and reveals a group's controls only on its own disclosure", () => {
    const onSelect = vi.fn();
    const onTest = vi.fn();
    render(<GroupPanel groups={[selected, automatic]} running busy={false} onSelect={onSelect} onTest={onTest} />);
    openList(2);
    expect(screen.getAllByText("当前：东京 · 2 个选项")).toHaveLength(2);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText(latencyNote)).toBeTruthy();
    toggleGroup(selected.name);
    expect(screen.getByLabelText(selected.name)).toBeTruthy();
    expect(screen.queryByLabelText(automatic.name)).toBeNull();
    expect(screen.getByRole("button", { name: "测试“东京”延迟" })).toBeTruthy();
    toggleGroup(selected.name, false);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "测试“东京”延迟" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "收起策略组与节点（2 组）" }));
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByText(latencyNote)).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
    expect(onTest).not.toHaveBeenCalled();
  });

  it("keeps expanded selection and latency actions working with their original arguments", () => {
    const onSelect = vi.fn();
    const onTest = vi.fn();
    render(<GroupPanel groups={[selected]} running busy={false} onSelect={onSelect} onTest={onTest} />);
    openList(1);
    toggleGroup(selected.name);
    fireEvent.change(screen.getByLabelText(selected.name), { target: { value: "香港" } });
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("游戏线路", "香港");
    fireEvent.click(screen.getByRole("button", { name: "测试“东京”延迟" }));
    expect(onTest).toHaveBeenCalledExactlyOnceWith("东京");
  });

  it.each(["select", "Selector", "URLTest", "Fallback", "LoadBalance"])("preserves %s selection restrictions", (type) => {
    render(<GroupPanel groups={[{ ...selected, type }]} running busy={false} onSelect={vi.fn()} onTest={vi.fn()} />);
    openList(1);
    toggleGroup(selected.name);
    expect((screen.getByLabelText(selected.name) as HTMLSelectElement).disabled).toBe(!["select", "Selector"].includes(type));
  });

  it("disables only backend actions while busy and lets the list be folded", () => {
    const onSelect = vi.fn();
    const onTest = vi.fn();
    render(<GroupPanel groups={[selected]} running busy onSelect={onSelect} onTest={onTest} />);
    openList(1);
    toggleGroup(selected.name);
    expect((screen.getByLabelText(selected.name) as HTMLSelectElement).disabled).toBe(true);
    const test = screen.getByRole("button", { name: "测试“东京”延迟" });
    expect((test as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(test);
    toggleGroup(selected.name, false);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
    expect(onTest).not.toHaveBeenCalled();
  });

  it.each(["", "DIRECT", "REJECT"])("does not test the non-proxy selection %s", (now) => {
    const onTest = vi.fn();
    render(<GroupPanel groups={[{ ...selected, now }]} running busy={false} onSelect={vi.fn()} onTest={onTest} />);
    openList(1);
    toggleGroup(selected.name);
    const test = screen.getByRole("button", { name: `测试“${now}”延迟` });
    expect((test as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(test);
    expect(onTest).not.toHaveBeenCalled();
  });

  it("retains disclosure state across fresh polling objects, latency changes, and reordering", () => {
    const props = { running: true, busy: false, onSelect: vi.fn(), onTest: vi.fn() };
    const view = render(<GroupPanel {...props} groups={[selected, automatic]} />);
    openList(2);
    toggleGroup(selected.name);
    const updated = { ...selected, now: "香港", options: selected.options.map((option) => ({ ...option, delay_ms: 72 })) };
    view.rerender(<GroupPanel {...props} groups={[{ ...automatic }, updated]} />);
    expect((screen.getByLabelText(selected.name) as HTMLSelectElement).value).toBe("香港");
    expect(screen.getByRole("option", { name: "香港 · 72 ms" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "收起“游戏线路”" })).toBeTruthy();
    expect(screen.queryByLabelText(automatic.name)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "收起策略组与节点（2 组）" }));
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("keeps the existing empty and stopped messages without a disclosure", () => {
    const props = { busy: false, onSelect: vi.fn(), onTest: vi.fn() };
    const view = render(<GroupPanel {...props} running={false} groups={[selected]} />);
    expect(screen.getByText("启用代理后可选择节点和测试延迟。")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    view.rerender(<GroupPanel {...props} running groups={[]} />);
    expect(screen.getByText("暂无可选策略组，点击刷新状态重试。")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
