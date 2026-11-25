#!/usr/bin/env sh
# Bootstrap HashiCorp Vault Transit Engine key for Whistleblower Envelope Encryption
set -eu
export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
vault secrets enable -path=transit transit || true
vault write -f transit/keys/whistleblower-transit-key type=aes256-gcm96
echo "Vault Transit key 'whistleblower-transit-key' ready."
