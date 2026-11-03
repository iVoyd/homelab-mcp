#!/usr/bin/env bash
# Write a kubeconfig for one of the ServiceAccounts in deploy/rbac.yaml.
# Usage: scripts/make-kubeconfig.sh SERVICE_ACCOUNT NAMESPACE OUTPUT_FILE
# Uses your admin access; set KUBECTL="sudo k3s kubectl" if that is how you reach it.
# The output file contains a token: it is created with mode 600. Do not commit it.
set -euo pipefail
if [ $# -ne 3 ]; then
  echo "usage: $0 SERVICE_ACCOUNT NAMESPACE OUTPUT_FILE" >&2
  exit 2
fi
sa=$1 ns=$2 out=$3
read -r -a kubectl <<< "${KUBECTL:-kubectl}"

secret="${sa}-token"
token=$("${kubectl[@]}" -n "$ns" get secret "$secret" -o jsonpath='{.data.token}' | base64 -d)
ca=$("${kubectl[@]}" -n "$ns" get secret "$secret" -o jsonpath='{.data.ca\.crt}')
server=$("${kubectl[@]}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')
if [ -z "$token" ] || [ -z "$ca" ] || [ -z "$server" ]; then
  echo "could not read token/CA/server for $ns/$sa (did you apply deploy/rbac.yaml?)" >&2
  exit 1
fi

umask 077
mkdir -p "$(dirname "$out")"
cat > "$out" <<KUBECONFIG
apiVersion: v1
kind: Config
clusters:
  - name: homelab
    cluster:
      server: $server
      certificate-authority-data: $ca
users:
  - name: $sa
    user:
      token: $token
contexts:
  - name: $sa
    context: {cluster: homelab, user: $sa, namespace: $ns}
current-context: $sa
KUBECONFIG
echo "wrote $out"
