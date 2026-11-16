# -*- coding: utf-8 -*-
"""Shared constants of the dental <-> DMS integration."""

# Document categories. Each one is a sub-folder of the per-branch "Dental Hospital" root folder.
# Extension modules add their own values with ``selection_add`` (e.g. 'education').
DOC_TYPES = [
    ('patient', 'Patient Records'),
    ('clinical', 'Clinical Reports & Consultations'),
    ('imaging', 'X-Rays & Imaging'),
    ('odontogram', 'Odontogram & Dental Charts'),
    ('treatment', 'Treatment Plans & Sessions'),
    ('prescription', 'Prescriptions & Pharmacy'),
    ('consent', 'Signed Consent Forms'),
    ('lab', 'Laboratory Reports'),
    ('second_opinion', 'Second Opinions'),
    ('billing', 'Invoices & Billing'),
    ('staff', 'Staff Documents'),
    ('purchase', 'Purchase Documents'),
    ('admin', 'Hospital Administration'),
]

ROOT_FOLDER_NAME = 'Dental Hospital'

# Permission letters: v = view + download, u = upload, e = edit / rename / move, d = delete, s = share
# Keys are xml ids (without module) of the dms.access.group records in security/dental_dms_access_groups.xml.
# Extension modules extend this through dental.dms.service._get_folder_permissions().
FULL = 'vueds'
FOLDER_PERMISSIONS = {
    'patient': {'dms_group_clinical': 'vu', 'dms_group_frontdesk': 'vue', 'dms_group_management': FULL},
    'clinical': {'dms_group_clinical': 'vue', 'dms_group_management': FULL},
    'imaging': {'dms_group_clinical': 'vue', 'dms_group_frontdesk': 'vu', 'dms_group_management': FULL},
    'odontogram': {'dms_group_clinical': 'vue', 'dms_group_management': FULL},
    'treatment': {'dms_group_clinical': 'vue', 'dms_group_frontdesk': 'v', 'dms_group_management': FULL},
    'prescription': {'dms_group_clinical': 'vue', 'dms_group_management': FULL},
    'consent': {'dms_group_clinical': 'vu', 'dms_group_frontdesk': 'vu', 'dms_group_management': FULL},
    'lab': {'dms_group_clinical': 'vu', 'dms_group_management': FULL},
    'second_opinion': {'dms_group_clinical': 'vue', 'dms_group_management': FULL},
    'billing': {'dms_group_billing': 'vue', 'dms_group_frontdesk': 'vu', 'dms_group_management': FULL},
    'staff': {'dms_group_hr_admin': FULL},
    'purchase': {'dms_group_billing': 'v', 'dms_group_management': FULL},
    'admin': {'dms_group_hr_admin': 'vu', 'dms_group_management': FULL},
}

PERM_LETTERS = {
    'v': ('perm_view', 'perm_download'),
    'u': ('perm_upload',),
    'e': ('perm_edit', 'perm_rename', 'perm_move'),
    'd': ('perm_delete',),
    's': ('perm_share',),
}

IMAGING_MIMETYPES_PREFIX = ('image/',)
IMAGING_MIMETYPES = ('application/dicom', 'application/x-dicom')
IMAGING_KEYWORDS = ('x-ray', 'xray', 'x ray', 'opg', 'cbct', 'rvg', 'iopa', 'radiograph', 'bitewing',
                    'panoramic', 'cephalo', 'scan', '.dcm')
CONSENT_KEYWORDS = ('consent',)
