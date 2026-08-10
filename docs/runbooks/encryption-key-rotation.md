# Integration encryption key rotation

Never remove an active key first. Generate a new Fernet key in the secret manager, prepend it to `INTEGRATION_ENCRYPTION_KEYS`, deploy, and verify integration health. Existing ciphertext remains readable because older keys stay in the list; all new encryption uses the first key.

Run the credential rotation job or reconnect each integration so ciphertext is rewritten with the new key. Verify every connection can decrypt and complete a provider health check. Only then remove the old key and deploy again.

Keep the current and recovery keys in the disaster-recovery secret set. Never place keys, decrypted credentials, or ciphertext in tickets, logs, shell history, or Git. If validation fails, restore the previous ordered key list and redeploy; do not edit encrypted database values manually.
