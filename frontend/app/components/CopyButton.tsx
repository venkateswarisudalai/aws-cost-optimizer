"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  function onClick() {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <button
      onClick={onClick}
      title={text}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition ${
        copied
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
          : "border-white/10 bg-white/[0.03] text-gray-300 hover:border-white/20 hover:bg-white/[0.07]"
      }`}
    >
      {copied ? (
        <>
          <Check size={13} />
          Copied
        </>
      ) : (
        <>
          <Copy size={13} />
          Copy fix
        </>
      )}
    </button>
  );
}
