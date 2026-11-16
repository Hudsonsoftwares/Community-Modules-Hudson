import logging

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.abdm_base.tools import fhir

from .. import const
from ..tools import fhir_insurance

_logger = logging.getLogger(__name__)

PURPOSES = {
    'validation': ['validation'],
    'benefits': ['validation', 'benefits'],
    'discovery': ['discovery'],
}


class InsuranceEligibility(models.Model):
    _inherit = 'insurance.eligibility'

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------
    def _nhcx_build_bundle(self):
        """CoverageEligibilityRequest bundle for this check."""
        self.ensure_one()
        policy = self.policy_id
        company = self.company_id or self.env.company
        patient = self.partner_id._nhcx_fhir_patient()
        subscriber = None
        if policy.holder_id and policy.holder_id != policy.partner_id:
            subscriber = policy.holder_id._nhcx_fhir_patient()
        payer = fhir_insurance.payer_organization(self.payer_id.name, self.payer_id.nhcx_participant_code)
        provider = fhir_insurance.provider_organization(
            company.abdm_hip_name or company.name, company.abdm_hip_id,
            company.nhcx_participant_code, phone=company.phone, email=company.email)
        coverage = fhir_insurance.coverage(
            patient, payer, policy.member_id, policy.policy_number, policy.relationship,
            policy.date_start, policy.date_end, subscriber_res=subscriber,
            plan_name=policy.plan_id.name, group_number=policy.group_number)
        request = fhir_insurance.coverage_eligibility_request(
            patient, provider, payer, coverage, PURPOSES.get(self.purpose, ['validation']),
            service_date=self.service_date, items=self.product_tmpl_ids.mapped('name'),
            local_reference=self.name)
        return fhir_insurance.request_bundle(
            'CoverageEligibilityRequestBundle', request, [patient, subscriber, provider, payer, coverage])

    def _send_nhcx(self):
        for check in self:
            if not check.payer_id.nhcx_participant_code:
                check._set_error(self.env._(
                    "%s has no NHCX participant code: sync the payers from NHCX "
                    "(Settings > ABDM > NHCX) or enter it on the insurance company.",
                    check.payer_id.display_name))
                continue
            try:
                tx = self.env['nhcx.client'].send_request(
                    const.PATH_COVERAGE_ELIGIBILITY_CHECK, check._nhcx_build_bundle(),
                    payer=check.payer_id, company=check.company_id or self.env.company,
                    record=check, operation='nhcx.coverageeligibility.check')
            except UserError as exc:
                # Keep the check (state Error + message) instead of losing it in a rollback.
                check._set_error(exc.args[0] if exc.args else exc)
                continue
            check.write({'state': 'waiting', 'external_ref': tx.request_id})
            check.message_post(body=self.env._("Eligibility request sent to %s through NHCX.",
                                               check.payer_id.display_name))

    # ------------------------------------------------------------------
    # Answer (called by nhcx.client.handle_callback)
    # ------------------------------------------------------------------
    def _nhcx_on_response(self, action, headers, payload, error):
        self.ensure_one()
        if self.state not in ('waiting', 'error'):
            _logger.info("NHCX answer for %s ignored: check is %s", self.name, self.state)
            return
        self.sudo().response_data = payload if isinstance(payload, (dict, list)) else None
        if error:
            self._set_error(self.env._("Payer answered with an error: %s", error))
            return
        parsed = fhir_insurance.parse_coverage_eligibility_response(payload)
        if not parsed['found'] or (parsed['inforce'] is None and
                                   (parsed['errors'] or parsed.get('outcome') == 'error')):
            self._set_error('; '.join(parsed['errors']) or self.env._("The payer's answer has no result."))
            return
        if headers.get(const.H_STATUS) == const.STATUS_PARTIAL and parsed['inforce'] is None:
            self.message_post(body=self.env._("Partial answer received; waiting for the rest."))
            return
        disposition = parsed['disposition']
        if parsed['errors']:
            disposition = '\n'.join(filter(None, [disposition] + parsed['errors']))
        self._apply_result(
            'eligible' if parsed['inforce'] else 'not_eligible',
            benefits=parsed['benefits'],
            disposition=disposition or False,
            payer_reference=parsed['payer_reference'] or False,
            benefit_start=parsed['benefit_start'] or False,
            benefit_end=parsed['benefit_end'] or False,
        )

    def _nhcx_expire(self, minutes):
        """Mark checks whose request the payer never answered."""
        Tx = self.env['abdm.transaction'].sudo()
        waiting = self.sudo().search([('state', '=', 'waiting'), ('connector', '=', 'nhcx'),
                                      ('external_ref', '!=', False)])
        timed_out = Tx.search([('request_id', 'in', waiting.mapped('external_ref')),
                               ('state', '=', 'timeout')])
        expired_refs = set(timed_out.mapped('request_id'))
        for check in waiting.filtered(lambda c: c.external_ref in expired_refs):
            check._set_error(self.env._(
                "No answer from the payer within %s minutes. Check again later.", minutes))


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _nhcx_fhir_patient(self):
        """FHIR Patient for NHCX; uses ABHA and, when the specialty module has
        them, gender and date of birth."""
        self.ensure_one()
        gender = self['gender'] if 'gender' in self._fields else None
        birth_date = None
        for name in ('date_of_birth', 'birthdate', 'birthday'):
            if name in self._fields and self[name]:
                birth_date = self[name]
                break
        local_id = None
        for name in ('dental_patient_id', 'ref'):
            if name in self._fields and self[name] and self[name] != 'New':
                local_id = self[name]
                break
        return fhir.patient(
            local_id=local_id or str(self.id),
            name=self.name,
            abha_number=self.abha_number or None,
            abha_address=self.abha_address or None,
            gender=gender if gender in ('male', 'female', 'other') else None,
            birth_date=birth_date,
            phone=self.phone or None,
        )
