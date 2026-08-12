import { Check, CircleAlert, CircleDashed } from "lucide-react";

import type { OnboardingStatusResponse } from "@/lib/api";
import { resolveSetupStepStatus, STEP_STATUS_LABELS } from "@/lib/onboarding";

const STEPS = [
  { key: "workspace", label: "Business" },
  { key: "menu", label: "Menu" },
  { key: "inventory", label: "Inventory" },
  { key: "prices", label: "Prices" },
  { key: "fiscal", label: "Fiscal" },
  { key: "pos", label: "POS" },
] as const;

export function OnboardingProgress({ status }: { status: OnboardingStatusResponse }) {
  return (
    <ol className="setup-progress" aria-label="Setup progress">
      {STEPS.map((step, index) => {
        const stepStatus = resolveSetupStepStatus(step.key, status);
        return (
          <li className={`is-${stepStatus.toLowerCase().replace("_", "-")}`} key={step.key}>
            <span className="setup-progress-number" aria-hidden="true">
              {stepStatus === "COMPLETE" ? <Check /> : stepStatus === "NEEDS_ATTENTION" ? <CircleAlert /> : <CircleDashed />}
            </span>
            <span><strong>{index + 1}. {step.label}</strong><small>{STEP_STATUS_LABELS[stepStatus]}</small></span>
          </li>
        );
      })}
    </ol>
  );
}
