import { Focusable, GamepadButton, type GamepadEvent } from "@decky/ui";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { styles } from "./styles";

interface CancelEvent {
  preventDefault(): void;
  stopPropagation(): void;
}

export function EditingBoundary({ children }: { readonly children: ReactNode }) {
  const boundary = useRef<HTMLDivElement>(null);
  const deadline = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [confirmExit, setConfirmExit] = useState(false);

  const resetExit = useCallback((): void => {
    clearTimeout(timer.current);
    timer.current = undefined;
    deadline.current = 0;
    setConfirmExit(false);
  }, []);

  useEffect(() => () => { clearTimeout(timer.current); }, []);

  const finishEditing = (event: CancelEvent): boolean => {
    const editing = document.activeElement;
    if (!(editing instanceof HTMLInputElement || editing instanceof HTMLTextAreaElement)
      || !boundary.current?.contains(editing)) return false;
    event.preventDefault();
    event.stopPropagation();
    resetExit();
    editing.blur();
    (editing.closest<HTMLElement>("[data-text-editor]") ?? boundary.current).focus();
    return true;
  };

  const handleBack = (event: GamepadEvent): void => {
    if (event.detail?.is_repeat) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (finishEditing(event)) return;
    if (deadline.current > Date.now()) {
      resetExit();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    clearTimeout(timer.current);
    deadline.current = Date.now() + 2000;
    setConfirmExit(true);
    timer.current = setTimeout(resetExit, 2000);
  };

  return <Focusable ref={boundary} tabIndex={-1} onCancelButton={handleBack}
    onClickCapture={resetExit} onPointerDownCapture={resetExit}
    onKeyDownCapture={(event) => { if (event.key !== "Escape") resetExit(); }}
    onGamepadDirection={resetExit}
    onButtonDown={(event) => { if (event.detail.button !== GamepadButton.CANCEL) resetExit(); }}
    onKeyDown={(event) => { if (event.key === "Escape") finishEditing(event); }}>
    {confirmExit && <div role="status" aria-live="polite" style={styles.notice}>再次按 B 返回 Decky</div>}
    {children}
  </Focusable>;
}
