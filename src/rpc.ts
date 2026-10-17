import { callable } from "@decky/api";
import { unwrap } from "./state";
import type { Group, ProxyMode, Result, RuleBehavior, RuleFormat, Status } from "./types";

const getStatus = callable<[], Result<Status>>("get_status");
const importProfile = callable<[name: string, url: string, content: string], Result<Status>>("import_profile");
const refreshProfile = callable<[profileId: string], Result<Status>>("refresh_profile");
const activateProfile = callable<[profileId: string], Result<Status>>("activate_profile");
const deleteProfile = callable<[profileId: string], Result<Status>>("delete_profile");
const startProxy = callable<[], Result<Status>>("start_proxy");
const stopProxy = callable<[], Result<Status>>("stop_proxy");
const setMode = callable<[mode: ProxyMode], Result<Status>>("set_mode");
const setTun = callable<[enabled: boolean], Result<Status>>("set_tun");
const setAutoStart = callable<[enabled: boolean], Result<Status>>("set_auto_start");
const getGroups = callable<[], Result<Group[]>>("get_groups");
const selectProxy = callable<[group: string, proxy: string], Result<Group[]>>("select_proxy");
const testDelay = callable<[name: string], Result<{ delay_ms: number }>>("test_delay");
const installCore = callable<[], Result<Status>>("install_core");
const getDiagnostics = callable<[], Result<string>>("get_diagnostics");
const setSubscriptionInterval = callable<[hours: number], Result<Status>>("set_subscription_interval");
const setUpdatePreferences = callable<[autoCheck: boolean, autoInstall: boolean], Result<Status>>("set_update_preferences");
const checkForUpdates = callable<[], Result<Status>>("check_for_updates");
const installUpdate = callable<[], Result<Status>>("install_update");
const importRuleProvider = callable<[name: string, url: string, behavior: RuleBehavior, format: RuleFormat, target: string], Result<Status>>("import_rule_provider");

export const backend = {
  getStatus: async (): Promise<Status> => unwrap(await getStatus()),
  importProfile: async (name: string, url: string, content: string): Promise<Status> => unwrap(await importProfile(name, url, content)),
  refreshProfile: async (id: string): Promise<Status> => unwrap(await refreshProfile(id)),
  activateProfile: async (id: string): Promise<Status> => unwrap(await activateProfile(id)),
  deleteProfile: async (id: string): Promise<Status> => unwrap(await deleteProfile(id)),
  startProxy: async (): Promise<Status> => unwrap(await startProxy()),
  stopProxy: async (): Promise<Status> => unwrap(await stopProxy()),
  setMode: async (mode: ProxyMode): Promise<Status> => unwrap(await setMode(mode)),
  setTun: async (enabled: boolean): Promise<Status> => unwrap(await setTun(enabled)),
  setAutoStart: async (enabled: boolean): Promise<Status> => unwrap(await setAutoStart(enabled)),
  getGroups: async (): Promise<Group[]> => unwrap(await getGroups()),
  selectProxy: async (group: string, proxy: string): Promise<Group[]> => unwrap(await selectProxy(group, proxy)),
  testDelay: async (name: string): Promise<{ delay_ms: number }> => unwrap(await testDelay(name)),
  installCore: async (): Promise<Status> => unwrap(await installCore()),
  getDiagnostics: async (): Promise<string> => unwrap(await getDiagnostics()),
  setSubscriptionInterval: async (hours: number): Promise<Status> => unwrap(await setSubscriptionInterval(hours)),
  setUpdatePreferences: async (autoCheck: boolean, autoInstall: boolean): Promise<Status> => unwrap(await setUpdatePreferences(autoCheck, autoInstall)),
  checkForUpdates: async (): Promise<Status> => unwrap(await checkForUpdates()),
  installUpdate: async (): Promise<Status> => unwrap(await installUpdate()),
  importRuleProvider: async (name: string, url: string, behavior: RuleBehavior, format: RuleFormat, target: string): Promise<Status> => unwrap(await importRuleProvider(name, url, behavior, format, target)),
};
