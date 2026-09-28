#!/usr/bin/env bash
# Run from the server/ folder:  bash swy_setup.sh
# Fetches the remaining providers, enables the PayPal methods Ledger uses,
# and dumps method contracts to swy_info.txt so the code can match them exactly.
set -u
OUT=swy_info.txt; : > "$OUT"

echo "== fetching providers ==" | tee -a "$OUT"
for p in notion gmail jira slack; do
  if ! swy get "$p" --yes >>"$OUT" 2>&1; then
    echo "!! 'swy get $p' failed, search results:" | tee -a "$OUT"
    swy search "$p" >>"$OUT" 2>&1
  fi
done

echo "== enabling PayPal methods ==" | tee -a "$OUT"
for m in invoices.invoicing.invoices.list invoices.invoicing.remind.create \
         invoices.invoicing.invoices.get disputes.customer.disputes.list \
         payments.payment.captures.refund; do
  swy add method "$m" >>"$OUT" 2>&1 || echo "!! add failed: $m" | tee -a "$OUT"
done

echo "== contracts ==" >>"$OUT"
for m in invoices.invoicing.invoices.list invoices.invoicing.remind.create \
         invoices.invoicing.invoices.get disputes.customer.disputes.list \
         payments.payment.captures.refund; do
  echo "----- $m" >>"$OUT"; swy info "$m" >>"$OUT" 2>&1
done

swy list methods > methods.txt 2>&1
swy list tooling >> "$OUT" 2>&1
echo "Done. Tell Claude to read swy_info.txt and methods.txt"
