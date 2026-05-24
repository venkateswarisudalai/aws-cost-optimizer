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
      className="inline-flex items-center gap-1.5 rounded-md border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:border-gray-600 hover:bg-gray-700 transition-colors"
      title={text}
    >
      {copied ? (
        <>
          <Check size={12} className="text-emerald-400" />
          Copied
        </>
      ) : (
        <>
          <Copy size={12} />
          Copy fix
        </>
      )}
    </button>
  );
}
