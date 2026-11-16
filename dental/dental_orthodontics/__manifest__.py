{
    'name': 'Dental Orthodontics',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Orthodontic chart: diagnosis, treatment plan, bracket chart, archwire sequence, adjustment visits and retention',
    'author': 'Hudson Software Solutions',
    'description': """
Orthodontic Chart
=================
One orthodontic chart per course of treatment, linked to the patient's dental case and to the
braces line of the treatment plan.

* Orthodontic assessment: Angle classification (molar and canine, right and left), overjet,
  overbite, crossbite, midlines, crowding / spacing per arch, curve of Spee, profile, skeletal
  pattern, IOTN (DHC and AC) and the main cephalometric values.
* Treatment plan: appliance, bracket prescription and slot, extraction pattern, anchorage,
  objectives and estimated duration.
* Bracket chart (FDI): what is bonded on each tooth (bracket, tube, band, attachment), with
  bond, failure and re-bond history, drawn as a chart of both arches.
* Adjustment visit log: archwires (upper / lower) with automatic archwire sequence, elastics,
  power chain, aligner trays, procedures, hygiene and compliance, next-visit interval.
  Completing a visit records a treatment session of the braces plan line, so the existing
  per-visit billing or monthly installment plan and the next-visit follow-up keep working.
* Phases: assessment, planned, active (leveling, working, finishing), retention, completed.
""",
    'depends': ['dental_core'],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'views/ortho_chart_views.xml',
        'views/dental_case_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_orthodontics/static/src/scss/ortho_chart.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
