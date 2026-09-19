# Atlas company platforms (GCP home + SAP)

**Company:** Atlas (`atlas-migration`). This is the company already on Aperture.
**Not Helios.** Helios was SAP-only chrome. Rebrand SAP console client to Atlas.
**GCP is the home platform.** SAP is an extra Atlas platform, not another company.

## Model (already started in `shared/schemas.py`)

- `ResourceType.PLATFORM = "platform"`
- `Platform` / `Company`
- `Requester.company_id` default `"atlas"`
- `Requester.platforms` default `["gcp"]` (Atlas employees have GCP unless seeded otherwise)

## Seed (`usecase-demo/seed_data.py`)

Keep `REQUESTER` / `MANAGER` / `FINANCE_OWNER` aliases (ids unchanged).

```
COMPANY = Company(
  id="atlas", name="Atlas", project="atlas-migration",
  platforms=[
    Platform(id="gcp", name="Google Cloud", short="GCP", home=True),
    Platform(id="sap", name="SAP S/4HANA", short="SAP", home=False),
  ],
)

Alex Chen     u-newhire-1        data-platform   platforms=["gcp"]
Priya Nair    u-manager-1        data-platform   platforms=["gcp","sap"]
Jordan Lee    u-finance-owner-1  finance         platforms=["gcp","sap"]
Maya Okonkwo  u-sales-1          growth          platforms=["sap"]         Sales Operations
Devon Hale    u-sre-1            data-platform   platforms=["gcp"]         Site Reliability Engineer
Chris Vogel   u-people-1         finance         platforms=["sap"]         HR Business Partner
```

`PEOPLE = [those six]`. Do **not** seed a person named Sam Rivera (`test_add_person` uses that name).

Add resources:

- `platform-gcp` — type PLATFORM, INTERNAL, team data-platform, metadata `{platform: gcp, kind: platform}`
- `platform-sap` — type PLATFORM, RESTRICTED, team finance, metadata `{platform: sap, kind: platform}`

Tag every existing resource `metadata.platform` = `gcp` or `sap`.
APPROVERS: `platform-gcp` → Priya; `platform-sap` → Jordan + Priya.

## Policy (`policy-engine/engine.py`)

`_resource_platform(resource) -> "gcp"|"sap"|None`

- `type == PLATFORM` → `None` (requesting the entitlement itself)
- else `metadata.platform` if set
- else SAP_* / `sap-*` → `sap`, otherwise `gcp`

`_has_platform(requester, platform, active_grants)` if platform in `requester.platforms` OR active grant on `platform-{id}`.

`_platform_decision` early in `_evaluate_single` (after hard-deny): if needed platform missing → AUTO_DENY reason contains `Atlas-Platform-01` and names GCP or SAP.

Existing SAP tests keep Conduct-SAP-01 / company 2000: give test helpers `platforms=["gcp","sap"]`.

## Hub (`backend-api/main.py`)

- `KNOWN_REQUESTERS` from `usecase_demo.PEOPLE`
- `GET /company` → COMPANY
- `POST /people` accepts `platforms` (default `["gcp"]`)
- `POST /people/{id}/platforms` `{platform, action: grant|revoke}`
  - grant: add platform + `_issue_grant` on `platform-{id}` (90d) if none active
  - revoke: remove platform + revoke that platform grant
- `_issue_grant` / `revoke_grant` sync `requester.platforms` for `platform-*`
- `_enqueue_execute`: skip `platform-*` (never CU)
- `GET /console/state` bindings still skip `sap-*`; also skip `platform-*`
- `GET /sap/state` still sap-* only
- conftest loads all PEOPLE

Alex (gcp-only) asking `sap-sales-order-display` → denied Atlas-Platform-01.
Priya/Jordan asking it still grants; directory still Conduct-SAP-01.
Update `test_evaluate_sales_order_auto_grants_and_directory_denies` to use Priya.

## UI (`generative-ui/src/aperture`)

- Header: APERTURE · **Atlas** · chips GCP (home) + SAP
- Person cards: platform chips; Ask (Atlas strings **byte-for-byte**); Ask SAP (`INC-8841`, Northwind 1710001)
- sap-only people: primary Ask uses SAP_ASK
- Add person: GCP default, optional SAP
- Manager can Grant/Revoke GCP or SAP via POST `/people/{id}/platforms`
- Matrix group rows by platform
- Summary GUIDE for SAP types
- `api.ts`: `platforms`, `company_id`, fetch `/company`

## SAP chrome (same Atlas company)

Replace **Helios Manufacturing** with **Atlas** in:

- `agent-runtime/mock_sap/index.html`
- `agent-runtime/tests/test_mock_sap.py`
- `agent-runtime/computer_use.py` goal strings

Keep company code 1000 London / 2000 Frankfurt. Do not make the Fiori shell look like Google Cloud.

## Tests

- Engine: gcp-only → sap deny Atlas-Platform-01; sap-only → gcp deny; gcp+sap → existing path; `platform-sap` request is not circular-deny
- Hub: GET /company; add person platforms; grant/revoke platform; Alex sap deny
- Mock SAP: Atlas not Helios; catalog counts unchanged
- Atlas ASK strings in Menu.tsx unchanged

## Do not

- Commit
- Rename Atlas ASK text
- Touch REAL_GCP / sql-prod-primary never-enact
- Invent a Helios company object
- Seed Sam Rivera
