#!/usr/bin/env bash
# Demonstrate the admission webhook by trying to mutate an agent-owned object
# from outside. Run this AFTER `make deploy && make demo` so a ScopedAgent
# and its NetworkPolicy exist.
#
# Expected result: every kubectl command in this script is REJECTED by the
# admission webhook with an explanation referencing the agent's limits.

set -u

NAMESPACE="agent-warden-demo"
TARGET_NP="log-triage-warden"  # NetworkPolicy created by the log-triage ScopedAgent

cat <<MSG
=== agent-warden webhook demo ===

This script attempts to mutate the NetworkPolicy that the operator created
for the 'log-triage' ScopedAgent. Because that NetworkPolicy carries the
'agent-warden.io/scoped-agent' label, the admission webhook intercepts
every operation on it.

Without agent-warden, an operator with kubectl access could delete the
NetworkPolicy and free the agent from its egress restrictions.
With agent-warden, the action is denied and recorded as a BlockedAction.

MSG

if ! kubectl get networkpolicy -n "$NAMESPACE" "$TARGET_NP" >/dev/null 2>&1; then
  echo "error: NetworkPolicy $NAMESPACE/$TARGET_NP not found."
  echo "Run 'make demo' first to create the example ScopedAgents."
  exit 1
fi

echo ">>> Attempt 1: kubectl delete networkpolicy $TARGET_NP"
echo
kubectl delete networkpolicy -n "$NAMESPACE" "$TARGET_NP" 2>&1 || true
echo

echo ">>> Attempt 2: kubectl patch networkpolicy $TARGET_NP (remove egress rules)"
echo
kubectl patch networkpolicy -n "$NAMESPACE" "$TARGET_NP" \
  --type='json' -p='[{"op":"replace","path":"/spec/egress","value":[]}]' 2>&1 || true
echo

echo
echo "=== BlockedAction custom resources created by the webhook ==="
kubectl get blockedactions -n "$NAMESPACE" --sort-by=.spec.blockedAt -o wide
echo
echo "Done. Both attempts should have been denied above."
