export type ProxyMode = "rule" | "global" | "direct";
export type ImportSource = "url" | "yaml";
export type RuleBehavior = "classical" | "domain" | "ipcidr";
export type RuleFormat = "yaml" | "text" | "mrs";

export interface ProfileSummary {
  readonly source_rules: boolean;
  readonly rules: number;
  readonly groups: number;
  readonly rule_providers: number;
  readonly legacy: boolean;
}

export interface PluginUpdate {
  readonly available: boolean;
  readonly version: string | null;
  readonly checked_at: string | null;
  readonly error: string | null;
  readonly state: "idle" | "checking" | "available" | "preparing" | "installing";
  readonly supported: boolean;
}

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
  readonly version?: string;
  readonly subscription_interval_hours?: number;
  readonly subscription_last_check?: string | null;
  readonly subscription_error?: string | null;
  readonly auto_check_updates?: boolean;
  readonly auto_install_updates?: boolean;
  readonly update?: PluginUpdate;
  readonly active_profile_summary?: ProfileSummary | null;
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
