"""1.1.0: a task of a treatment plan's project is now one phase of the plan (it used to be one
treatment step). Old step tasks are replaced by phase tasks grouped by the steps' clinical phase,
and the board columns become Planned / In Progress / Done."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
               (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False, 'tracking_disable': True})

    old_task_ids = []
    if _column_exists(cr, 'project_task', 'dental_plan_line_id'):
        cr.execute("SELECT id FROM project_task WHERE dental_plan_line_id IS NOT NULL")
        old_task_ids = [row[0] for row in cr.fetchall()]
    old_stage_ids = []
    if _column_exists(cr, 'project_task_type', 'dental_phase'):
        cr.execute("SELECT id FROM project_task_type WHERE dental_phase IS NOT NULL")
        old_stage_ids = [row[0] for row in cr.fetchall()]

    # Sales order lines pointed at the old step tasks: re-linked to the phases below
    if old_task_ids:
        cr.execute("UPDATE sale_order_line SET task_id = NULL WHERE task_id IN %s", (tuple(old_task_ids),))
        env['project.task'].browse(old_task_ids).with_context(dental_line_sync=True).unlink()

    board_stages = env['project.task.type']._dental_board_stages()
    projects = env['project.project'].search([('dental_plan_id', '!=', False)])
    projects.write({'type_ids': [(6, 0, board_stages.ids)], 'label_tasks': 'Phases'})

    plans = env['dental.treatment.plan'].search([])
    plans._dental_ensure_project()
    lines = plans.line_ids
    lines.phase_task_id._dental_refresh_phase()
    for line in lines.filtered('sale_line_id'):
        line.sale_line_id.task_id = line.phase_task_id

    if old_stage_ids:
        stages = env['project.task.type'].browse(old_stage_ids).exists()
        stages.filtered(lambda s: not env['project.task'].search_count([('stage_id', '=', s.id)])).unlink()

    for table, column in (('project_task', 'dental_plan_line_id'), ('project_task_type', 'dental_phase')):
        if _column_exists(cr, table, column):
            cr.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}" CASCADE')
    _logger.info("dental_project: %s step tasks replaced by phases on %s plans", len(old_task_ids), len(plans))
