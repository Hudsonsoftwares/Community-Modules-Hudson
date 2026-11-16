# -*- coding: utf-8 -*-
{
    'name': 'Indian Payroll Documents',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': "Store the employees' tax proof files in their Documents folders",
    'description': """
Copies the proof files of the employee tax declarations (80C, 80D, HRA, LTA, 24(b), 57(iia),
previous employer Form 12B / Form 16, ...) into the employee's Documents folder:
Employees / <employee> / Payroll / <tax year> / Tax Proofs / <section> - <file name>.

* Copied when the employee submits the proofs (and for proofs added while they are reviewed).
* A copy: deleting or moving it in Documents never changes the declaration.
* Removed proofs, or a declaration reset to draft: the copy goes to the Documents Trash.
* Proof Verified: the copies are locked (only Documents managers can change them).
* Payroll Settings: switch per company and a button to store the existing proofs.
""",
    'author': 'Hudson Software Solutions',
    'depends': [
        'hudson_in_payroll',
        'hudson_payroll_dms',
    ],
    'data': [
        'security/ir.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
