"""Small FHIR R4 builders following the ABDM (NRCeS) implementation guide.

Health records sent through ABDM are FHIR "document" Bundles: the first entry
is a Composition (the record header with sections), followed by every
resource it references. Profiles: https://nrces.in/ndhm/fhir/r4/

Builders return plain dicts; references between resources use ``urn:uuid:``
full URLs inside the bundle. Specialty modules feed them their own data.
"""
import uuid
from datetime import date, datetime, timezone

PROFILE = 'https://nrces.in/ndhm/fhir/r4/StructureDefinition/'
SNOMED = 'http://snomed.info/sct'
V2_0203 = 'http://terminology.hl7.org/CodeSystem/v2-0203'
ABHA_SYSTEM = 'https://healthid.ndhm.gov.in'
DOCTOR_SYSTEM = 'https://doctor.ndhm.gov.in'
FACILITY_SYSTEM = 'https://facility.ndhm.gov.in'

# ABDM health-information types -> Composition profile, SNOMED type
HI_TYPES = {
    'OPConsultation': ('OPConsultRecord', '371530004', 'Clinical consultation report'),
    'Prescription': ('PrescriptionRecord', '440545006', 'Prescription record'),
    'DiagnosticReport': ('DiagnosticReportRecord', '721981007', 'Diagnostic studies report'),
    'HealthDocumentRecord': ('HealthDocumentRecord', '419891008', 'Record artifact'),
}

# OP consultation sections (SNOMED)
SECTION_CHIEF_COMPLAINT = ('422843007', 'Chief complaint section', 'Chief complaints')
SECTION_PHYSICAL_EXAM = ('425044008', 'Physical exam section', 'Physical examination')
SECTION_MEDICAL_HISTORY = ('371529009', 'History and physical report', 'Medical history')
SECTION_ALLERGIES = ('722446000', 'Allergy record', 'Allergies')
SECTION_MEDICATIONS = ('721912009', 'Medication summary document', 'Medications')
SECTION_PROCEDURE = ('371525003', 'Clinical procedure report', 'Procedure')
SECTION_FOLLOW_UP = ('736271009', 'Outpatient care plan', 'Follow up')
SECTION_PRESCRIPTION = ('440545006', 'Prescription record', 'Prescription')


def new_id():
    return str(uuid.uuid4())


def ref(resource):
    return {'reference': 'urn:uuid:%s' % resource['id'], 'display': resource.get('_display') or resource['resourceType']}


def fhir_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)  # Odoo stores UTC
        return value.isoformat(timespec='seconds')
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _meta(profile):
    return {'versionId': '1', 'lastUpdated': fhir_datetime(datetime.now(timezone.utc)),
            'profile': [PROFILE + profile]}


def _clean(data):
    """Drop None / empty values recursively (FHIR forbids empty elements)."""
    if isinstance(data, dict):
        cleaned = {k: _clean(v) for k, v in data.items() if not k.startswith('_')}
        return {k: v for k, v in cleaned.items() if v not in (None, '', [], {})}
    if isinstance(data, list):
        return [x for x in (_clean(v) for v in data) if x not in (None, '', [], {})]
    return data


def concept(text, code=None, system=SNOMED, display=None):
    result = {'text': text}
    if code:
        result['coding'] = [{'system': system, 'code': code, 'display': display or text}]
    return result


def narrative(text):
    from html import escape
    lines = ''.join('<p>%s</p>' % escape(line) for line in (text or '').splitlines() if line.strip())
    return {'status': 'generated', 'div': '<div xmlns="http://www.w3.org/1999/xhtml">%s</div>' % (lines or '<p>-</p>')}


# --- participants -----------------------------------------------------------
def patient(local_id, name, abha_number=None, abha_address=None, gender=None, birth_date=None,
            phone=None):
    identifiers = [{'type': concept('Medical record number', 'MR', V2_0203, 'Medical record number'),
                    'system': ABHA_SYSTEM, 'value': abha_number or local_id}]
    if abha_address:
        identifiers.append({'system': 'https://phr.ndhm.gov.in', 'value': abha_address})
    return {
        'resourceType': 'Patient', 'id': new_id(), '_display': name,
        'meta': _meta('Patient'),
        'identifier': identifiers,
        'name': [{'text': name}],
        'telecom': [{'system': 'phone', 'value': phone, 'use': 'mobile'}] if phone else None,
        'gender': gender if gender in ('male', 'female', 'other', 'unknown') else 'unknown',
        'birthDate': fhir_datetime(birth_date),
    }


def practitioner(name, registration_number=None):
    return {
        'resourceType': 'Practitioner', 'id': new_id(), '_display': name,
        'meta': _meta('Practitioner'),
        'identifier': [{'type': concept('Medical License number', 'MD', V2_0203, 'Medical License number'),
                        'system': DOCTOR_SYSTEM, 'value': registration_number}] if registration_number else None,
        'name': [{'text': name}],
    }


def organization(name, hfr_id=None, phone=None, email=None):
    telecom = [t for t in (phone and {'system': 'phone', 'value': phone, 'use': 'work'},
                           email and {'system': 'email', 'value': email, 'use': 'work'}) if t]
    return {
        'resourceType': 'Organization', 'id': new_id(), '_display': name,
        'meta': _meta('Organization'),
        'identifier': [{'type': concept('Provider number', 'PRN', V2_0203, 'Provider number'),
                        'system': FACILITY_SYSTEM, 'value': hfr_id}] if hfr_id else None,
        'name': name,
        'telecom': telecom,
    }


def encounter(patient_res, start, end=None, finished=True):
    return {
        'resourceType': 'Encounter', 'id': new_id(), '_display': 'Encounter',
        'meta': _meta('Encounter'),
        'status': 'finished' if finished else 'in-progress',
        'class': {'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode', 'code': 'AMB',
                  'display': 'ambulatory'},
        'subject': ref(patient_res),
        'period': {'start': fhir_datetime(start), 'end': fhir_datetime(end or start)},
    }


# --- clinical content -------------------------------------------------------
def condition(patient_res, text, code=None, code_system=None, active=True, recorded=None,
              body_site=None, note=None, category=None):
    return {
        'resourceType': 'Condition', 'id': new_id(), '_display': text,
        'meta': _meta('Condition'),
        'clinicalStatus': concept('Active' if active else 'Resolved', 'active' if active else 'resolved',
                                  'http://terminology.hl7.org/CodeSystem/condition-clinical'),
        'category': [concept(category)] if category else None,
        'code': concept(text, code, code_system or 'http://hl7.org/fhir/sid/icd-10') if code else {'text': text},
        'bodySite': [{'text': body_site}] if body_site else None,
        'subject': ref(patient_res),
        'recordedDate': fhir_datetime(recorded),
        'note': [{'text': note}] if note else None,
    }


def allergy(patient_res, text, recorded=None, recorder=None):
    return {
        'resourceType': 'AllergyIntolerance', 'id': new_id(), '_display': text,
        'meta': _meta('AllergyIntolerance'),
        'clinicalStatus': concept('Active', 'active',
                                  'http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical'),
        'verificationStatus': concept('Confirmed', 'confirmed',
                                      'http://terminology.hl7.org/CodeSystem/allergyintolerance-verification'),
        'code': {'text': text},
        'patient': ref(patient_res),
        'recordedDate': fhir_datetime(recorded),
        'recorder': ref(recorder) if recorder else None,
    }


def observation(patient_res, label, value, when=None, performer=None):
    return {
        'resourceType': 'Observation', 'id': new_id(), '_display': label,
        'meta': _meta('Observation'),
        'status': 'final',
        'code': {'text': label},
        'subject': ref(patient_res),
        'effectiveDateTime': fhir_datetime(when),
        'performer': [ref(performer)] if performer else None,
        'valueString': value,
    }


def procedure(patient_res, text, performed=None, body_site=None, note=None, performer=None,
              completed=True):
    return {
        'resourceType': 'Procedure', 'id': new_id(), '_display': text,
        'meta': _meta('Procedure'),
        'status': 'completed' if completed else 'in-progress',
        'code': {'text': text},
        'subject': ref(patient_res),
        'performedDateTime': fhir_datetime(performed),
        'performer': [{'actor': ref(performer)}] if performer else None,
        'bodySite': [{'text': body_site}] if body_site else None,
        'note': [{'text': note}] if note else None,
    }


def medication_request(patient_res, requester, medicine, authored, dosage_text, route=None,
                       instructions=None, reasons=None, quantity=None, duration_days=None):
    dosage = {
        'text': dosage_text,
        'additionalInstruction': [{'text': instructions}] if instructions else None,
        'route': {'text': route} if route else None,
    }
    if duration_days:
        dosage['timing'] = {'repeat': {'boundsDuration': {
            'value': duration_days, 'unit': 'd', 'system': 'http://unitsofmeasure.org', 'code': 'd'}}}
    return {
        'resourceType': 'MedicationRequest', 'id': new_id(), '_display': medicine,
        'meta': _meta('MedicationRequest'),
        'status': 'active',
        'intent': 'order',
        'medicationCodeableConcept': {'text': medicine},
        'subject': ref(patient_res),
        'authoredOn': fhir_datetime(authored),
        'requester': ref(requester),
        'reasonReference': [ref(r) for r in (reasons or [])] or None,
        'dosageInstruction': [dosage],
        'dispenseRequest': {'quantity': {'value': quantity}} if quantity else None,
    }


# --- document ---------------------------------------------------------------
def section(code_tuple, entries, text=None):
    code, display, title = code_tuple
    return {
        'title': title,
        'code': concept(display, code),
        'text': narrative(text) if text else None,
        'entry': [ref(e) for e in entries] or None,
    }


def document_bundle(hi_type, title, patient_res, author, custodian, sections, resources,
                    when=None, encounter_res=None, local_reference=None):
    """Build the Bundle for one health record of type ``hi_type``."""
    profile, type_code, type_display = HI_TYPES[hi_type]
    composition = {
        'resourceType': 'Composition', 'id': new_id(),
        'meta': _meta(profile),
        'language': 'en-IN',
        'identifier': {'system': 'https://ndhm.in/phr', 'value': local_reference or new_id()},
        'status': 'final',
        'type': concept(type_display, type_code),
        'subject': ref(patient_res),
        'encounter': ref(encounter_res) if encounter_res else None,
        'date': fhir_datetime(when or datetime.now(timezone.utc)),
        'author': [ref(author)],
        'title': title,
        'custodian': ref(custodian),
        'section': sections,
    }
    everything = [composition, patient_res, author, custodian]
    if encounter_res:
        everything.append(encounter_res)
    seen = {r['id'] for r in everything}
    everything += [r for r in resources if r['id'] not in seen]
    bundle = {
        'resourceType': 'Bundle', 'id': new_id(),
        'meta': {'versionId': '1', 'lastUpdated': fhir_datetime(datetime.now(timezone.utc)),
                 'profile': [PROFILE + 'DocumentBundle'],
                 'security': [{'system': 'http://terminology.hl7.org/CodeSystem/v3-Confidentiality',
                               'code': 'V', 'display': 'very restricted'}]},
        'identifier': {'system': 'http://hip.in', 'value': new_id()},
        'type': 'document',
        'timestamp': fhir_datetime(datetime.now(timezone.utc)),
        'entry': [{'fullUrl': 'urn:uuid:%s' % r['id'], 'resource': r} for r in everything],
    }
    return _clean(bundle)
