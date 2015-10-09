# -*- coding:utf-8 -*-
##############################################################################
#
#    Copyright (C) 2015 Savoir-faire Linux. All Rights Reserved.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from openerp import models, fields, api, _
from openerp.exceptions import Warning

from .hr_fiscal_year import get_schedules


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    name = fields.Char(
                       'Name', 
                       required=True, 
                       readonly=True, 
                       states={'draft': [('readonly', False)]},
                       default=lambda obj:obj.env['ir.sequence']\
                       .get('hr.payslip.run')
                       )
    company_id = fields.Many2one(
                                 'res.company', 
                                 'Company',
                                 states={'close': [('readonly', True)]},
                                 default=lambda obj: obj.env.user.company_id
                                 )
    hr_period_id = fields.Many2one(
                                   'hr.period', 
                                   string='Period',
                                   states={'close': [('readonly', True)]}
                                   )
    date_payment = fields.Date(
                               'Date of Payment', 
                               states={'close': [('readonly', True)]}
                               )
    schedule_pay = fields.Selection(
                                    get_schedules, 
                                    'Scheduled Pay', 
                                    states={'close': [('readonly', True)]}
                                    )

    @api.multi
    @api.constrains('hr_period_id', 'company_id')
    def _check_period_company(self):
        for run in self:
            if run.hr_period_id:
                if run.hr_period_id.company_id != run.company_id:
                    raise Warning("The company on the selected period must be "
                                  "the same as the company on the payslip "
                                  "batch.")
        return True

    @api.multi
    @api.constrains('hr_period_id', 'schedule_pay')
    def _check_period_schedule(self):
        for run in self:
            if run.hr_period_id:
                if run.hr_period_id.schedule_pay != run.schedule_pay:
                    raise Warning("The schedule on the selected period must be "
                                  "the same as the schedule on the payslip "
                                  "batch.")
        return True
    
    @api.model
    def get_default_schedule(self, company_id):
        company = self.env['res.company'].browse(company_id)

        fy_obj = self.env['hr.fiscalyear']

        fys = fy_obj.search([
            ('state', '=', 'open'),
            ('company_id', '=', company.id),
        ])

        return (
            fys[0].schedule_pay
            if len(fys) else 'monthly'
        )

    @api.onchange('company_id', 'schedule_pay')
    @api.one
    def onchange_company_id(self):
        schedule_pay = self.schedule_pay or \
        self.get_default_schedule(self.company_id.id)

        if len(self.company_id) and schedule_pay:
            period = self.env['hr.period'].get_next_period(self.company_id.id,
                                                           schedule_pay,)
            self.hr_period_id = period.id if period else False,

    @api.onchange('hr_period_id')
    def onchange_period_id(self):
        if len(self.hr_period_id):
            self.date_start = self.hr_period_id.date_start
            self.date_end = self.hr_period_id.date_stop
            self.date_payment = self.hr_period_id.date_payment
            self.schedule_pay = self.hr_period_id.schedule_pay

    @api.model
    def create(self, vals):
        """
        Keep compatibility between modules
        """
        if vals.get('date_end') and not vals.get('date_payment'):
            vals.update({'date_payment': vals['date_end']})
        return super(HrPayslipRun, self).create(vals)

    @api.multi
    def get_payslip_employees_wizard(self):
        """ Replace the static action used to call the wizard
        """
        self.ensure_one()
        payslip_run = self[0]

        view_ref = self.env['ir.model.data'].get_object_reference(
                                'hr_payroll', 'view_hr_payslip_by_employees')

        view_id = view_ref and view_ref[1] or False

        company = payslip_run.company_id

        employee_obj = self.env['hr.employee']

        employees = employee_obj.search([('company_id', '=', company.id)])

        employee_ids = [
            emp.id for emp in employees
            if emp.contract_id.schedule_pay == payslip_run.schedule_pay
        ]

        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Payslips'),
            'res_model': 'hr.payslip.employees',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'new',
            'context': {
                'default_company_id': company.id,
                'default_schedule_pay': payslip_run.schedule_pay,
                'default_employee_ids': [(6, 0, employee_ids)],
            }
        }

    @api.multi
    def close_payslip_run(self):
        for run in self:
            if next((p for p in run.slip_ids if p.state == 'draft'), False):
                raise Warning("The payslip batch %s still has unconfirmed "
                "pay slips." % (run.name))

        self.update_periods()
        return super(HrPayslipRun, self).close_payslip_run()

    @api.multi
    def draft_payslip_run(self):
        for run in self:
            run.hr_period_id.button_re_open()
        return super(HrPayslipRun, self).draft_payslip_run()

    @api.multi
    def update_periods(self):
        for run in self:
            period = run.hr_period_id
            if len(period):
                # Close the current period
                period.button_close()

                # Open the next period of the fiscal year
                fiscal_year = period.fiscalyear_id
                next_period = fiscal_year.search_period(
                    number=period.number + 1)

                if next_period:
                    next_period.button_open()