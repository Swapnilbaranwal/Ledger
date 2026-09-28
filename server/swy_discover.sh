#!/usr/bin/env bash
# Prints endpoint + summary for candidate method ids -> swy_candidates.txt
OUT=swy_candidates.txt; : > "$OUT"
IDS="gmail.user.messages.get gmail.user.messages.get1 gmail.user.send.create gmail.user.send.create1 gmail.user.messages.create
jira.api.issue.create jira.api.search.get jira.api.search.create jira.api.search.create1 jira.api.search.list jira.api.search.list1 jira.api.search.list2
notion.query.create notion.markdown.get notion.page.create notion.page.update notion.search.create notion.databas.get
slack.chat.postmessage.create slack.conversations.history.list
disputes.customer.disputes.get disputes.customer.provideEvidence.create disputes.customer.makeOffer.create disputes.customer.acceptClaim.create transaction_search.reporting.transactions.list"
for m in $IDS; do
  echo "===== $m" >>"$OUT"
  swy info "$m" </dev/null 2>&1 | grep -E "^(Provider|Summary|Endpoint)|\"(Authorization|type)\": \"(bearer|oauth|api_key|basic)" >>"$OUT"
  swy info "$m" </dev/null 2>&1 | grep -iE "^Auth|auth.type|\"type\": \"oauth2\"" | head -3 >>"$OUT"
done
echo "Done -> swy_candidates.txt"
