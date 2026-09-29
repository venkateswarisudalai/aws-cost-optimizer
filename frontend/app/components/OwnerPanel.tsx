"use client";

import { Loader2, MessageSquare, UserRound } from "lucide-react";
import { useState } from "react";
import { askOwner } from "../lib/api";
import type { Confirmation, Finding, Owner } from "../lib/types";

function ownerText(o: Owner | null | undefined): { who: string; how: string } {
  if (!o || o.source === "unknown") {
    return { who: "Unknown", how: o?.note ?? "Not looked up in this scan." };
  }
  if (o.source === "tag") {
    return { who: o.name ?? "?", how: `from the “${o.tag_key}” tag` };
  }
  const when = o.event_time ? ` on ${o.event_time.slice(0, 10)}` : "";
  return {
    who: o.name ?? "?",
    how: `CloudTrail: ${o.relationship ?? "created"} it (${o.event_name})${when}`,
  };
}

const STATUS: Record<string, { label: string; cls: string }> = {
  pending: {
    label: "Asked on Slack · waiting",
    cls: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  },
  keep: {
    label: "Owner: keep it",
    cls: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  },
  delete_ok: {
    label: "Owner: OK to delete",
    cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  },
};

export function ConfirmationBadge({ c }: { c?: Confirmation }) {
  if (!c) return null;
  const s = STATUS[c.status] ?? STATUS.pending;
  return (
    <span
      title={c.note ?? undefined}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${s.cls}`}
    >
      <MessageSquare size={11} />
      {s.label}
    </span>
  );
}

/** Who owns the resource, and the Slack "is this still needed?" action. */
export function OwnerPanel({
  f,
  confirmation,
  onAsked,
  slackOn,
}: {
  f: Finding;
  confirmation?: Confirmation;
  onAsked: () => void;
  slackOn: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const { who, how } = ownerText(f.owner);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      const res = await askOwner(f.id);
      setPreview(res.message.text);
      setNote(
        res.sent
          ? "Sent. Answers appear here after “Check Slack replies”."
          : res.reason === "demo mode"
            ? "Demo: simulated, nothing was sent to Slack."
            : "Preview only: set AWSCO_SLACK_BOT_TOKEN to send it.",
      );
      onAsked();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <UserRound size={14} className="shrink-0 text-gray-400" />
          <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
            Owner
          </span>
          <span className="font-medium text-gray-200">{who}</span>
          <span className="text-gray-500">· {how}</span>
        </div>
        <div className="flex items-center gap-2">
          <ConfirmationBadge c={confirmation} />
          {!slackOn && (
            <span
              className="text-[11px] text-gray-600"
              title="Optional — see .env.example"
            >
              Slack not set up
            </span>
          )}
          {slackOn && (
            <button
              onClick={ask}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1 font-medium text-gray-200 transition hover:bg-white/[0.08] disabled:opacity-50"
            >
              {busy ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <MessageSquare size={12} />
              )}
              {confirmation ? "Ask again on Slack" : "Ask on Slack"}
            </button>
          )}
        </div>
      </div>
      {confirmation?.note && (
        <p className="mt-2 text-gray-400">
          “{confirmation.note}”{" "}
          {confirmation.responder && <>— {confirmation.responder}</>}
        </p>
      )}
      {note && <p className="mt-2 text-gray-500">{note}</p>}
      {preview && (
        <p className="mt-1 rounded bg-black/30 px-2 py-1.5 font-mono text-[11px] text-gray-400">
          {preview}
        </p>
      )}
      {error && <p className="mt-2 text-rose-300">{error}</p>}
    </div>
  );
}
