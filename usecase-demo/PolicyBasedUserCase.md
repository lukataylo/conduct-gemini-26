# Policy-Based User Case

See [PolicyBasedUserCaseDemo.md](PolicyBasedUserCaseDemo.md) for the canonical final
presentation user case.

## Last User Case: The Friday Finance Freeze

Alex is fixing a finance dashboard before earnings week. Project Atlas demonstrates:

- low-risk internal read access auto-grants,
- PowerBI `VIEW` grants while `EXPORT` escalates,
- finance production write access during quiet period becomes read-only and escalates to
  the CFO,
- warehouse IoT access from outside the geofence is denied,
- support impersonation is denied when Zendesk requester does not match the target
  customer,
- vault secret harvesting is denied with anomaly alarm,
- escalation cards show risk score, policy violation, peer signal, suggested downgrade,
  approvers, and SLA,
- the Reaper loop revokes the finance grant when Jira `ATLAS-101` is marked `DONE`.

Final toast:

```text
Access reclaimed: Jira ATLAS-101 is complete.
```
