# Dental multi-company (branch) security standard

A clinic branch is an Odoo company (`res.company`). Every module that stores branch data must follow
these rules. `dental_core/tests/test_multi_company.py` shows how to test them.

## 1. Decide: company-owned or shared?

| Kind | Examples | Rule |
|---|---|---|
| **Company-owned** (transactions, clinical data) | appointments, cases, examinations, diagnoses, plans, sessions, follow-ups, recalls, prescriptions, dispensing, lab orders | Must have a stored, required `company_id` and a company restriction row |
| **Shared** (masters, people) | patients (`res.partner`), appointment types, diagnosis master, treatment categories, recall rules, medicine categories | No `company_id`; visible to every branch |
| **Optionally shared** | prescription templates, patient documents, catalog services (`product.template`) | Optional `company_id`: empty means shared, set means that branch only |
| **Cross-branch history (read-only)** | `dental.patient.history` | SQL view of a patient's clinical timeline from every branch, so a branch can treat a patient seen elsewhere. Read-only for dentists and managers, deliberately **without** a company restriction row. It shows names and summaries only and never grants access to the branch-owned records themselves |

Patients are always kept without `company_id` (enforced in `dental_patient`), so any branch can find them by
name, Patient ID or phone.

## 2. Company-owned models

```python
class DentalThing(models.Model):
    _name = 'dental.thing'
    _inherit = ['mail.thread', 'dental.company.mixin']   # stored, required company_id + _check_company_auto

    case_id = fields.Many2one('dental.case', check_company=True)   # every link to a company-owned record

    @api.depends('case_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('case_id')                 # follow the parent, else the current company
```

* Child lines use `company_id = fields.Many2one(related='parent_id.company_id', store=True, index=True)`.
* Use `check_company=True` on every Many2one to a company-owned model. Odoo then rejects cross-branch links on
  create and write. A branch-specific record is not linked to another branch's records, even by code running as `sudo()`.

## 3. Access rows (Odoo 20 `ir.access`)

Rows **with a group** are *permissions*, and rows for the same model are **OR-ed**. A company filter placed in a
group row does nothing if any other row for that group has no filter. Isolation must therefore use a
**group-less restriction row**, which is AND-ed with everything:

```csv
id,name,model_id,group_id/id,operation,domain
dental_thing_company_rule,Dental Thing: company isolation,dental.thing,,crud,"['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]"
```

`company_ids` contains the branches currently selected in the company switcher.

## 4. `sudo()` and client-supplied branches

* `sudo()` skips all access rows. Before using it on data the user asked for, call `record.check_access('read')`.
* Any method that receives a `branch_id`/`company_id` from the client and then reads or writes with `sudo()` must call
  `self.env['dental.company.mixin']._dental_check_company_access(company)` first. Public website booking is exempt,
  because those controllers call with `sudo()` on purpose.
* Lists built with `sudo()` (for example doctors on a dashboard) must filter on `('company_id', 'in', [False, company.id])`.

## 5. Tests

Every new company-owned model needs a test that a user of branch A:
1. cannot search or read a branch B record,
2. cannot link an A record to a B record,
3. cannot reach B data through any `sudo()` entry point (actions, dashboards, booking).
