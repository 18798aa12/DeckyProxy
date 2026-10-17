import type { CSSProperties } from "react";

export const styles = {
  status: { padding: "12px 14px", background: "#202A35", borderLeft: "3px solid #1A9FFF", borderRadius: 3, marginBottom: 6 } satisfies CSSProperties,
  statusName: { fontSize: 19, fontWeight: 700, marginBottom: 5 } satisfies CSSProperties,
  detail: { fontSize: 12, lineHeight: 1.6, color: "#BAC8D6", overflowWrap: "anywhere" } satisfies CSSProperties,
  error: { padding: "9px 14px", marginBottom: 8, color: "#F5A7AE", background: "#35272E", fontSize: 13, lineHeight: 1.5, overflowWrap: "anywhere" } satisfies CSSProperties,
  notice: { padding: "6px 14px", color: "#67D9BF", fontSize: 12, lineHeight: 1.5 } satisfies CSSProperties,
  note: { fontSize: 12, color: "#BAC8D6", lineHeight: 1.6, margin: "4px 0 10px", overflowWrap: "anywhere" } satisfies CSSProperties,
  textarea: { display: "block", width: "100%", boxSizing: "border-box", minHeight: 130, padding: 10, color: "#EAF1F8", background: "#18212B", border: "1px solid #8399AD", borderRadius: 3, font: "inherit", fontSize: 13, lineHeight: 1.5, resize: "vertical" } satisfies CSSProperties,
  diagnostics: { whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: "inherit", fontSize: 12, lineHeight: 1.6, color: "#BAC8D6" } satisfies CSSProperties,
};
