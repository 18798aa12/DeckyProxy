import type { ImportSource } from "./types";

export interface ProfileDraft {
  readonly source: ImportSource;
  readonly name: string;
  readonly value: string;
}

const emptyDraft: ProfileDraft = { source: "url", name: "", value: "" };
const lifetime = 30 * 60 * 1000;
let sessionDraft: { readonly value: ProfileDraft; readonly expires: number } | null = null;
let expiry: ReturnType<typeof setTimeout> | undefined;

// QAM content unmounts when closed. Drafts stay only in this plugin's memory,
// never browser storage, and disappear when Decky reloads or after inactivity.
export function readProfileDraft(): ProfileDraft {
  if (!sessionDraft || sessionDraft.expires <= Date.now()) {
    sessionDraft = null;
    return emptyDraft;
  }
  return sessionDraft.value;
}

export function writeProfileDraft(value: ProfileDraft): void {
  clearTimeout(expiry);
  sessionDraft = { value: { ...value }, expires: Date.now() + lifetime };
  expiry = setTimeout(clearProfileDraft, lifetime);
}

export function clearProfileDraft(): void {
  clearTimeout(expiry);
  expiry = undefined;
  sessionDraft = null;
}
