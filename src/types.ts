export type ProxyMode = "rule" | "global" | "direct";
export type ImportSource = "url" | "yaml";

export interface Profile {
  readonly id: string;
  readonly name: string;
  readonly updated_at: string;
  readonly source_host: string | null;
}

export interface Status {
  readonly running: boolean;
  readonly core_installed: boolean;
  readonly core_version: string;
  readonly platform_supported: boolean;
  readonly tun_enabled: boolean;
  readonly mode: ProxyMode;
  readonly active_profile_id: string | null;
  readonly profiles: readonly Profile[];
  readonly auto_start: boolean;
  readonly last_error: string | null;
  readonly mixed_port: number;
}

export interface ProxyOption {
  readonly name: string;
  readonly delay_ms: number | null;
}

export interface Group {
  readonly name: string;
  readonly type: string;
  readonly now: string;
  readonly options: readonly ProxyOption[];
}

export type Result<T> = { readonly ok: true; readonly data: T } | { readonly ok: false; readonly error: string };
export type StatusAction = (label: string, operation: () => Promise<Status>) => Promise<boolean>;
