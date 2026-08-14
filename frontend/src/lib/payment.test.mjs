import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { paymentRequest } from "./payment.ts";

test("online payment opens without an empty order update", () => {
  const source = readFileSync(new URL("../app/app/pos/page.tsx", import.meta.url), "utf8");
  const openPayment = source.match(/async function openPayment\(\) \{([\s\S]*?)\r?\n  \}\r?\n\r?\n  function closePayment/)?.[1];

  assert.ok(openPayment);
  assert.doesNotMatch(openPayment, /updateSalesOrder\s*\(/);
  assert.match(openPayment, /setPaymentOrder\(priced\)/);
});

test("builds an exact split and computes cash change", () => {
  const result = paymentRequest({
    mode: "SPLIT",
    totalMinor: "670000",
    cashMinor: "200000",
    cashReceivedMinor: "250000",
    cardMinor: "470000",
    otherMinor: "0",
    otherReference: "",
  });

  assert.equal(result.error, "");
  assert.equal(result.changeMinor, 50000n);
  assert.deepEqual(result.lines.map(({ method, amount_minor }) => [method, amount_minor]), [
    ["CASH", "200000"],
    ["CARD", "470000"],
  ]);
});

test("rejects an incomplete split and closes a zero-total order without lines", () => {
  const incomplete = paymentRequest({
    mode: "SPLIT",
    totalMinor: "670000",
    cashMinor: "200000",
    cashReceivedMinor: "200000",
    cardMinor: "400000",
    otherMinor: "0",
    otherReference: "",
  });
  assert.equal(incomplete.error, "Payment does not cover the total.");

  const free = paymentRequest({
    mode: null,
    totalMinor: "0",
    cashMinor: "0",
    cashReceivedMinor: null,
    cardMinor: "0",
    otherMinor: "0",
    otherReference: "",
  });
  assert.deepEqual(free.lines, []);
  assert.equal(free.error, "");
});
