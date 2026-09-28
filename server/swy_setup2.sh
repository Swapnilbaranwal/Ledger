#!/usr/bin/env bash
# Part 2: enable the refund method (answers the provider question) and dump contracts.
set -u
OUT=swy_info.txt; : > "$OUT"
echo "== enabling refund method (PayPal@payments_payment_v2.2.0) =="
swy add method PayPal@payments_payment_v2.2.0 payments.payment.captures.refund </dev/null 2>&1 | tee -a "$OUT"

for m in invoices.invoicing.invoices.list invoices.invoicing.remind.create \
         invoices.invoicing.invoices.get disputes.customer.disputes.list \
         payments.payment.captures.refund; do
  echo "----- $m" >>"$OUT"; swy info "$m" </dev/null >>"$OUT" 2>&1
done
echo "----- tooling" >>"$OUT"; swy list tooling </dev/null >>"$OUT" 2>&1
swy list methods </dev/null > methods.txt 2>&1
echo "Done. Tell Claude."
