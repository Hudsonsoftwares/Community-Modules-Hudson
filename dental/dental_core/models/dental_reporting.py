# -*- coding: utf-8 -*-
from odoo import models, fields, tools

class DentalBranchPerformanceReport(models.Model):
    _name = 'dental.branch.performance.report'
    _description = 'Branch Performance Analysis'
    _auto = False
    _order = 'date desc, branch_id'

    branch_id = fields.Many2one('res.company', string='Clinic Branch', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    total_appointments = fields.Integer(string='Total Appointments', readonly=True)
    completed_visits = fields.Integer(string='Completed Visits', readonly=True)
    active_visits = fields.Integer(string='Active Visits', readonly=True)
    cancelled_visits = fields.Integer(string='Cancelled / No-show', readonly=True)
    total_patients = fields.Integer(string='Unique Patients', readonly=True)
    total_doctors = fields.Integer(string='Active Doctors', readonly=True)
    total_duration = fields.Float(string='Total Hours', readonly=True)
    avg_duration = fields.Float(string='Avg Duration (Hours)', readonly=True)
    estimated_revenue = fields.Monetary(string='Estimated Revenue', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    row_number() OVER () AS id,
                    c.id AS branch_id,
                    a.date_start::date AS date,
                    count(a.id) AS total_appointments,
                    count(CASE WHEN a.state = 'completed' THEN 1 END) AS completed_visits,
                    count(CASE WHEN a.state IN ('checked_in', 'in_consultation') THEN 1 END) AS active_visits,
                    count(CASE WHEN a.state IN ('cancelled', 'no_show') THEN 1 END) AS cancelled_visits,
                    count(DISTINCT a.patient_id) AS total_patients,
                    count(DISTINCT a.doctor_id) AS total_doctors,
                    coalesce(sum(a.duration), 0.0) AS total_duration,
                    coalesce(avg(a.duration), 0.0) AS avg_duration,
                    coalesce(sum(coalesce(pt.list_price, 0.0) + coalesce(he.consultation_fee, 0.0)), 0.0) AS estimated_revenue,
                    c.currency_id AS currency_id
                FROM res_company c
                JOIN dental_appointment a ON a.branch_id = c.id
                LEFT JOIN product_template pt ON a.treatment_id = pt.id
                LEFT JOIN hr_employee he ON a.doctor_id = he.id
                GROUP BY c.id, a.date_start::date, c.currency_id
            )
        """ % self._table)


class DentalRevenueReport(models.Model):
    _name = 'dental.revenue.report'
    _description = 'Dental Revenue Analysis'
    _auto = False
    _order = 'date desc, id desc'

    branch_id = fields.Many2one('res.company', string='Clinic Branch', readonly=True)
    doctor_id = fields.Many2one('hr.employee', string='Doctor', readonly=True)
    patient_id = fields.Many2one('res.partner', string='Patient', readonly=True)
    treatment_id = fields.Many2one('product.template', string='Dental Treatment', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('in_consultation', 'In Consultation'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show')
    ], string='Status', readonly=True)
    consultation_revenue = fields.Monetary(string='Consultation Fee', readonly=True)
    treatment_revenue = fields.Monetary(string='Treatment Fee', readonly=True)
    total_revenue = fields.Monetary(string='Total Revenue', readonly=True)
    visit_count = fields.Integer(string='Visits', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    a.id AS id,
                    a.branch_id AS branch_id,
                    a.doctor_id AS doctor_id,
                    a.patient_id AS patient_id,
                    a.treatment_id AS treatment_id,
                    a.date_start::date AS date,
                    a.state AS state,
                    coalesce(he.consultation_fee, 0.0) AS consultation_revenue,
                    coalesce(pt.list_price, 0.0) AS treatment_revenue,
                    (coalesce(he.consultation_fee, 0.0) + coalesce(pt.list_price, 0.0)) AS total_revenue,
                    1 AS visit_count,
                    c.currency_id AS currency_id
                FROM dental_appointment a
                JOIN res_company c ON a.branch_id = c.id
                LEFT JOIN product_template pt ON a.treatment_id = pt.id
                LEFT JOIN hr_employee he ON a.doctor_id = he.id
                WHERE a.state != 'cancelled'
            )
        """ % self._table)


class DentalTreatmentReport(models.Model):
    _name = 'dental.treatment.report'
    _description = 'Dental Treatment Statistics'
    _auto = False
    _order = 'procedure_count desc, total_amount desc'

    treatment_id = fields.Many2one('product.template', string='Treatment / Procedure', readonly=True)
    category_id = fields.Many2one('product.category', string='Category', readonly=True)
    doctor_id = fields.Many2one('hr.employee', string='Doctor', readonly=True)
    branch_id = fields.Many2one('res.company', string='Clinic Branch', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('in_consultation', 'In Consultation'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show')
    ], string='Status', readonly=True)
    procedure_count = fields.Integer(string='Procedure Count', readonly=True)
    total_amount = fields.Monetary(string='Total Revenue', readonly=True)
    avg_price = fields.Monetary(string='Average Price', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    a.id AS id,
                    a.treatment_id AS treatment_id,
                    pt.categ_id AS category_id,
                    a.doctor_id AS doctor_id,
                    a.branch_id AS branch_id,
                    a.date_start::date AS date,
                    a.state AS state,
                    1 AS procedure_count,
                    coalesce(pt.list_price, 0.0) AS total_amount,
                    coalesce(pt.list_price, 0.0) AS avg_price,
                    c.currency_id AS currency_id
                FROM dental_appointment a
                JOIN res_company c ON a.branch_id = c.id
                JOIN product_template pt ON a.treatment_id = pt.id
                WHERE a.state != 'cancelled'
            )
        """ % self._table)
