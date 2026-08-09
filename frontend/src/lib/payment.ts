import type { PaymentLineInput, PaymentMethod } from "./api";

export type PaymentMode = PaymentMethod | "SPLIT" | null;

type PaymentDraft = {
  mode: PaymentMode;
  totalMinor: string;
  cashMinor: string | null;
  cashReceivedMinor: string | null;
  cardMinor: string | null;
  otherMinor: string | null;
  otherReference: string;
};

export function paymentRequest(draft: PaymentDraft) {
  const total = BigInt(draft.totalMinor);
  if (total === BigInt(0)) {
    return { lines: [] as PaymentLineInput[], error: "", remainingMinor: BigInt(0), changeMinor: BigInt(0) };
  }
  if (!draft.mode) return invalid("Choose a payment method.", total);

  if (draft.mode !== "SPLIT") {
    if (draft.mode === "CASH") {
      if (draft.cashReceivedMinor === null) return invalid("Enter the cash received.", total);
      const received = BigInt(draft.cashReceivedMinor);
      if (received < total) return invalid("Cash received is below the order total.", total - received);
      return {
        lines: [{ method: "CASH" as const, amount_minor: draft.totalMinor, cash_received_minor: draft.cashReceivedMinor }],
        error: "",
        remainingMinor: BigInt(0),
        changeMinor: received - total,
      };
    }
    return {
      lines: [{
        method: draft.mode,
        amount_minor: draft.totalMinor,
        ...(draft.mode === "OTHER" && draft.otherReference.trim()
          ? { reference: draft.otherReference.trim() }
          : {}),
      }],
      error: "",
      remainingMinor: BigInt(0),
      changeMinor: BigInt(0),
    };
  }

  if ([draft.cashMinor, draft.cardMinor, draft.otherMinor].some((value) => value === null)) {
    return invalid("Enter valid payment amounts.", total);
  }
  const cash = BigInt(draft.cashMinor!);
  const card = BigInt(draft.cardMinor!);
  const other = BigInt(draft.otherMinor!);
  const applied = cash + card + other;
  const remaining = total - applied;
  const positiveMethods = [cash, card, other].filter((amount) => amount > BigInt(0)).length;
  if (positiveMethods < 2) return invalid("Split payment needs at least two methods.", remaining);
  if (remaining !== BigInt(0)) {
    return invalid(remaining > BigInt(0) ? "Payment does not cover the total." : "Payment exceeds the total.", remaining);
  }
  if (cash > BigInt(0)) {
    if (draft.cashReceivedMinor === null) return invalid("Enter the cash received.", remaining);
    if (BigInt(draft.cashReceivedMinor) < cash) return invalid("Cash received is below the cash amount.", remaining);
  }

  const lines: PaymentLineInput[] = [];
  if (cash > BigInt(0)) lines.push({ method: "CASH", amount_minor: String(cash), cash_received_minor: draft.cashReceivedMinor! });
  if (card > BigInt(0)) lines.push({ method: "CARD", amount_minor: String(card) });
  if (other > BigInt(0)) lines.push({ method: "OTHER", amount_minor: String(other), ...(draft.otherReference.trim() ? { reference: draft.otherReference.trim() } : {}) });
  return {
    lines,
    error: "",
    remainingMinor: BigInt(0),
    changeMinor: cash > BigInt(0) ? BigInt(draft.cashReceivedMinor!) - cash : BigInt(0),
  };
}

function invalid(error: string, remainingMinor: bigint) {
  return { lines: [] as PaymentLineInput[], error, remainingMinor, changeMinor: BigInt(0) };
}
