path "collabio-storage/datakey/plaintext/collabio-rgw-sse-kms" {
  capabilities = ["update"]
}

path "collabio-storage/decrypt/collabio-rgw-sse-kms" {
  capabilities = ["update"]
}

path "collabio-storage/keys/collabio-rgw-sse-kms" {
  capabilities = ["read"]
}
