import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { localReservationDate, reservationMinute, reservationTime } from "./reservations.ts";

const api = () => readFile(new URL("./api.ts", import.meta.url), "utf8");
const guest = () => readFile(new URL("../app/reserve/[slug]/public-reservation-client.tsx", import.meta.url), "utf8");
const status = () => readFile(new URL("../app/reservation/status/[guestAccessToken]/public-reservation-status.tsx", import.meta.url), "utf8");
const foh = () => readFile(new URL("../app/app/pos/front-of-house/page.tsx", import.meta.url), "utf8");

test("guest form gets authoritative availability for native date and party inputs", async () => {
  const source = await guest();
  assert.match(source, /type="date"/);
  assert.match(source, /Party size/);
  assert.match(source, /getPublicReservationAvailability\(slug, date, partySize\)/);
  assert.match(source, /Checking availability/);
  assert.match(source, /No availability for this date and party size/);
});

test("guest confirmation is server-backed and keeps the opaque status token out of storage", async () => {
  const [source, contract] = await Promise.all([guest(), api()]);
  assert.match(source, /createPublicReservation\(slug/);
  assert.match(source, /reservation\.guest_access_token/);
  assert.match(source, /Confirm reservation/);
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
  assert.match(contract, /PublicReservationCreated = PublicReservation & \{ guest_access_token: string \}/);
  assert.match(source, /location\.organization_name/);
  assert.match(source, /location\.location_name/);
});

test("booking 409 refreshes availability and never renders optimistic success", async () => {
  const source = await guest();
  assert.match(source, /caught\.status === 409 && caught\.code === "SLOT_UNAVAILABLE"/);
  assert.match(source, /await refreshAvailability\(\)/);
  assert.match(source, /Availability has been refreshed/);
  assert.doesNotMatch(source, /setReservation\(|Reservation confirmed/);
});

test("guest status trusts server cancellation permission and explains forbidden cancellation", async () => {
  const source = await status();
  assert.match(source, /reservation\.can_cancel &&/);
  assert.match(source, /cancelPublicReservation\(guestAccessToken\)/);
  assert.match(source, /can no longer be cancelled online/);
  assert.match(source, /window\.setTimeout\(poll, 5000\)/);
  assert.match(source, /reservation\.organization_name/);
  assert.match(source, /reservation\.location_name/);
  assert.doesNotMatch(source, /internal_notes|dining_table_id|reservation\.id/);
});

test("front of house exposes exactly the requested live views and table states", async () => {
  const [source, contract] = await Promise.all([foh(), api()]);
  for (const view of ["TABLES", "RESERVATIONS", "WAITLIST"]) assert.match(source, new RegExp(`"${view}"`));
  for (const state of ["AVAILABLE", "RESERVED", "OCCUPIED"]) assert.match(contract, new RegExp(`"${state}"`));
  assert.match(source, /getDiningFloor/);
  assert.match(source, /elapsedVisit\(table\.visit\.opened_at, clockNow\)/);
  assert.match(source, /sales_order_status/);
});

test("reservation list has Today Upcoming Status filters and lifecycle actions", async () => {
  const source = await foh();
  for (const label of ["Today", "Upcoming", "Status", "Seat", "Cancel", "No-show"]) assert.match(source, new RegExp(label));
  assert.match(source, /seatReservation/);
  assert.match(source, /noShowReservation/);
});

test("waitlist and walk-in seating use server actions and recover occupied conflicts", async () => {
  const source = await foh();
  assert.match(source, /createWaitlistEntry/);
  assert.match(source, /seatWaitlistEntry/);
  assert.match(source, /seatWalkIn/);
  assert.match(source, /caught instanceof ApiError && caught\.status === 409/);
  assert.match(source, /Live state has been refreshed/);
});

test("staff mutation retries keep scope-keyed ids until the server confirms success", async () => {
  const source = await foh();
  assert.match(source, /retryIds = useRef\(new Map<string, string>\(\)\)/);
  assert.match(source, /const result = await operation\(id\);[\s\S]*retryIds\.current\.delete\(key\)/);
  assert.match(source, /retryIds\.current\.clear\(\)/);
  for (const key of ["reservation:seat", "reservation:cancel", "reservation:no-show", "waitlist:create", "waitlist:seat", "waitlist:cancel", "walk-in:seat", "visit:open-check", "visit:close"]) assert.match(source, new RegExp(key));
  assert.equal(source.match(/crypto\.randomUUID\(\)/g)?.length, 1);
});

test("money remains outside the front-of-house reservation flow", async () => {
  const source = await foh();
  assert.doesNotMatch(source, /subtotal_minor|total_minor|discount_minor|Payment|Inventory/);
  assert.match(source, /openDiningVisitCheck/);
  assert.match(source, /\/app\/pos\?order_id=/);
});

test("front-of-house actions are permission gated", async () => {
  const [page, hook] = await Promise.all([foh(), readFile(new URL("../hooks/use-front-of-house-permissions.ts", import.meta.url), "utf8")]);
  assert.match(hook, /foh\.read/);
  assert.match(hook, /foh\.manage/);
  assert.match(hook, /foh\.configure/);
  assert.match(page, /permissions\.canManage/);
  assert.match(page, /permissions\.canConfigure/);
});

test("admin setup covers section and table configuration without a floor-plan editor", async () => {
  const source = await foh();
  assert.match(source, /createDiningSection/);
  assert.match(source, /updateDiningSection/);
  assert.match(source, /createDiningTable/);
  assert.match(source, /updateDiningTable/);
  for (const field of ["name", "section_id", "capacity", "sort_order", "is_active"]) assert.match(source, new RegExp(field));
  assert.match(source, /saveReservationSettings/);
  assert.doesNotMatch(source, /drag|drop|canvas/i);
});

test("reservation times are minute-level in the requested location timezone", () => {
  const value = "2026-08-15T18:05:45Z";
  assert.equal(localReservationDate(value, "Asia/Almaty"), "2026-08-15");
  assert.match(reservationTime(value, "Asia/Almaty"), /23:05/);
  assert.match(reservationMinute(value, "Asia/Almaty"), /23:05/);
  assert.doesNotMatch(reservationMinute(value, "Asia/Almaty"), /45/);
});
