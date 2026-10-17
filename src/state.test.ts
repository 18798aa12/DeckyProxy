import { describe, expect, it } from "vitest";
import { canStart, formatDelay, prepareImport, safeError, unwrap } from "./state";
import type { Status } from "./types";

const ready: Status = {
  running: false, core_installed: true, core_version: "v1.19.0",
  platform_supported: true, tun_enabled: false, mode: "rule",
  active_profile_id: "home", profiles: [], auto_start: false,
  last_error: null, mixed_port: 7890,
};

describe("safe proxy controls", () => {
  it("requires a supported platform, installed core and selected profile to start", () => {
    expect(canStart(ready)).toBe(true);
    expect(canStart({ ...ready, core_installed: false })).toBe(false);
    expect(canStart({ ...ready, active_profile_id: null })).toBe(false);
    expect(canStart({ ...ready, platform_supported: false })).toBe(false);
  });

  it("imports exactly one source and preserves private YAML content", () => {
    expect(prepareImport(" Home ", "url", " https://provider.example/sub?token=secret "))
      .toEqual({ name: "Home", url: "https://provider.example/sub?token=secret", content: "" });
    expect(prepareImport("Home", "yaml", "proxies:\n  - name: A"))
      .toEqual({ name: "Home", url: "", content: "proxies:\n  - name: A" });
  });

  it("rejects missing names, empty sources and unsupported URL protocols", () => {
    expect(() => prepareImport("", "yaml", "proxies: []")).toThrow("名称");
    expect(() => prepareImport("Home", "yaml", "  ")).toThrow("内容");
    expect(() => prepareImport("Home", "url", "file:///etc/passwd")).toThrow("HTTPS");
    expect(() => prepareImport("Home", "url", "https://user:password@provider.example/sub"))
      .toThrow("用户名");
  });

  it("matches the backend limit of 64 characters for profile names", () => {
    expect(prepareImport("线".repeat(64), "yaml", "proxies: []").name.length).toBe(64);
    expect(() => prepareImport("线".repeat(65), "yaml", "proxies: []")).toThrow("64");
    expect(prepareImport("🎮".repeat(64), "yaml", "proxies: []").name).toBe("🎮".repeat(64));
  });

  it("propagates backend failures without showing a private URL", () => {
    expect(() => unwrap({ ok: false, error: "无法获取 https://provider.example/sub?token=secret" }))
      .toThrow("无法获取 [已隐藏地址]");
    expect(safeError(new Error("transport https://private.example/secret")))
      .not.toContain("secret");
    expect(unwrap({ ok: true, data: 42 })).toBe(42);
  });

  it("does not label a failed latency test as fast", () => {
    expect(formatDelay(null)).toBe("未测试");
    expect(formatDelay(0)).toBe("超时");
    expect(formatDelay(-1)).toBe("超时");
    expect(formatDelay(78)).toBe("78 ms");
  });
});
