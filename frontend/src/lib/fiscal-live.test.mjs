import assert from "node:assert/strict";
import test from "node:test";

import { fiscalReceiptAction, paymentAttemptAction, safeReceiptUrl } from "./fiscal-live.ts";

test("unknown provider outcomes can only be reconciled", () => {
  assert.equal(paymentAttemptAction("UNKNOWN"), "RECONCILE");
  assert.equal(fiscalReceiptAction("UNKNOWN"), "RECONCILE");
});

test("only definitive failures expose a new safe attempt", () => {
  assert.equal(paymentAttemptAction("DECLINED"), "RETRY");
  assert.equal(paymentAttemptAction("CANCELLED"), "RETRY");
  assert.equal(paymentAttemptAction("TERMINAL_PENDING"), "RECONCILE");
  assert.equal(paymentAttemptAction("APPROVED"), "NONE");
  assert.equal(fiscalReceiptAction("DEAD"), "RETRY");
});

test("receipt links allow web URLs only", () => {
  assert.equal(safeReceiptUrl("https://receipt.example/1"), "https://receipt.example/1");
  assert.equal(safeReceiptUrl("javascript:alert(1)"), null);
  assert.equal(safeReceiptUrl(null), null);
});
