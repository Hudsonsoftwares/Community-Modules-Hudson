from odoo import models, fields, api, _
from odoo.exceptions import AccessError


class DentalCompanyMixin(models.AbstractModel):
    """Standard for company (branch) owned dental records. See dental_base/SECURITY.md.

    - ``company_id`` is stored, required and indexed so record rules and ``check_company`` work.
    - It follows the record's parent (override ``_compute_company_id`` with the parent's dependencies);
      without a parent it falls back to the current company.
    - ``_check_company_auto`` makes Odoo reject links to records of another company on create/write
      for every Many2one declared with ``check_company=True``.
    - Pair the model with a group-less ``ir.access`` restriction row (see SECURITY.md); group rows
      are OR-ed together and therefore cannot restrict anything on their own.
    """
    _name = 'dental.company.mixin'
    _description = 'Dental Company-Owned Record'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Branch', required=True, index=True,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        default=lambda self: self.env.company,
    )

    def _compute_company_id(self):
        # Models override this with @api.depends on their parent and call _set_company_from()
        for record in self:
            record.company_id = record.company_id or self.env.company

    def _set_company_from(self, *sources):
        """Set company_id from the first parent record that has one; keep the current value otherwise."""
        for record in self:
            company = False
            for source in sources:
                parent = source(record) if callable(source) else record[source]
                if parent:
                    company = parent.company_id if 'company_id' in parent._fields else parent
                    if company:
                        break
            record.company_id = company or record.company_id or self.env.company

    @api.model
    def _dental_check_company_access(self, company):
        """Guard for entry points that receive a company/branch from the client and then use sudo().

        Internal users may only act on companies they are allowed in; public website visitors may use
        any branch (public booking), the website controllers being responsible for that channel.
        """
        if not company or self.env.su or self.env.user._is_public():
            return company
        if company not in self.env.user.company_ids:
            raise AccessError(_("You are not allowed to access data of branch %s.", company.display_name))
        return company
