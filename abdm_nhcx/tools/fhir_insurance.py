"""FHIR R4 builders and parsers for NHCX insurance workflows.

Participant resources (Patient, Organization, Practitioner) come from
``abdm_base.tools.fhir`` so ABDM health records and NHCX requests describe
the patient and the facility the same way. NHCX request bundles are
``collection`` bundles holding the request resource first, then everything it
references.
"""
import uuid
from datetime import datetime, timezone

from odoo.addons.abdm_base.tools.fhir import (
    FACILITY_SYSTEM, V2_0203, _clean, concept, fhir_datetime, new_id, ref,
)

from .. import const


def _meta(profile):
    return {'versionId': '1', 'lastUpdated': fhir_datetime(datetime.now(timezone.utc)),
            'profile': [const.PROFILE + profile]}


def payer_organization(name, participant_code):
    """Insurer / TPA as identified on the exchange."""
    return {
        'resourceType': 'Organization', 'id': new_id(), '_display': name,
        'meta': _meta('Organization'),
        'identifier': [{'type': concept('Provider number', 'PRN', V2_0203, 'Provider number'),
                        'system': const.PARTICIPANT_SYSTEM, 'value': participant_code}],
        'name': name,
    }


def provider_organization(name, hfr_id, participant_code=None, phone=None, email=None):
    """The clinic: HFR facility ID, plus its exchange participant code if different."""
    identifiers = []
    if hfr_id:
        identifiers.append({'type': concept('Provider number', 'PRN', V2_0203, 'Provider number'),
                            'system': FACILITY_SYSTEM, 'value': hfr_id})
    if participant_code and participant_code != hfr_id:
        identifiers.append({'system': const.PARTICIPANT_SYSTEM, 'value': participant_code})
    telecom = [t for t in (phone and {'system': 'phone', 'value': phone, 'use': 'work'},
                           email and {'system': 'email', 'value': email, 'use': 'work'}) if t]
    return {
        'resourceType': 'Organization', 'id': new_id(), '_display': name,
        'meta': _meta('Organization'),
        'identifier': identifiers,
        'name': name,
        'telecom': telecom,
    }


def coverage(patient_res, payer_res, member_id, policy_number=None, relationship='self',
             start=None, end=None, subscriber_res=None, plan_name=None, group_number=None):
    """The patient's policy (what is on the insurance card)."""
    identifiers = [{'system': const.MEMBER_SYSTEM, 'value': member_id}]
    if policy_number:
        identifiers.insert(0, {'system': const.POLICY_SYSTEM, 'value': policy_number})
    classes = []
    if plan_name:
        classes.append({'type': concept('Plan', 'plan', 'http://terminology.hl7.org/CodeSystem/coverage-class'),
                        'value': plan_name, 'name': plan_name})
    if group_number:
        classes.append({'type': concept('Group', 'group', 'http://terminology.hl7.org/CodeSystem/coverage-class'),
                        'value': group_number})
    return {
        'resourceType': 'Coverage', 'id': new_id(), '_display': 'Coverage',
        'meta': _meta('Coverage'),
        'identifier': identifiers,
        'status': 'active',
        'subscriber': ref(subscriber_res or patient_res),
        'subscriberId': member_id,
        'beneficiary': ref(patient_res),
        'relationship': concept(relationship.capitalize(), relationship, const.RELATIONSHIP_SYSTEM),
        'period': {'start': fhir_datetime(start), 'end': fhir_datetime(end)} if (start or end) else None,
        'payor': [ref(payer_res)],
        'class': classes or None,
    }


def coverage_eligibility_request(patient_res, provider_res, payer_res, coverage_res, purposes,
                                 service_date=None, items=None, local_reference=None,
                                 practitioner_res=None):
    """CoverageEligibilityRequest. ``items``: list of service names to ask about."""
    return {
        'resourceType': 'CoverageEligibilityRequest', 'id': new_id(),
        'meta': _meta('CoverageEligibilityRequest'),
        'identifier': [{'system': const.REQUEST_SYSTEM, 'value': local_reference or new_id()}],
        'status': 'active',
        'priority': concept('Normal', 'normal', 'http://terminology.hl7.org/CodeSystem/processpriority'),
        'purpose': purposes,
        'patient': ref(patient_res),
        'servicedDate': fhir_datetime(service_date),
        'created': fhir_datetime(datetime.now(timezone.utc)),
        'enterer': ref(practitioner_res) if practitioner_res else None,
        'provider': ref(provider_res),
        'insurer': ref(payer_res),
        'insurance': [{'focal': True, 'coverage': ref(coverage_res)}],
        'item': [{'productOrService': {'text': name}} for name in (items or [])] or None,
    }


def request_bundle(profile, main_resource, resources):
    """Collection bundle: the request resource first, then what it references."""
    everything = [main_resource]
    seen = {main_resource['id']}
    for resource in resources:
        if resource and resource['id'] not in seen:
            everything.append(resource)
            seen.add(resource['id'])
    bundle = {
        'resourceType': 'Bundle', 'id': new_id(),
        'meta': _meta(profile),
        'identifier': {'system': const.REQUEST_SYSTEM, 'value': str(uuid.uuid4())},
        'type': 'collection',
        'timestamp': fhir_datetime(datetime.now(timezone.utc)),
        'entry': [{'fullUrl': 'urn:uuid:%s' % r['id'], 'resource': r} for r in everything],
    }
    return _clean(bundle)


# --- parsing ------------------------------------------------------------------
def resources_of_type(bundle, resource_type):
    if not isinstance(bundle, dict):
        return []
    if bundle.get('resourceType') == resource_type:
        return [bundle]
    return [e.get('resource') for e in bundle.get('entry') or []
            if isinstance(e, dict) and isinstance(e.get('resource'), dict)
            and e['resource'].get('resourceType') == resource_type]


def text_of(codeable):
    """Readable text of a CodeableConcept (or a plain string)."""
    if not codeable:
        return ''
    if isinstance(codeable, str):
        return codeable
    if codeable.get('text'):
        return codeable['text']
    for coding in codeable.get('coding') or []:
        if coding.get('display') or coding.get('code'):
            return coding.get('display') or coding.get('code')
    return ''


def _code_of(codeable):
    for coding in (codeable or {}).get('coding') or []:
        if coding.get('code'):
            return coding['code']
    return ''


def _value(benefit, prefix):
    """(money amount, other value as text) of allowed*/used* in a benefit."""
    money = benefit.get(prefix + 'Money')
    if isinstance(money, dict) and money.get('value') is not None:
        return float(money['value']), ''
    for suffix in ('UnsignedInt', 'String'):
        if benefit.get(prefix + suffix) not in (None, ''):
            return 0.0, str(benefit[prefix + suffix])
    return 0.0, ''


def parse_coverage_eligibility_response(bundle):
    """Extract what Odoo needs from a CoverageEligibilityResponse (bundle).

    Returns a dict: ``found``, ``outcome``, ``inforce`` (True/False/None),
    ``disposition``, ``payer_reference``, ``benefit_start``, ``benefit_end``,
    ``errors`` (list of str) and ``benefits`` (list of dicts for
    ``insurance.eligibility.benefit``).
    """
    responses = resources_of_type(bundle, 'CoverageEligibilityResponse')
    if not responses:
        return {'found': False, 'errors': ['No CoverageEligibilityResponse in the answer'],
                'benefits': [], 'inforce': None}
    resp = responses[0]
    insurances = resp.get('insurance') or []
    inforce_values = [i.get('inforce') for i in insurances if i.get('inforce') is not None]
    inforce = any(inforce_values) if inforce_values else None
    period = next((i.get('benefitPeriod') for i in insurances if i.get('benefitPeriod')), None) or {}

    benefits, sequence = [], 10
    for insurance in insurances:
        for item in insurance.get('item') or []:
            network_code = _code_of(item.get('network'))
            base = {
                'name': (item.get('name') or text_of(item.get('category'))
                         or text_of(item.get('productOrService')) or 'Benefit'),
                'category': text_of(item.get('category')),
                'service': text_of(item.get('productOrService')),
                'network': network_code if network_code in ('in', 'out') else False,
                'term': text_of(item.get('term')),
                'covered': not item.get('excluded', False),
                'requires_preauth': bool(item.get('authorizationRequired')),
                'description': item.get('description') or False,
            }
            for benefit in item.get('benefit') or [{}]:
                allowed, allowed_text = _value(benefit, 'allowed')
                used, used_text = _value(benefit, 'used')
                line = dict(base, sequence=sequence,
                            benefit_type=text_of(benefit.get('type')),
                            allowed_amount=allowed, used_amount=used,
                            allowed_value=allowed_text, used_value=used_text)
                benefits.append(line)
                sequence += 10

    errors = [text_of(e.get('code')) or str(e) for e in resp.get('error') or []]
    identifiers = resp.get('identifier') or []
    return {
        'found': True,
        'outcome': resp.get('outcome'),
        'inforce': inforce,
        'disposition': resp.get('disposition') or '',
        'payer_reference': identifiers[0].get('value') if identifiers else '',
        'benefit_start': (period.get('start') or '')[:10] or False,
        'benefit_end': (period.get('end') or '')[:10] or False,
        'errors': errors,
        'benefits': benefits,
    }
