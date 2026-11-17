"use client";

import { useState } from "react";
import type { Family, Study } from "@/lib/bench";

const MODEL: Record<string, string> = {
  "google.gemma-3-12b-it": "Gemma 3 12B",
  "deepseek.v3.2": "DeepSeek V3.2",
};

function decisionChip(d: string) {
  return d === "promote?" ? "chip up" : d === "reject" ? "chip down" : "chip";
}

function who(s: Study, role: string) {
  const r = s.spend.by_role[role];
  return r ? `${role} · ${MODEL[r.model] ?? r.model}` : role;
}

function params(p: Record<string, number[] | number>) {
  const items = Object.entries(p).filter(([, v]) => !(Array.isArray(v) && v.length === 1 && v[0] === 0));
  if (!items.length) return "full grid";
  return items.map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("/") : v}`).join(" · ");
}

function short(idea: string) {
  return idea.length > 58 ? idea.slice(0, 56) + "…" : idea;
}

export default function StudyReplay({ studies }: { studies: Study[] }) {
  const [i, setI] = useState(0);
  const s = studies[i];
  return (
    <div>
      <div className="row" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }} role="tablist">
        {studies.map((x, k) => (
          <button
            key={x.id}
            role="tab"
            aria-selected={k === i}
            className={k === i ? "btn pri sm" : "btn sm"}
            onClick={() => setI(k)}
          >
            {short(x.idea)} <span className={decisionChip(x.verdict.decision)}>{x.verdict.decision}</span>
          </button>
        ))}
      </div>

      <div className="panel flat">
        <div className="row" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span className="chip acc">{s.source_label}</span>
          <span className="chip">
            {s.dataset.rows.toLocaleString("en-US")} days · {s.dataset.start} → {s.dataset.end}
          </span>
          <span className="chip">checks {s.dataset.passed ? "passed" : "FAILED"} · sha {s.dataset.sha256}</span>
          <span className="chip">{s.trials} trials · {s.looks} looks</span>
          <span className="chip">
            {s.spend.calls} model calls · ${s.spend.usd.toFixed(4)} · {s.seconds} s
          </span>
        </div>
        <p style={{ fontSize: 15, fontWeight: 700, margin: "14px 0 4px", color: "var(--ink)" }}>“{s.idea}”</p>

        <ol className="steps">
          <li>
            <div className="stephead">{who(s, "intake")}</div>
            <p>
              Style: <b>{s.spec.style}</b>. {s.spec.summary}
            </p>
          </li>
          <li>
            <div className="stephead">{who(s, "planner")} → plan critic</div>
            <p>{s.plan.hypothesis}</p>
            <p className="muted">
              Templates <b>{s.plan.templates.join(", ")}</b> · budget {s.plan.trial_budget} trials · {s.plan.rounds} rounds.{" "}
              {s.plan.rationale}
            </p>
            {s.plan_review ? (
              <p className="muted">
                Plan critic:{" "}
                {s.plan_review.approve
                  ? s.plan_revisions
                    ? `sent the plan back ${s.plan_revisions}×, then approved.`
                    : "approved."
                  : `sent the plan back ${s.plan_revisions}×; the study went ahead after the allowed revision. Last note: ${s.plan_review.changes}`}
              </p>
            ) : null}
          </li>
          {s.rounds.map((r) => (
            <li key={r.round}>
              <div className="stephead">
                round {r.round} · {r.by === "researcher" ? who(s, "researcher") : r.by}
              </div>
              {r.by === "researcher" ? (
                <p>
                  {r.diagnosis ? <span className="muted">{r.diagnosis} </span> : null}
                  {r.hypothesis}
                </p>
              ) : (
                <p className="muted">Each planned template&apos;s full grid, filters off: coverage before refinement.</p>
              )}
              <ul className="exps">
                {r.experiments.map((e, k) => (
                  <li key={k}>
                    <b>{e.template}</b> <span className="mono">{params(e.params)}</span>
                    {r.by === "researcher" ? <span className="muted"> · {e.rationale}</span> : null}
                  </li>
                ))}
              </ul>
              {r.families.length ? <FamilyTable fams={r.families} /> : <p className="muted">No family ran this round.</p>}
              {r.refused_by_code.length ? (
                <p className="refused">Refused by code: {r.refused_by_code.join(" · ")}</p>
              ) : null}
              {r.critic ? (
                <p className="critic">
                  <b>{who(s, "critic")}:</b> {r.critic.verdict.replace("_", " ")}
                  {r.critic.concerns.length ? ` · ${r.critic.concerns.join(" · ")}` : ""}
                </p>
              ) : null}
            </li>
          ))}
          <li>
            <div className="stephead">verdict · code</div>
            <p>
              <span className={decisionChip(s.verdict.decision)}>{s.verdict.decision}</span> {s.verdict.reason}.
            </p>
            <p className="muted">
              Stopped by: {s.stop_reason}. The bar rises with looks: after {s.looks} looks a family needs OOS Sharpe ≥{" "}
              {s.verdict.required_oos_sharpe}, not just 0.4.
            </p>
            {s.holdout ? (
              <p>
                <b>Sealed holdout, opened once</b> ({s.holdout.window[0]} → {s.holdout.window[1]}): Sharpe{" "}
                <b style={{ color: s.holdout.passed ? "var(--up)" : "var(--down)" }}>{s.holdout.sharpe}</b> against
                buy-and-hold {s.holdout.buy_hold_sharpe} · {s.holdout.passed ? "passed" : "failed"}.
              </p>
            ) : (
              <p className="muted">Holdout left sealed: nothing earned a look.</p>
            )}
          </li>
          {s.report ? (
            <li>
              <div className="stephead">
                {who(s, "reporter")} · numbers {s.report_check?.passed ? "all checked against the ledger" : "FLAGGED"}
              </div>
              <p style={{ fontWeight: 700, color: "var(--ink)" }}>{s.report.title}</p>
              <p>{s.report.summary}</p>
              <ul className="exps">
                {s.report.findings.map((f, k) => (
                  <li key={k}>{f}</li>
                ))}
              </ul>
              <p>{s.report.verdict}</p>
            </li>
          ) : null}
          <li>
            <div className="stephead">human gate</div>
            {s.verdict.decision === "promote?" ? (
              <p>
                <span className="chip up">promote?</span> The study stops here and waits for a person. This recorded run was
                left unapproved.
              </p>
            ) : (
              <p className="muted">Not reached: a rejected idea needs no approval.</p>
            )}
          </li>
        </ol>

        <div className="scroll" style={{ marginTop: 12 }}>
          <table className="rank">
            <thead>
              <tr>
                <th>role</th>
                <th>model</th>
                <th>calls</th>
                <th>cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.spend.by_role).map(([role, r]) => (
                <tr key={role}>
                  <td>{role}</td>
                  <td>{MODEL[r.model] ?? r.model}</td>
                  <td>{r.calls}</td>
                  <td>${r.usd.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function FamilyTable({ fams }: { fams: Family[] }) {
  return (
    <div className="scroll">
      <table className="rank">
        <thead>
          <tr>
            <th>family</th>
            <th>template</th>
            <th>trials</th>
            <th>in-sample Sharpe</th>
            <th>walk-forward OOS</th>
            <th>blocks +</th>
            <th>buy &amp; hold OOS</th>
            <th>clears 0.4</th>
          </tr>
        </thead>
        <tbody>
          {fams.map((f) => (
            <tr key={f.id}>
              <td style={{ color: "var(--ink)", fontWeight: 700 }}>{f.id}</td>
              <td>{f.template}</td>
              <td>{f.trials}</td>
              <td>{f.in_sample_sharpe}</td>
              <td>{f.oos_sharpe}</td>
              <td>{f.positive_folds}/5</td>
              <td>{f.buy_hold_oos_sharpe}</td>
              <td>
                <span className={f.passed_walk_forward ? "chip up" : "chip down"}>
                  {f.passed_walk_forward ? "yes" : "no"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
