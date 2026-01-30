# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountVatProrata(models.Model):
    _inherit = 'account.vat.prorata'

    @api.depends("source_journal_ids")
    def _compute_prorata_type(self):
        for rec in self:
            if len(self.source_journal_ids) == 1 and self.source_journal_ids.vat_prorata_type:
                if rec.prorata_type != self.source_journal_ids.vat_prorata_type:
                    rec.prorata_type = self.source_journal_ids.vat_prorata_type

    @api.depends("prorata_type")
    def _compute_source_journal_ids(self):
        for rec in self:
            if rec.prorata_type:
                if len(rec.source_journal_ids) != 1 or rec.source_journal_ids.vat_prorata_type != rec.prorata_type:
                    journal = self.env['account.journal'].search([
                        ('vat_prorata_type', '=', rec.prorata_type),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)
                    if journal:
                        rec.source_journal_ids = [(6, 0, journal.ids)]

    prorata_type = fields.Selection([
        ('computed', 'Annual Prorata'),
        ('zero', 'Non-Lucrative Sector (0%)')],
        string="Calculation Type", required=True, default='computed', tracking=True,
        compute="_compute_prorata_type", readonly=True, store=True, precompute=True
    )
    source_journal_ids = fields.Many2many(compute="_compute_source_journal_ids", readonly=False, store=True, precompute=True)

    _sql_constraints = [
        ('date_company_uniq',
         'unique(date_to, date_from, company_id, prorata_type)',
         'A pro rata calculation already exists for these dates and this type!')
    ]

    @api.constrains('source_journal_ids', 'prorata_type')
    def _check_source_journals_type(self):
        for rec in self:
            if not rec.source_journal_ids:
                continue
            journal_types = rec.source_journal_ids.mapped('vat_prorata_type')
            if any(not t for t in journal_types):
                raise UserError(self.env._("All source journals must have a VAT Prorata Type defined."))
            if any(t != rec.prorata_type for t in journal_types):
                raise UserError(self.env._("Source journals type must match the calculation type (%s).") % rec.prorata_type)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company_id = res.get('company_id') or self.env.company.id
        
        # 1. First, we try to see if the 'computed' prorata for the year-to-date is done
        # Standard dates from base module: Jan 1st to end of last month
        date_to = res.get('date_to')
        date_from_annual = res.get('date_from') # This is Jan 1st thanks to base module
        
        annual_exists = self.search_count([
            ('date_to', '=', date_to),
            ('date_from', '=', date_from_annual),
            ('company_id', '=', company_id),
            ('prorata_type', '=', 'computed')
        ])
    
        if annual_exists:
            # 2. If annual is done, we switch to 'zero' type for the past month only
            # We recalculate date_from to be the 1st of the SAME month as date_to
            if date_to:
                date_from_monthly = date_to + relativedelta(day=1)
                
                # Check if 'zero' type already exists for this specific month
                zero_exists = self.search_count([
                    ('date_to', '=', date_to),
                    ('date_from', '=', date_from_monthly),
                    ('company_id', '=', company_id),
                    ('prorata_type', '=', 'zero')
                ])
                
                if not zero_exists:
                    journals = self.env['account.journal'].search([
                        ('vat_prorata_type', '=', 'zero'),
                        ('company_id', '=', company_id)
                    ])
                    res.update({
                        'prorata_type': 'zero',
                        'date_from': date_from_monthly,
                        'source_journal_ids': [(6, 0, journals.ids)],
                    })
        else:
            # 3. If annual is not done, we stick with 'computed' 
            # but filter journals accordingly
            journals = self.env['account.journal'].search([
                ('vat_prorata_type', '=', 'computed'),
                ('company_id', '=', company_id)
            ])
            res.update({
                'prorata_type': 'computed',
                'source_journal_ids': [(6, 0, journals.ids)],
            })
        return res

    def button_compute_ratio(self):
        self.ensure_one()
        if self.prorata_type == 'zero':
            self.write({
                'state': 'ratio',
                'computed_perct': 0.0,
                'used_perct': 0.0,
            })
            return True
        return super().button_compute_ratio()

    def _get_previous_prorata_domain(self):
        domain = super()._get_previous_prorata_domain()
        domain.append(('prorata_type', '=', self.prorata_type))
        return domain

    def _compute_warning_reversal(self):
        res = super()._compute_warning_reversal()
        for rec in self:
            if rec.prorata_type == "zero":
                rec.warning_reversal = False
