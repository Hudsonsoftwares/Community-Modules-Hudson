# -*- encoding: utf-8 -*-
from odoo import api, models


class EhHrConsent(models.Model):
    _inherit = 'eh.hr.consent'

    def action_withdraw(self):
        """Cascade: when a face consent is withdrawn, every active face
        template tied to it is deactivated in the same transaction.

        The cascade is logged to the kiosk audit trail so a future
        compliance review can prove the deactivation happened, and when.
        """
        result = super().action_withdraw()
        Template = self.env['eh.hr.face.template'].sudo()
        Event = self.env['eh.hr.kiosk.event'].sudo()
        for record in self:
            if record.consent_type != 'face':
                continue
            templates = Template.search([
                ('consent_id', '=', record.id),
                ('active', '=', True),
            ])
            if templates:
                templates.write({'active': False})
                Event.log(
                    'consent_withdraw',
                    employee_id=record.employee_id.id,
                    notes='Cascade: deactivated %d face template(s) on consent withdrawal' % len(templates),
                    ref_model='eh.hr.consent',
                    ref_id=record.id,
                    company_id=record.company_id.id,
                )
        return result

    @api.model
    def _cron_retention_sweep(self, *, batch_limit=500, **kwargs):
        """Deactivate the active face templates of expired face consents.

        The keywords of the base sweep, batch_limit first, are passed through
        so a caller can bound the run whether or not this module is installed.
        The deactivation pass is bounded by the same batch_limit: templates
        left active past it are picked up by the next run.
        """
        result = super()._cron_retention_sweep(batch_limit=batch_limit, **kwargs)
        templates = self.env['eh.hr.face.template'].sudo().search([
            ('active', '=', True),
            ('consent_id.consent_type', '=', 'face'),
            ('consent_id.state', '=', 'expired'),
        ], limit=batch_limit)
        if templates:
            templates.write({'active': False})
        return result

    def _retention_purge(self):
        """The face templates of a consent past its retention window go with
        it. They are biometric data the consent no longer covers, and the
        template's link to its consent is ondelete='restrict', so the purge
        would otherwise fail on the first such consent and roll back the
        whole run, every day."""
        self.env['eh.hr.face.template'].sudo().with_context(active_test=False).search([
            ('consent_id', 'in', self.ids),
        ]).unlink()
        return super()._retention_purge()
