# Dental Documents – DMS integration

Connects the dental hospital modules to the existing Document Management System
(`dms`, `dms_enterprise_features`). The Document modules are **not modified**. Everything here is
an extension module that uses their models and APIs.

## Modules

| Module | Depends on | Installs | Purpose |
|---|---|---|---|
| `dental_dms` | dms, dms_enterprise_features, dental_core, account, hr, purchase | manually | Core bridge: routing, dental links on `dms.file`, smart buttons, Add Document wizard, Dental Documents search, security |
| `dental_dms_education` | dental_dms | manually | Patient Treatment Education & Video Library |
| `dental_dms_lab` | dental_dms, dental_lab | automatically | Lab orders, dispatches and receipts |
| `dental_dms_pharmacy` | dental_dms, dental_pharmacy | automatically | Prescriptions and dispensing |
| `dental_dms_second_opinion` | dental_dms, dental_second_opinion | automatically | Second-opinion requests and specialist reports |

## How documents are filed (no duplication)

* Any attachment created on a dental record (chatter, Add Document wizard, reports, imports) is filed by
  `dental.dms.service` as a `dms.file` with `attachment_id` set to that attachment. The DMS serves the
  original attachment, so no second storage and no copy of the content is created.
* If a DMS folder rule already filed the attachment (for example Accounting, Purchases or Employees),
  the existing `dms.file` only receives the dental links. It is not filed a second time.
* If the same content is already filed for the same patient (`dental_core` pushes a copy of each
  `dental.patient.document` onto the patient), it is not filed again.
* Folder tree, per branch (company):
  `Dental Hospital / <category> / <patient | employee | record>`.
  The categories are Patient Records, Clinical Reports & Consultations, X-Rays & Imaging, Odontogram,
  Treatment Plans, Prescriptions, Signed Consent Forms, Laboratory Reports, Second Opinions,
  Invoices & Billing, Staff Documents, Purchase Documents, Hospital Administration and the Patient
  Education Library.
* Each `dms.file` carries stored, indexed links: patient, case, consultation, treatment plan,
  appointment, employee, tooth, document date, source record and document type.
* Routing errors are logged and never block the business workflow (savepoint).

| Source | Category |
|---|---|
| Patient (`res.partner`, patients only) / appointment | Patient Records |
| Dental case / consultation / diagnosis | Clinical, or X-Rays & Imaging for images, DICOM and X-ray file names |
| Tooth finding, "Save Odontogram to Documents" | Odontogram |
| Treatment plan / session | Treatment, or Consent when "consent" is in the file name |
| `dental.patient.document` | By its document type (X-ray, prescription, lab report and so on) |
| Customer invoice of a patient | Invoices & Billing |
| Employee / purchase order | Staff / Purchase |

## Security

* **Roles:** DMS access groups are bound to the dental roles: *Clinical Team*, *Front Desk*, *Billing*,
  *HR & Administration*, *Clinic Management* (+ *Laboratory*, *Pharmacy*, *Specialists* in the glue
  modules). Permission lines on each category folder are inherited by the sub-folders, as DMS does
  natively. The matrix is in `models/const.py`. Lines are only ever added, never removed, so manual
  changes made by DMS managers are kept.
* **Branches:** folders and files belong to the branch company, and the existing DMS multi-company
  rules apply.
* **Patient privacy:** a file linked to a case, consultation, treatment plan, appointment or employee
  is visible only to users who can read that record (`ir.access` rows using Odoo 20's `access`
  operator). These rows are mirrored in `dms.file.check_access/read` because the DMS security mixin
  makes per-record checks pass under sudo. This covers downloads, RPC reads and write/unlink.
* Lab and pharmacy documents are linked to the patient and to their order or prescription, not to the
  case, so laboratory and pharmacy staff, who cannot read cases, still see them.

## Deployment

1. Install `dental_dms`, then `dental_dms_education`. The glue modules install automatically.
   The install hook creates the folders for every branch and files the existing attachments.
2. Settings → Users: dental roles already give the right document access. To add people to a team
   without changing their dental role, use the explicit users of the DMS access groups
   ("Dental - …").
3. Run the upgrade from the Odoo UI, or restart the Windows service after a CLI upgrade (asset
   bundles: see the project notes).

## Pre-existing issues found during the audit (not changed here)

* `dms_enterprise_features`: while the "Route Employee Documents" folder rule is active, creating an
  employee fails with *"A directory with the same name already exists"*. The rule (via the avatar
  attachment) and `hr.employee._setup_dms_folder_and_permissions` both create `Employees/<name>`.
  This reproduces on DentalDB without these modules, and it also breaks the existing `dental_core`,
  `dental_pharmacy` and `dental_speech` test suites there.
* `dms`: `dms.security.mixin.filtered_domain()` returns every record under sudo. Odoo 20 therefore
  never applies record rules on direct (by id) reads of `dms.file`, so any internal user can read any
  DMS file by id. `dental_dms` closes this for dental documents only.
* `dental_consent` has no `__manifest__.py`, so it cannot be installed. Signed consents are handled as
  the *Signed Consent Forms* category, with a consent indicator and an "Add Signed Consent" button on
  treatment plans.
