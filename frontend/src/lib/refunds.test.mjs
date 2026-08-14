import assert from "node:assert/strict";
import test from "node:test";

import { allocateRefundPayment, refundAttempt, refundDraftTotal, refundedItemQuantity } from "./refunds.ts";

const refund = {
  status: "COMPLETED",
  lines: [{ order_item_id: "item-1", quantity: 1 }],
  payment_lines: [{ original_payment_line_id: "card", amount_minor: "4000" }],
};

test("keeps cumulative item and split-payment availability exact", () => {
  assert.equal(refundedItemQuantity([refund], "item-1"), 1);
  assert.equal(refundDraftTotal({ items: [{ id: "item-1", quantity: 2, line_total_minor: "3600", net_line_total_minor: "3600" }] }, { "item-1": 2 }), 3600n);

  const allocation = allocateRefundPayment(1800n, {
    lines: [
      { id: "card", amount_minor: "4700" },
      { id: "cash", amount_minor: "2000" },
    ],
  }, [refund]);
  assert.deepEqual(allocation.map(({ available, amount }) => [available, amount]), [[700n, 700n], [2000n, 1100n]]);
});

test("uses discounted net and preserves cumulative rounding for partial refunds", () => {
  assert.equal(refundDraftTotal({ items: [{ id: "item-1", quantity: 1, line_total_minor: "90000", net_line_total_minor: "81000" }] }, { "item-1": 1 }), 81000n);
  const rounded = { items: [{ id: "item-1", quantity: 3, line_total_minor: "300", net_line_total_minor: "100" }] };
  assert.equal(refundDraftTotal(rounded, { "item-1": 1 }), 33n);
  assert.equal(refundDraftTotal(rounded, { "item-1": 2 }, [refund]), 67n);
});

test("retries identical refund payloads with the same id only", () => {
  let sequence = 0;
  const createId = () => `refund-${++sequence}`;
  const first = refundAttempt(null, "payload-a", createId);
  assert.equal(refundAttempt(first, "payload-a", createId).id, first.id);
  assert.notEqual(refundAttempt(first, "payload-b", createId).id, first.id);
});
