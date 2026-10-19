import { useEffect, useRef, type ReactNode } from "react";

/** Cached results only: opening this surface must never initiate a read. */
export function ReferenceDrawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const opener = document.activeElement;
    const width = window.matchMedia("(min-width: 1280px)");
    const display = () => {
      const focused = element.contains(document.activeElement)
        ? (document.activeElement as HTMLElement)
        : null;
      element.close();
      if (width.matches) element.show();
      else element.showModal();
      focused?.focus();
    };
    display();
    width.addEventListener("change", display);
    return () => {
      width.removeEventListener("change", display);
      element.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="reference-drawer"
      aria-labelledby="reference-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header className="reference-heading">
        <h2 id="reference-title">{title}</h2>
        <button onClick={onClose}>参照を閉じる</button>
      </header>
      {children}
    </dialog>
  );
}
