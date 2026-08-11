# Payment uncertainty

If the cashier pressed Pay and the request timed out, do not create a new payment and do not invent a new `client_payment_id`.

Retry the identical request with the same `client_payment_id`, order ID, methods, amounts, cash received values, references, and line order. The backend idempotency contract returns the existing payment or safely completes the original operation. A changed payload with the same ID must return a conflict.

If the result is still uncertain, search the order/payment read APIs using the same tenant and location scope, correlate the request ID in logs, and verify the order status, payment record, SALE inventory transaction, outbox event, and any integration job. Never repair this state with direct SQL. Escalate before taking another payment from the guest.
